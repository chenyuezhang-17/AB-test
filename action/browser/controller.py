"""High-level browser controller with Vimium-style element labeling.

Provides the interface between AI and the browser:
- Label all interactive elements on the page
- Click elements by label (e.g., "ab")
- Type into focused elements
- Take annotated screenshots
- Scroll, navigate, etc.
"""

import asyncio
from pathlib import Path
from typing import Any

from browser.chrome import ChromeBrowser


_LABELS_JS = (Path(__file__).parent / "labels.js").read_text()


class BrowserController:
    """AI-friendly browser controller with element labeling."""

    def __init__(self):
        self.chrome = ChromeBrowser()
        self._labels: list[dict[str, Any]] = []

    async def start(self, url: str | None = None) -> None:
        """Connect to Chrome and optionally navigate to a URL."""
        await self.chrome.connect(target_url=url)
        if url:
            await self.chrome.navigate(url)

    async def label_elements(self) -> list[dict[str, Any]]:
        """Inject Vimium-style labels on all interactive elements."""
        self._labels = await self.chrome.evaluate(_LABELS_JS)
        if self._labels is None:
            self._labels = []
        return self._labels

    async def clear_labels(self) -> None:
        """Remove label overlays from the page."""
        await self.chrome.evaluate("""
            document.querySelectorAll('.ki-label-overlay').forEach(el => el.remove());
        """)
        self._labels = []

    def find_label(self, label: str) -> dict[str, Any] | None:
        """Look up an element by its two-letter label."""
        for el in self._labels:
            if el["label"] == label.lower():
                return el
        return None

    async def click_label(self, label: str) -> dict[str, Any] | None:
        """Click an element by its label (e.g., 'ab').

        After clicking, if the target is an editable element (contentEditable,
        input, textarea, or role=textbox), explicitly focus it via JS.
        This fixes React/Twitter-style contentEditable divs that don't
        reliably receive focus from coordinate clicks alone.
        """
        el = self.find_label(label)
        if not el:
            print(f"Label '{label}' not found. Run label_elements() first.")
            return None

        await self.clear_labels()
        x, y = el["rect"]["x"], el["rect"]["y"]
        await self.chrome.click(x, y)
        await asyncio.sleep(0.3)

        # Auto-focus editable elements that may not respond to coordinate click.
        # Twitter/React contentEditable divs often don't get focus from CDP
        # coordinate clicks — elementFromPoint may hit an inner span/div.
        # Strategy: try elementFromPoint first, walk up to editable parent,
        # then fall back to aria/role-based selector matching.
        role = el.get("role", "")
        tag = el.get("tag", "")
        text = el.get("text", "")
        is_editable = role in ("textbox", "combobox", "searchbox") or tag in (
            "input",
            "textarea",
        )
        if is_editable:
            import json as _json

            await self.chrome.evaluate(f"""
                (function() {{
                    // Strategy 1: elementFromPoint → walk up to the best focusable element.
                    // Priority: role=textbox/combobox > input/textarea > contentEditable.
                    // Don't stop at the first contentEditable child — Draft.js nests
                    // multiple CE divs, and only the role=textbox parent gives reliable focus.
                    let target = document.elementFromPoint({x}, {y});
                    if (target) {{
                        let node = target;
                        let firstEditable = null;
                        while (node && node !== document.body) {{
                            if (['INPUT','TEXTAREA'].includes(node.tagName)) {{
                                node.focus();
                                return;
                            }}
                            const r = node.getAttribute('role');
                            if (r === 'textbox' || r === 'combobox' || r === 'searchbox') {{
                                node.focus();
                                return;
                            }}
                            if (!firstEditable && node.isContentEditable) {{
                                firstEditable = node;
                            }}
                            node = node.parentElement;
                        }}
                        // Fallback: focus the first contentEditable we found
                        if (firstEditable) {{
                            firstEditable.focus();
                            return;
                        }}
                    }}
                    // Strategy 2: query by role + aria-label matching
                    const role = {_json.dumps(role)};
                    const text = {_json.dumps(text)};
                    if (role) {{
                        const candidates = document.querySelectorAll('[role=\"' + role + '\"]');
                        for (const c of candidates) {{
                            const label = c.getAttribute('aria-label') || c.getAttribute('placeholder') || c.textContent.trim().slice(0, 40);
                            if (label && text && label.includes(text.slice(0, 20))) {{
                                c.focus();
                                return;
                            }}
                        }}
                        // If only one candidate with this role, focus it
                        if (candidates.length === 1) {{
                            candidates[0].focus();
                            return;
                        }}
                    }}
                    // Strategy 3: focus whatever elementFromPoint found
                    if (target) target.focus();
                }})()
            """)
            await asyncio.sleep(0.1)

        desc = el.get("text", "") or el.get("href", "") or el["tag"]
        print(f"Clicked [{label}] -> {desc[:60]}")
        return el

    async def type_text(self, text: str) -> None:
        """Type text into the currently focused element (char by char)."""
        await self.chrome.type_text(text)

    async def fill_text(self, text: str) -> dict:
        """Fill text into focused element using React-safe method.

        Uses execCommand('insertText') which triggers React synthetic events.
        Returns verification info: actual content, length, match status.
        """
        return await self.chrome.fill_text(text)

    async def get_focused_info(self) -> dict:
        """Get info about currently focused element."""
        return await self.chrome.get_focused_element_info()

    async def press_key(self, key: str) -> None:
        """Press Enter, Tab, Escape, etc."""
        await self.chrome.press_key(key)

    async def navigate(self, url: str) -> None:
        """Navigate to a URL."""
        await self.chrome.navigate(url)
        self._labels = []

    async def scroll_down(self, amount: int = 500) -> None:
        """Scroll down the page."""
        await self.chrome.scroll(x=400, y=400, delta_y=amount)
        await asyncio.sleep(0.3)
        self._labels = []

    async def scroll_up(self, amount: int = 500) -> None:
        """Scroll up the page."""
        await self.chrome.scroll(x=400, y=400, delta_y=-amount)
        await asyncio.sleep(0.3)
        self._labels = []

    async def screenshot(self, save_path: str | None = None) -> bytes:
        """Take a screenshot. Optionally save to file."""
        data = await self.chrome.screenshot()
        if save_path:
            Path(save_path).write_bytes(data)
            print(f"Screenshot saved to {save_path}")
        return data

    async def get_page_info(self) -> dict:
        """Get current page title and URL."""
        title = await self.chrome.evaluate("document.title")
        url = await self.chrome.evaluate("window.location.href")
        return {"title": title, "url": url}

    async def get_page_text(self) -> str:
        """Extract visible text content from the page."""
        text = await self.chrome.evaluate("""
            (function() {
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT, null
                );
                const parts = [];
                while (walker.nextNode()) {
                    const t = walker.currentNode.textContent.trim();
                    if (t) parts.push(t);
                }
                return parts.join('\\n').slice(0, 5000);
            })()
        """)
        return text or ""

    async def snapshot(self) -> str:
        """Get a compact accessibility tree snapshot of the current page.

        Returns a text representation with numbered interactive elements,
        similar to Playwright MCP's snapshot mode. ~10-100x cheaper than
        screenshots for AI context.

        Format:
          [1] button "Tweet"
          [2] textbox "What's happening?" value="draft text"
          [3] link "Home" -> /home
          ---
          Static: heading "For You" | text "Trending topics" | ...
        """
        nodes = await self.chrome.get_accessibility_tree()

        # Build a lookup of nodeId -> node
        node_map = {}
        for node in nodes:
            nid = node.get("nodeId")
            if nid:
                node_map[nid] = node

        interactive_roles = {
            "button",
            "link",
            "textbox",
            "searchbox",
            "combobox",
            "checkbox",
            "radio",
            "switch",
            "tab",
            "menuitem",
            "menuitemcheckbox",
            "menuitemradio",
            "option",
            "slider",
            "spinbutton",
            "scrollbar",
            "treeitem",
        }

        interactive = []
        context_parts = []

        for node in nodes:
            role = node.get("role", {}).get("value", "")
            ignored = node.get("ignored", False)
            if ignored:
                continue

            # Extract name
            name = ""
            value = ""
            for prop in node.get("properties", []):
                pass
            name_obj = node.get("name", {})
            name = name_obj.get("value", "") if isinstance(name_obj, dict) else ""
            value_obj = node.get("value", {})
            value = value_obj.get("value", "") if isinstance(value_obj, dict) else ""

            if not name and not value:
                continue

            if role in interactive_roles:
                entry = {"role": role, "name": name}
                if value:
                    entry["value"] = str(value)[:100]
                interactive.append(entry)
            elif role in ("heading", "StaticText") and name:
                context_parts.append(f'{role} "{name[:60]}"')

        # Format output
        lines = []
        for i, el in enumerate(interactive, 1):
            parts = [f"[{i}]", el["role"], f'"{el["name"][:60]}"']
            if el.get("value"):
                parts.append(f'value="{el["value"][:60]}"')
            lines.append(" ".join(parts))

        if context_parts:
            lines.append("---")
            # Show first 20 context items to keep it compact
            lines.append("Context: " + " | ".join(context_parts[:20]))

        return "\n".join(lines) if lines else "(empty page)"

    async def close(self) -> None:
        """Disconnect from Chrome."""
        await self.chrome.close()

    def format_labels(self, labels: list[dict] | None = None) -> str:
        """Format labels into a readable string for AI consumption."""
        labels = labels or self._labels
        if not labels:
            return "(no interactive elements found)"

        lines = []
        for el in labels:
            parts = [f"[{el['label']}]"]
            parts.append(el["tag"])
            if el.get("role"):
                parts.append(f"role={el['role']}")
            if el.get("type"):
                parts.append(f"type={el['type']}")
            if el.get("text"):
                parts.append(f'"{el["text"][:50]}"')
            if el.get("href"):
                parts.append(f"-> {el['href'][:60]}")
            lines.append(" ".join(parts))
        return "\n".join(lines)
