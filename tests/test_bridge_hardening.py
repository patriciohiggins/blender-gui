#!/usr/bin/env python3
"""Regression tests for the v1.1.1 bridge hardening (single-user guard + resource limits).

Runs without Blender by injecting a minimal fake `bpy` module.
"""
import importlib.util
import json
import os
import socket
import sys
import threading
import time
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(REPO, "scripts", "hermes_blender_bridge.py")

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
})
os.environ.pop("HERMES_BRIDGE_ALLOW_SHARED", None)

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


def request(code="RESULT=1+1", timeout=3, raw=None):
    s = socket.create_connection(("127.0.0.1", PORT), timeout=timeout)
    s.settimeout(timeout)
    payload = raw if raw is not None else (json.dumps({"id": 1, "code": code}) + "\n").encode()
    s.sendall(payload)
    data = b""
    while b"\n" not in data:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data.split(b"\n", 1)[0].decode("utf-8", "replace"))


# 1. happy path still works
r = request()
check("code ejecutable", r.get("ok") is True and r.get("result") == "2", str(r))

# 2. code size bound
r = request(code="#" + "x" * 200)
check("limite de tamano de code", r.get("ok") is False and "code too large" in r.get("error", ""), str(r))

# 3. request line bound (no newline + oversize)
r = request(raw=b"x" * 3000)
check("limite de linea", r.get("ok") is False and "request too large" in r.get("error", ""), str(r))

# 4. invalid JSON is rejected cleanly
r = request(raw=b"{bad}\n")
check("json invalido", r.get("ok") is False and r.get("error") == "invalid json", str(r))

# 5. idle clients get a timeout instead of holding a thread forever
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

# 6. client concurrency cap
slots = [socket.create_connection(("127.0.0.1", PORT), timeout=3) for _ in range(2)]
r = request(timeout=2)
check("tope de clientes concurrentes", "too many clients" in r.get("error", ""), str(r))
for s in slots:
    s.close()
time.sleep(1.4)  # let the two idle handlers time out and release slots

# 7. queue depth cap
while not bridge._cmd_queue.empty():
    bridge._cmd_queue.get_nowait()
for _ in range(bridge.MAX_QUEUE):
    bridge._cmd_queue.put_nowait(("RESULT=1", threading.Event(), {}))
r = request(timeout=2)
check("tope de cola", "command queue full" in r.get("error", ""), str(r))
while not bridge._cmd_queue.empty():
    bridge._cmd_queue.get_nowait()

# 8. shared-host / root guard
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

report = "/home/k2/.hermes/cache/scratch/blander_hardening_tests.txt"
with open(report, "w") as f:
    f.write(f"failures={len(failures)} list={failures}\n")
print(f"RESULTADO: {len(failures)} fallos -> {report}")
sys.exit(1 if failures else 0)
