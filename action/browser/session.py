"""Persistent browser session using a Unix socket server.

Keeps a single Chrome CDP connection alive across multiple CLI calls.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

from browser.controller import BrowserController

_PORT = os.environ.get("CHROME_PORT", "9222")
SOCKET_PATH = f"/tmp/leego-browser-{_PORT}.sock"
PID_FILE = "/tmp/social-browser.pid"
DEFAULT_CDP = f"http://localhost:{_PORT}"


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    ctrl: BrowserController,
):
    """Handle a single command from the CLI."""
    try:
        chunks = []
        while True:
            chunk = await asyncio.wait_for(reader.read(65536), timeout=10)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        request = json.loads(data.decode())
    except Exception as e:
        writer.write(json.dumps({"error": f"bad request: {e}"}).encode())
        await writer.drain()
        writer.close()
        return

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
            info = await ctrl.get_page_info()
            result = {"ok": True, **info}

        elif cmd == "label":
            labels = await ctrl.label_elements()
            result = {
                "ok": True,
                "count": len(labels),
                "elements": labels,
                "formatted": ctrl.format_labels(labels),
            }

        elif cmd == "click":
            el = await ctrl.click_label(arg)
            if el:
                await asyncio.sleep(0.5)
                info = await ctrl.get_page_info()
                focus_info = await ctrl.get_focused_info()
                result = {"ok": True, "clicked": el, **info, **focus_info}
            else:
                result = {"ok": False, "error": f"label '{arg}' not found"}

        elif cmd == "type":
            await ctrl.type_text(arg)
            # Verify by reading back focused element
            focus_info = await ctrl.get_focused_info()
            result = {"ok": True, "typed": arg, **focus_info}

        elif cmd == "fill":
            fill_result = await ctrl.fill_text(arg)
            result = {"ok": fill_result.get("ok", False), **fill_result}

        elif cmd == "snapshot":
            text = await ctrl.snapshot()
            result = {"ok": True, "snapshot": text}

        elif cmd == "enter":
            await ctrl.press_key("Enter")
            result = {"ok": True}

        elif cmd == "scroll_down":
            amount = int(arg) if arg else 500
            await ctrl.scroll_down(amount)
            result = {"ok": True}

        elif cmd == "scroll_up":
            amount = int(arg) if arg else 500
            await ctrl.scroll_up(amount)
            result = {"ok": True}

        elif cmd == "screenshot":
            path = arg or "screenshot.jpg"
            await ctrl.screenshot(save_path=path)
            result = {"ok": True, "path": path}

        elif cmd == "text":
            text = await ctrl.get_page_text()
            result = {"ok": True, "text": text}

        elif cmd == "info":
            info = await ctrl.get_page_info()
            result = {"ok": True, **info}

        elif cmd == "wait":
            seconds = float(arg) if arg else 2
            await asyncio.sleep(seconds)
            info = await ctrl.get_page_info()
            result = {"ok": True, "waited": seconds, **info}

        elif cmd == "back":
            await ctrl.chrome.evaluate("window.history.back()")
            await asyncio.sleep(1)
            info = await ctrl.get_page_info()
            result = {"ok": True, **info}

        elif cmd == "eval":
            value = await ctrl.chrome.evaluate(arg)
            result = {"ok": True, "value": value}

        elif cmd == "stop":
            result = {"ok": True, "message": "server stopping"}
            writer.write(json.dumps(result).encode())
            writer.write_eof()
            await writer.drain()
            writer.close()
            asyncio.get_event_loop().stop()
            return

        else:
            result = {"ok": False, "error": f"unknown command: {cmd}"}

    except Exception as e:
        result = {"ok": False, "error": str(e)}

    writer.write(json.dumps(result, ensure_ascii=False).encode())
    writer.write_eof()
    await writer.drain()
    writer.close()


async def run_server(url: str | None = None):
    """Start the browser session server."""
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)

    ctrl = BrowserController()
    start_url = url or "about:blank"
    await ctrl.start(start_url)

    server = await asyncio.start_unix_server(
        lambda r, w: handle_client(r, w, ctrl),
        path=SOCKET_PATH,
    )

    Path(PID_FILE).write_text(str(os.getpid()))

    info = await ctrl.get_page_info()
    print(json.dumps({"ok": True, "status": "server_started", **info}))
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
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        if os.path.exists(PID_FILE):
            os.unlink(PID_FILE)


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(run_server(url))


if __name__ == "__main__":
    main()
