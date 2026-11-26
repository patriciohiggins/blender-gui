"""Hermes control bridge for a running Blender GUI.

Start Blender with:  blender --python <skill_dir>/scripts/hermes_blender_bridge.py
It opens a localhost-only JSON-lines server on port 7999. Commands run in
Blender's main thread via bpy.app.timers so bpy.ops calls stay valid.

Hardening (v1.1.1):
  * Refuses to start as root or on a host with other logged-in users unless
    HERMES_BRIDGE_ALLOW_SHARED=1 is explicitly set (single-user hosts only).
  * Bounds request size, code size, read time, queue depth and client count.
  * Still executes arbitrary code by design: there is NO authentication yet.
    Keep the port local and send only trusted code.
"""
import bpy
import contextlib
import getpass
import io
import json
import os
import queue
import socketserver
import subprocess
import threading
import traceback

PORT = int(os.environ.get("HERMES_BRIDGE_PORT", "7999"))
READ_TIMEOUT = float(os.environ.get("HERMES_BRIDGE_READ_TIMEOUT", "5"))
MAX_REQUEST_BYTES = int(os.environ.get("HERMES_BRIDGE_MAX_REQUEST_BYTES", str(64 * 1024)))
MAX_CODE_BYTES = int(os.environ.get("HERMES_BRIDGE_MAX_CODE_BYTES", str(32 * 1024)))
MAX_QUEUE = int(os.environ.get("HERMES_BRIDGE_MAX_QUEUE", "16"))
MAX_CLIENTS = int(os.environ.get("HERMES_BRIDGE_MAX_CLIENTS", "8"))
EXEC_TIMEOUT = 120

_cmd_queue = queue.Queue(maxsize=MAX_QUEUE)
_client_slots = threading.BoundedSemaphore(MAX_CLIENTS)
_started = False


def _shared_host_reason():
    """Return a reason string when this host must not run an unauthenticated RCE bridge."""
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


def _execute(code):
    ns = {"bpy": bpy, "__builtins__": __builtins__}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(code, "<hermes>", "exec"), ns)
    return {"output": buf.getvalue(), "result": str(ns.get("RESULT", ""))}


def _timer():
    try:
        code, event, holder = _cmd_queue.get_nowait()
    except queue.Empty:
        return 0.05
    try:
        holder.update(_execute(code))
        holder["ok"] = True
    except Exception:
        holder["ok"] = False
        holder["error"] = traceback.format_exc()
    event.set()
    return 0.01


class _Handler(socketserver.StreamRequestHandler):
    def _send(self, resp):
        try:
            self.wfile.write((json.dumps(resp) + "\n").encode("utf-8"))
        except Exception:
            pass  # client may already be gone; never let response I/O kill the thread

    def handle(self):
        if not _client_slots.acquire(blocking=False):
            self._send({"ok": False, "error": "too many clients"})
            return
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
            code = req.get("code", "")
            if not isinstance(code, str) or len(code.encode("utf-8")) > MAX_CODE_BYTES:
                self._send({"ok": False, "error": "code too large or invalid"})
                return
            event = threading.Event()
            holder = {}
            try:
                _cmd_queue.put_nowait((code, event, holder))
            except queue.Full:
                self._send({"ok": False, "error": "command queue full"})
                return
            if not event.wait(EXEC_TIMEOUT):
                holder = {"ok": False, "error": "timeout in Blender main thread"}
            self._send({
                "id": req.get("id"),
                "ok": holder.get("ok", False),
                "output": holder.get("output", ""),
                "result": holder.get("result", ""),
                "error": holder.get("error", ""),
            })
        except Exception:
            self._send({"ok": False, "error": traceback.format_exc()})
        finally:
            _client_slots.release()


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 16


def start():
    global _started
    if _started:
        return
    reason = _shared_host_reason()
    if reason and os.environ.get("HERMES_BRIDGE_ALLOW_SHARED") != "1":
        raise RuntimeError("HERMES_BRIDGE_REFUSED: " + reason
                           + "; set HERMES_BRIDGE_ALLOW_SHARED=1 only if you accept local RCE here")
    if reason:
        print("HERMES_BRIDGE_WARNING: shared-host override active:", reason)
    print("HERMES_BRIDGE_WARNING: unauthenticated code-execution bridge on 127.0.0.1:%d; "
          "do not forward or expose this port" % PORT)
    _started = True
    server = _Server(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    bpy.app.timers.register(_timer, first_interval=0.1, persistent=True)
    print("HERMES_BRIDGE_READY port", PORT)


start()
