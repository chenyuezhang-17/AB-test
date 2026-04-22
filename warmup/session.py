"""Persistent browser session for @Leegowlessie — port 9223, separate socket.

Usage: python -m warmup.session
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

# Allow imports from action/browser
sys.path.insert(0, str(Path(__file__).parent.parent / "action"))

from browser.controller import BrowserController

_PORT       = os.environ.get("CHROME_PORT", "9223")
SOCKET_PATH = f"/tmp/leego-browser-{_PORT}.sock"
PID_FILE    = f"/tmp/leego-browser-{_PORT}.pid"
CDP_URL     = f"http://localhost:{_PORT}"


async def handle_client(reader, writer, ctrl):
    try:
        data = await asyncio.wait_for(reader.read(65536), timeout=10)
        request = json.loads(data.decode())
    except Exception as e:
        writer.write(json.dumps({"error": f"bad request: {e}"}).encode())
        await writer.drain(); writer.close(); return

    cmd = request.get("cmd", "")
    arg = request.get("arg", "")
    result = {}

    try:
        if cmd == "ping":
            info = await ctrl.get_page_info()
            result = {"ok": True, **info}
        elif cmd == "goto":
            await ctrl.navigate(arg)
            await asyncio.sleep(1)
            result = {"ok": True, **(await ctrl.get_page_info())}
        elif cmd == "eval":
            value = await ctrl.chrome.evaluate(arg)
            result = {"ok": True, "value": value}
        elif cmd == "type":
            await ctrl.type_text(arg)
            result = {"ok": True}
        elif cmd == "scroll_down":
            await ctrl.scroll_down(int(arg) if arg else 500)
            result = {"ok": True}
        elif cmd == "scroll_up":
            await ctrl.scroll_up(int(arg) if arg else 500)
            result = {"ok": True}
        elif cmd == "wait":
            await asyncio.sleep(float(arg) if arg else 2)
            result = {"ok": True}
        elif cmd == "stop":
            result = {"ok": True}
            writer.write(json.dumps(result).encode())
            writer.write_eof(); await writer.drain(); writer.close()
            asyncio.get_event_loop().stop(); return
        else:
            result = {"ok": False, "error": f"unknown cmd: {cmd}"}
    except Exception as e:
        result = {"ok": False, "error": str(e)}

    writer.write(json.dumps(result, ensure_ascii=False).encode())
    writer.write_eof(); await writer.drain(); writer.close()


async def run_server():
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)

    ctrl = BrowserController(cdp_url=CDP_URL)
    # Connect to x.com if open, otherwise any existing tab
    try:
        await ctrl.start("https://x.com/home")
    except Exception:
        await ctrl.start(None)   # connect to first available tab

    server = await asyncio.start_unix_server(
        lambda r, w: handle_client(r, w, ctrl), path=SOCKET_PATH
    )
    Path(PID_FILE).write_text(str(os.getpid()))
    print(json.dumps({"ok": True, "status": "leegowlessie_session_started"}))
    sys.stdout.flush()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: loop.stop())

    try:
        await server.serve_forever()
    except asyncio.CancelledError:
        pass
    finally:
        await ctrl.close()
        for f in [SOCKET_PATH, PID_FILE]:
            try: os.unlink(f)
            except: pass


if __name__ == "__main__":
    asyncio.run(run_server())
