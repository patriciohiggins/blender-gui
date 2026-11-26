#!/usr/bin/env python3
"""Regression tests for the v1.2.0 bridge: auth, limits, guard, structured results, progress/cancel.

Runs without Blender by injecting a minimal fake `bpy` module.
"""
import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
import time
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "scripts")
BRIDGE = os.path.join(SCRIPTS, "hermes_blender_bridge.py")
TEST_TOKEN = "t" * 64

# Free port so the test never touches the real 7999.
_probe = socket.socket()
_probe.bind(("127.0.0.1", 0))
PORT = _probe.getsockname()[1]
_probe.close()

os.environ.update({
    "HERMES_BRIDGE_PORT": str(PORT),
    "HERMES_BRIDGE_READ_TIMEOUT": "1",
    "HERMES_BRIDGE_MAX_REQUEST_BYTES": "2048",
    "HERMES_BRIDGE_MAX_CODE_BYTES": "128",
    "HERMES_BRIDGE_MAX_QUEUE": "2",
    "HERMES_BRIDGE_MAX_CLIENTS": "2",
    "HERMES_BRIDGE_TOKEN": TEST_TOKEN,
})
os.environ.pop("HERMES_BRIDGE_ALLOW_SHARED", None)
sys.path.insert(0, SCRIPTS)  # bridge_auth import


def _run_timer(fn, first_interval=None, persistent=False):
    """Mimic Blender's main-thread timer so queued commands actually execute."""
    def loop():
        while True:
            try:
                fn()
            except Exception:
                pass
            time.sleep(0.01)
    threading.Thread(target=loop, daemon=True).start()


fake_bpy = types.ModuleType("bpy")
setattr(fake_bpy, "app", types.SimpleNamespace(
    timers=types.SimpleNamespace(register=_run_timer),
    version_string="fake",
))
sys.modules["bpy"] = fake_bpy

spec = importlib.util.spec_from_file_location("bridge_hardened", BRIDGE)
assert spec is not None and spec.loader is not None
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

failures = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"{status} {name} {detail}")
    if not cond:
        failures.append(name)


def request(code="RESULT=1+1", timeout=3, raw=None, req_id=1, token=TEST_TOKEN, cancel_id=None):
    s = socket.create_connection(("127.0.0.1", PORT), timeout=timeout)
    s.settimeout(timeout)
    if raw is not None:
        payload = raw
    else:
        obj = {"id": req_id}
        if cancel_id is not None:
            obj["cancel"] = cancel_id
        else:
            obj["code"] = code
        if token is not None:
            obj["token"] = token
        payload = (json.dumps(obj) + "\n").encode()
    s.sendall(payload)
    data = b""
    while b"\n" not in data:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data.split(b"\n", 1)[0].decode("utf-8", "replace"))


# --- v1.1.1 defenses -------------------------------------------------------
r = request()
check("code ejecutable", r.get("ok") is True and r.get("result") == 2, str(r))

r = request(code="#" + "x" * 200)
check("limite de tamano de code", r.get("ok") is False and "code too large" in r.get("error", ""), str(r))

r = request(raw=b"x" * 3000)
check("limite de linea", r.get("ok") is False and "request too large" in r.get("error", ""), str(r))

r = request(raw=b"{bad}\n")
check("json invalido", r.get("ok") is False and r.get("error") == "invalid json", str(r))

idle = socket.create_connection(("127.0.0.1", PORT), timeout=3)
time.sleep(1.4)
data = b""
while b"\n" not in data:
    chunk = idle.recv(65536)
    if not chunk:
        break
    data += chunk
idle.close()
r = json.loads(data.split(b"\n", 1)[0])
check("timeout de cliente inactivo", "request timeout" in r.get("error", ""), str(r))

slots = [socket.create_connection(("127.0.0.1", PORT), timeout=3) for _ in range(2)]
r = request(timeout=2)
check("tope de clientes concurrentes", "too many clients" in r.get("error", ""), str(r))
for s in slots:
    s.close()
time.sleep(1.4)

while not bridge._cmd_queue.empty():
    bridge._cmd_queue.get_nowait()
for _ in range(bridge.MAX_QUEUE):
    bridge._cmd_queue.put_nowait(("RESULT=1", threading.Event(), {},
                                  {"cancel": threading.Event(), "progress": []}))
r = request(timeout=2)
check("tope de cola", "command queue full" in r.get("error", ""), str(r))
while not bridge._cmd_queue.empty():
    bridge._cmd_queue.get_nowait()

real_reason = getattr(bridge, "_shared_host_reason")
setattr(bridge, "_shared_host_reason", lambda: "other users logged in: intruder")
setattr(bridge, "_started", False)
try:
    bridge.start()
    check("guard de host compartido", False, "start() no rechazo el host")
except RuntimeError as e:
    check("guard de host compartido", "HERMES_BRIDGE_REFUSED" in str(e), str(e))
finally:
    setattr(bridge, "_shared_host_reason", real_reason)
    setattr(bridge, "_started", True)

# --- v1.2.0: autenticacion -------------------------------------------------
r = request(token=None)
check("sin token rechazado", r.get("ok") is False and r.get("error") == "unauthorized", str(r))

r = request(token="x" * 64)
check("token incorrecto rechazado", r.get("ok") is False and r.get("error") == "unauthorized", str(r))

# --- v1.2.0: resultados estructurados --------------------------------------
r = request(code="RESULT={'a':1,'b':[2,3]}")
check("resultado estructurado", r.get("result") == {"a": 1, "b": [2, 3]}, str(r))

r = request(code="PROGRESS('paso 1')\nRESULT='ok'")
check("eventos de progreso", "paso 1" in r.get("progress", []), str(r))

# --- v1.2.0: cancelacion cooperativa ---------------------------------------
captured = {}


def long_call():
    captured["r"] = request(
        code="import time\nPROGRESS('start')\nwhile not CANCELLED(): time.sleep(0.01)\nRESULT='done'",
        timeout=5, req_id=77)


worker = threading.Thread(target=long_call, daemon=True)
worker.start()
time.sleep(0.3)
r = request(cancel_id=77, timeout=3)
check("ack de cancelacion", r.get("ok") is True and r.get("cancelled") is True, str(r))
worker.join(timeout=5)
check("cancelacion cooperativa", captured.get("r", {}).get("cancelled") is True
      and "start" in captured.get("r", {}).get("progress", []), str(captured.get("r")))

report = os.environ.get("HERMES_TEST_REPORT") or os.path.join(
    tempfile.gettempdir(), "blander_hardening_tests.txt")
os.makedirs(os.path.dirname(report), exist_ok=True)
with open(report, "w") as f:
    f.write(f"failures={len(failures)} list={failures}\n")
print(f"RESULTADO: {len(failures)} fallos -> {report}")
sys.exit(1 if failures else 0)
