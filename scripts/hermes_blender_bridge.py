"""Hermes control bridge for a running Blender GUI.

Start Blender with:  blender --python <skill_dir>/scripts/hermes_blender_bridge.py
It opens a localhost-only JSON-lines server on port 7999. Commands run in
Blender's main thread via bpy.app.timers so bpy.ops calls stay valid.

Hardening (v1.2.0):
  * Token authentication required on every request (0600 token file outside
    the skill directory, or HERMES_BRIDGE_TOKEN / HERMES_BRIDGE_TOKEN_FILE).
  * Refuses to start as root or on a host with other logged-in users unless
    HERMES_BRIDGE_ALLOW_SHARED=1 is explicitly set.
  * Bounds request size, code size, read time, queue depth and client count.
  * RESULT is returned as structured JSON; PROGRESS() events and cooperative
    cancellation via CANCELLED() / {"cancel": id} are available.
  * Warns when the running Blender differs from the pinned 4.4.3 build.
"""
import bpy
import contextlib
import getpass
import hmac
import io
import json
import os
import queue
import socketserver
import subprocess
import sys
import threading
import traceback

# Blender does not add the --python script directory to sys.path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bridge_auth

PORT = int(os.environ.get("HERMES_BRIDGE_PORT", "7999"))
READ_TIMEOUT = float(os.environ.get("HERMES_BRIDGE_READ_TIMEOUT", "5"))
MAX_REQUEST_BYTES = int(os.environ.get("HERMES_BRIDGE_MAX_REQUEST_BYTES", str(64 * 1024)))
MAX_CODE_BYTES = int(os.environ.get("HERMES_BRIDGE_MAX_CODE_BYTES", str(32 * 1024)))
MAX_QUEUE = int(os.environ.get("HERMES_BRIDGE_MAX_QUEUE", "16"))
MAX_CLIENTS = int(os.environ.get("HERMES_BRIDGE_MAX_CLIENTS", "8"))
EXEC_TIMEOUT = 120
EXPECTED_BLENDER = "4.4.3"

_cmd_queue = queue.Queue(maxsize=MAX_QUEUE)
_client_slots = threading.BoundedSemaphore(MAX_CLIENTS)
_active = {}
_active_lock = threading.Lock()
_token = None
_started = False


def _shared_host_reason():
    """Return a reason string when this host must not run a code-execution bridge."""
    if os.name != "posix":
        return None
    if os.geteuid() == 0:
        return "running as root"
    me = getpass.getuser()
    try:
        out = subprocess.run(["who"], capture_output=True, text=True, timeout=2, check=False).stdout
    except Exception:
        out = ""
    others = sorted({line.split()[0] for line in out.splitlines()
                     if line.split() and line.split()[0] != me})
    if others:
        return "other users logged in: " + ", ".join(others)
    return None


def _execute(code, control):
    ns = {
        "bpy": bpy,
        "__builtins__": __builtins__,
        "PROGRESS": lambda msg: control["progress"].append(str(msg)),
        "CANCELLED": lambda: control["cancel"].is_set(),
    }
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(code, "<hermes>", "exec"), ns)
    # Structured value on purpose: clients get JSON, not a forced str().
    return {"output": buf.getvalue(), "result": ns.get("RESULT", None)}


def _timer():
    try:
        code, event, holder, control = _cmd_queue.get_nowait()
    except queue.Empty:
        return 0.05
    try:
        holder.update(_execute(code, control))
        holder["ok"] = True
        holder["progress"] = control["progress"]
        holder["cancelled"] = control["cancel"].is_set()
    except Exception:
        holder["ok"] = False
        holder["error"] = traceback.format_exc()
        holder["progress"] = control["progress"]
        holder["cancelled"] = control["cancel"].is_set()
    event.set()
    return 0.01


class _Handler(socketserver.StreamRequestHandler):
    def _send(self, resp):
        try:
            payload = json.dumps(resp, default=str)
        except Exception:
            payload = json.dumps({"ok": False, "error": "unserializable response"})
        try:
            self.wfile.write((payload + "\n").encode("utf-8"))
        except Exception:
            pass  # client may already be gone; never let response I/O kill the thread

    def _authorized(self, req):
        return hmac.compare_digest(str(req.get("token", "")), str(_token or ""))

    def handle(self):
        if not _client_slots.acquire(blocking=False):
            self._send({"ok": False, "error": "too many clients"})
            return
        req_id = None
        try:
            self.request.settimeout(READ_TIMEOUT)
            try:
                raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
            except TimeoutError:
                self._send({"ok": False, "error": "request timeout"})
                return
            if not raw.endswith(b"\n") or len(raw) > MAX_REQUEST_BYTES:
                self._send({"ok": False, "error": "request too large or incomplete"})
                return
            try:
                req = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send({"ok": False, "error": "invalid json"})
                return
            req_id = str(req.get("id"))
            if not self._authorized(req):
                self._send({"ok": False, "error": "unauthorized"})
                return

            # Cooperative cancellation of a previously submitted command id.
            if "cancel" in req:
                with _active_lock:
                    target = _active.get(str(req.get("cancel")))
                if target:
                    target.set()
                self._send({"id": req.get("id"), "ok": True, "cancelled": bool(target)})
                return

            code = req.get("code", "")
            if not isinstance(code, str) or len(code.encode("utf-8")) > MAX_CODE_BYTES:
                self._send({"ok": False, "error": "code too large or invalid"})
                return

            event = threading.Event()
            control = {"cancel": threading.Event(), "progress": []}
            holder = {}
            with _active_lock:
                _active[req_id] = control["cancel"]
            try:
                try:
                    _cmd_queue.put_nowait((code, event, holder, control))
                except queue.Full:
                    self._send({"ok": False, "error": "command queue full"})
                    return
                if not event.wait(EXEC_TIMEOUT):
                    control["cancel"].set()
                    holder = {"ok": False, "error": "timeout in Blender main thread"}
                self._send({
                    "id": req.get("id"),
                    "ok": holder.get("ok", False),
                    "output": holder.get("output", ""),
                    "result": holder.get("result", None),
                    "progress": holder.get("progress", []),
                    "cancelled": bool(holder.get("cancelled", control["cancel"].is_set())),
                    "error": holder.get("error", ""),
                })
            finally:
                with _active_lock:
                    _active.pop(req_id, None)
        except Exception:
            self._send({"ok": False, "error": traceback.format_exc()})
        finally:
            _client_slots.release()


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 16


def start():
    global _started, _token
    if _started:
        return
    reason = _shared_host_reason()
    if reason and os.environ.get("HERMES_BRIDGE_ALLOW_SHARED") != "1":
        raise RuntimeError("HERMES_BRIDGE_REFUSED: " + reason
                           + "; set HERMES_BRIDGE_ALLOW_SHARED=1 only if you accept local RCE here")
    if reason:
        print("HERMES_BRIDGE_WARNING: shared-host override active:", reason)
    _token = bridge_auth.ensure_token()
    print("HERMES_BRIDGE_AUTH: token activo desde", bridge_auth.default_path()
          if not os.environ.get("HERMES_BRIDGE_TOKEN") else "HERMES_BRIDGE_TOKEN")
    version = getattr(getattr(bpy, "app", None), "version_string", "")
    if version and not str(version).startswith(EXPECTED_BLENDER):
        print("HERMES_BRIDGE_WARNING: Blender", version, "!= probado", EXPECTED_BLENDER)
    print("HERMES_BRIDGE_WARNING: code-execution bridge on 127.0.0.1:%d; "
          "no reenviar ni exponer el puerto" % PORT)
    _started = True
    server = _Server(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    bpy.app.timers.register(_timer, first_interval=0.1, persistent=True)
    print("HERMES_BRIDGE_READY port", PORT)


start()
