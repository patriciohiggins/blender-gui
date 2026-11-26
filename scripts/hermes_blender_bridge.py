"""Hermes control bridge for a running Blender GUI.

Start Blender with:  blender --python <skill_dir>/scripts/hermes_blender_bridge.py
It opens a localhost-only JSON-lines server on port 7999. Commands run in
Blender's main thread via bpy.app.timers so bpy.ops calls stay valid.
"""
import bpy
import contextlib
import io
import json
import queue
import socketserver
import threading
import traceback

PORT = 7999
_cmd_queue = queue.Queue()
_started = False


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
    def handle(self):
        try:
            raw = self.rfile.readline().decode("utf-8")
            req = json.loads(raw)
            event = threading.Event()
            holder = {}
            _cmd_queue.put((req.get("code", ""), event, holder))
            if not event.wait(120):
                holder = {"ok": False, "error": "timeout in Blender main thread"}
            resp = {
                "id": req.get("id"),
                "ok": holder.get("ok", False),
                "output": holder.get("output", ""),
                "result": holder.get("result", ""),
                "error": holder.get("error", ""),
            }
        except Exception:
            resp = {"ok": False, "error": traceback.format_exc()}
        self.wfile.write((json.dumps(resp) + "\n").encode("utf-8"))


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start():
    global _started
    if _started:
        return
    _started = True
    server = _Server(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    bpy.app.timers.register(_timer, first_interval=0.1, persistent=True)
    print("HERMES_BRIDGE_READY port", PORT)


start()
