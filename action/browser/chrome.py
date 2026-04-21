"""Chrome browser connection via CDP (Chrome DevTools Protocol).

Connects to a running Chrome instance with --remote-debugging-port=9222,
reusing existing login sessions and cookies.
"""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import httpx
import websockets


CDP_URL = "http://localhost:9222"


class ChromeBrowser:
    """Low-level CDP connection to a running Chrome instance."""

    def __init__(self, cdp_url: str = CDP_URL):
        self.cdp_url = cdp_url
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._msg_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._event_handlers: dict[str, list] = {}
        self._recv_task: asyncio.Task | None = None
        self.target_id: str | None = None

    async def connect(self, target_url: str | None = None) -> None:
        """Connect to a Chrome tab. If target_url is given, find or create that tab."""
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            try:
                resp = await client.get(f"{self.cdp_url}/json/version")
                info = resp.json()
                print(f"Connected to Chrome {info.get('Browser', 'unknown')}")
            except httpx.ConnectError:
                raise ConnectionError(
                    "Chrome not running with debug port. Run:\n"
                    "  bash scripts/launch_chrome.sh"
                )

            resp = await client.get(f"{self.cdp_url}/json")
            tabs = resp.json()

            ws_url = None

            if target_url:
                for tab in tabs:
                    if target_url in tab.get("url", ""):
                        ws_url = tab["webSocketDebuggerUrl"]
                        self.target_id = tab["id"]
                        print(f"Found existing tab: {tab['url'][:80]}")
                        break

            if not ws_url:
                resp = await client.get(f"{self.cdp_url}/json/version")
                browser_ws_url = resp.json()["webSocketDebuggerUrl"]

                browser_ws = await websockets.connect(
                    browser_ws_url, max_size=50 * 1024 * 1024
                )
                new_url = target_url or "about:blank"
                create_msg = json.dumps(
                    {
                        "id": 1,
                        "method": "Target.createTarget",
                        "params": {"url": new_url},
                    }
                )
                await browser_ws.send(create_msg)
                create_resp = json.loads(await browser_ws.recv())
                self.target_id = create_resp["result"]["targetId"]
                await browser_ws.close()

                port = self.cdp_url.split(":")[-1].rstrip("/")
                ws_url = f"ws://localhost:{port}/devtools/page/{self.target_id}"
                print(f"Created new tab: {new_url[:80]}")

        self._ws = await websockets.connect(ws_url, max_size=50 * 1024 * 1024)
        self._recv_task = asyncio.create_task(self._recv_loop())

        await self.send("Page.enable")
        await self.send("DOM.enable")
        await self.send("Runtime.enable")

        await self.send(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                """
            },
        )
        await self.evaluate(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

    async def send(self, method: str, params: dict | None = None) -> dict:
        """Send a CDP command and wait for the response."""
        self._msg_id += 1
        msg_id = self._msg_id
        msg = {"id": msg_id, "method": method, "params": params or {}}

        future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future

        await self._ws.send(json.dumps(msg))
        result = await asyncio.wait_for(future, timeout=30)
        return result

    async def _recv_loop(self) -> None:
        """Background task to receive CDP messages."""
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if "id" in msg:
                    future = self._pending.pop(msg["id"], None)
                    if future and not future.done():
                        if "error" in msg:
                            future.set_exception(
                                RuntimeError(f"CDP error: {msg['error']}")
                            )
                        else:
                            future.set_result(msg.get("result", {}))
                elif "method" in msg:
                    for handler in self._event_handlers.get(msg["method"], []):
                        asyncio.create_task(handler(msg.get("params", {})))
        except websockets.ConnectionClosed:
            pass

    def on(self, event: str, handler) -> None:
        """Register an event handler for CDP events."""
        self._event_handlers.setdefault(event, []).append(handler)

    async def navigate(self, url: str, wait_until: str = "load") -> None:
        """Navigate to a URL and wait for the page to load."""
        event = (
            "Page.loadEventFired"
            if wait_until == "load"
            else "Page.domContentEventFired"
        )
        loaded = asyncio.Event()

        async def on_load(_params):
            loaded.set()

        self.on(event, on_load)
        await self.send("Page.navigate", {"url": url})
        await asyncio.wait_for(loaded.wait(), timeout=30)
        await asyncio.sleep(0.5)

    async def evaluate(self, expression: str) -> Any:
        """Execute JavaScript in the page and return the result."""
        result = await self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        remote_obj = result.get("result", {})
        if remote_obj.get("type") == "undefined":
            return None
        if "value" in remote_obj:
            return remote_obj["value"]
        return remote_obj

    async def screenshot(self, quality: int = 60) -> bytes:
        """Take a screenshot of the current viewport, returns JPEG bytes."""
        result = await self.send(
            "Page.captureScreenshot",
            {"format": "jpeg", "quality": quality},
        )
        return base64.b64decode(result["data"])

    async def click(self, x: float, y: float) -> None:
        """Click at coordinates (x, y)."""
        for event_type in ("mousePressed", "mouseReleased"):
            await self.send(
                "Input.dispatchMouseEvent",
                {
                    "type": event_type,
                    "x": x,
                    "y": y,
                    "button": "left",
                    "clickCount": 1,
                },
            )

    async def type_text(self, text: str, delay: float = 0.03) -> None:
        """Type text using a single Input.insertText call.

        Sending the full string at once avoids Twitter/DraftJS mid-type URL
        detection which scrambles characters when typed one-by-one (e.g.
        'https://' gets converted to a link entity mid-keystroke, shifting
        the cursor so subsequent chars land in the wrong position).
        """
        await self.send("Input.insertText", {"text": text})

    async def fill_text(self, text: str) -> dict:
        """Fill text into focused element using execCommand (React-safe).

        Pattern from Playwright: focus → selectAll → execCommand('insertText').
        Works reliably with React controlled inputs (e.g., Twitter/X compose box).
        Returns the actual value of the element after filling for verification.
        """
        result = await self.evaluate(f"""
            (function() {{
                const el = document.activeElement;
                if (!el || el === document.body) {{
                    return {{ ok: false, error: "no focused element" }};
                }}
                const tag = el.tagName.toLowerCase();
                const role = el.getAttribute('role') || '';
                const isEditable = el.isContentEditable
                    || tag === 'input' || tag === 'textarea'
                    || role === 'textbox';
                if (!isEditable) {{
                    return {{ ok: false, error: "focused element is not editable: " + tag }};
                }}
                // Select all existing content
                if (el.isContentEditable) {{
                    const sel = window.getSelection();
                    const range = document.createRange();
                    range.selectNodeContents(el);
                    sel.removeAllRanges();
                    sel.addRange(range);
                }} else {{
                    el.select();
                }}
                // Insert via execCommand — triggers React's synthetic event system
                document.execCommand('insertText', false, {json.dumps(text)});
                // Read back actual value
                const actual = el.isContentEditable
                    ? el.textContent.trim()
                    : el.value;
                return {{
                    ok: true,
                    tag: tag,
                    role: role,
                    actual: actual,
                    length: actual.length,
                    match: actual.includes({json.dumps(text)})
                }};
            }})()
        """)
        return (
            result
            if isinstance(result, dict)
            else {"ok": False, "error": "unexpected result"}
        )

    async def get_accessibility_tree(self) -> list[dict]:
        """Get the accessibility tree from CDP."""
        await self.send("Accessibility.enable")
        result = await self.send("Accessibility.getFullAXTree")
        return result.get("nodes", [])

    async def get_focused_element_info(self) -> dict:
        """Get info about the currently focused element."""
        return await self.evaluate("""
            (function() {
                const el = document.activeElement;
                if (!el || el === document.body) return { focused: null };
                const rect = el.getBoundingClientRect();
                return {
                    focused: {
                        tag: el.tagName.toLowerCase(),
                        role: el.getAttribute('role') || null,
                        type: el.type || null,
                        value: el.isContentEditable ? el.textContent.trim().slice(0, 200) : (el.value || '').slice(0, 200),
                        placeholder: el.getAttribute('placeholder') || null,
                        ariaLabel: el.getAttribute('aria-label') || null,
                        editable: el.isContentEditable || ['input','textarea'].includes(el.tagName.toLowerCase()),
                        rect: { x: Math.round(rect.x + rect.width/2), y: Math.round(rect.y + rect.height/2) }
                    }
                };
            })()
        """)

    async def press_key(self, key: str) -> None:
        """Press a special key (Enter, Tab, Escape, etc.)."""
        key_map = {
            "Enter": {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13},
            "Tab": {"key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9},
            "Escape": {"key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27},
            "Backspace": {
                "key": "Backspace",
                "code": "Backspace",
                "windowsVirtualKeyCode": 8,
            },
        }
        info = key_map.get(key, {"key": key, "code": key})
        await self.send("Input.dispatchKeyEvent", {"type": "keyDown", **info})
        await self.send("Input.dispatchKeyEvent", {"type": "keyUp", **info})

    async def scroll(
        self, x: float = 0, y: float = 0, delta_x: float = 0, delta_y: float = -300
    ) -> None:
        """Scroll the page. Negative delta_y = scroll down."""
        await self.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseWheel",
                "x": x,
                "y": y,
                "deltaX": delta_x,
                "deltaY": delta_y,
            },
        )

    async def close(self) -> None:
        """Disconnect from Chrome (does not close the browser)."""
        if self._recv_task:
            self._recv_task.cancel()
        if self._ws:
            await self._ws.close()
