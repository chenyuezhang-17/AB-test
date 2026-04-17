"""Create Lessie share links via Browser CDP — no JWT needed.

Uses the @alliiexia Chrome session (port 9222) to make API calls
with the browser's authenticated cookies. Same API flow as the JWT
method, but auth comes from browser cookies that auto-refresh.

Three-phase approach to avoid the 30s CDP eval timeout:
1. Start SSE search stream in background (non-blocking JS)
2. Poll window.__ls state until conversation_id + done
3. POST to shares/v1 to create public share link
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

SOCKET_PATH = "/tmp/social-browser.sock"
PID_FILE = "/tmp/social-browser.pid"


# ─── socket communication (same protocol as action/browser_post.py) ───────

async def _send(cmd: str, arg: str = "", timeout: int = 30) -> dict:
    reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)
    writer.write(json.dumps({"cmd": cmd, "arg": arg}).encode())
    writer.write_eof()
    await writer.drain()
    chunks = []
    while True:
        chunk = await asyncio.wait_for(reader.read(65536), timeout=timeout)
        if not chunk:
            break
        chunks.append(chunk)
    writer.close()
    return json.loads(b"".join(chunks).decode())


def _bw(cmd: str, arg: str = "", timeout: int = 30) -> dict:
    return asyncio.run(_send(cmd, arg, timeout))


def _session_alive() -> bool:
    """Check if the browser session is running and reachable."""
    if not os.path.exists(SOCKET_PATH):
        return False
    if not os.path.exists(PID_FILE):
        return False
    try:
        pid = int(Path(PID_FILE).read_text().strip())
        os.kill(pid, 0)  # check process exists
    except Exception:
        return False
    try:
        r = _bw("ping", "", timeout=5)
        return r.get("ok", False)
    except Exception:
        return False


# ─── CDP share link creation ─────────────────────────────────────────────

def create_share_link_cdp(search_prompt: str) -> str | None:
    """Create a Lessie share link using browser cookies via CDP.

    Navigate to app.lessie.ai (for cookie scope), then use fetch()
    to call the same API endpoints. Browser sends cookies automatically.

    Returns: "https://app.lessie.ai/share/xxxxx" or None
    """
    if not _session_alive():
        print("[share_cdp] Browser session not running, skipping CDP method")
        return None

    try:
        return _do_create(search_prompt)
    except Exception as e:
        print(f"[share_cdp] Error: {e}")
        return None


def _do_create(search_prompt: str) -> str | None:
    """Internal: three-phase share link creation."""

    # Navigate to Lessie domain so fetch() sends the right cookies
    goto_res = _bw("goto", "https://app.lessie.ai", timeout=20)
    if not goto_res.get("ok"):
        print(f"[share_cdp] Failed to navigate to Lessie: {goto_res}")
        return None
    time.sleep(2)

    # Check if logged in (redirected to login/auth page = not logged in)
    url_check = _bw("eval", "window.location.href", timeout=10)
    current_url = str(url_check.get("value", ""))
    if "login" in current_url or "auth" in current_url or "lessie.ai" not in current_url:
        print(f"[share_cdp] Not on Lessie or not logged in: {current_url}")
        return None

    # ── Phase 1: Start search stream in background ──
    # The fetch runs in the page context (non-blocking).
    # Results accumulate in window.__ls which we poll in Phase 2.
    prompt_json = json.dumps(search_prompt)

    phase1 = _bw("eval", f"""(function(){{
        window.__ls = {{ status: 'fetching', conv_id: null, has_results: false, error: null }};
        var prompt = {prompt_json};
        var now = new Date().toISOString();
        var body = {{
            messages: [{{
                role: "user", content: prompt,
                id: "msg_" + Date.now(),
                parts: [{{type: "text", text: prompt}}],
                peosonList: [], createdAt: now
            }}],
            payload: {{task_id: "", person_info_list: []}},
            id: "conv_" + Date.now()
        }};
        fetch("/sourcing-api/chat/v1/stream", {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify(body)
        }}).then(function(resp) {{
            if (!resp.ok) {{
                window.__ls.error = "HTTP " + resp.status;
                window.__ls.status = "error";
                return;
            }}
            var reader = resp.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';
            function read() {{
                reader.read().then(function(result) {{
                    if (result.done) {{ window.__ls.status = 'done'; return; }}
                    buffer += decoder.decode(result.value, {{stream: true}});
                    var lines = buffer.split('\\n');
                    buffer = lines.pop();
                    for (var i = 0; i < lines.length; i++) {{
                        var line = lines[i];
                        if (line.indexOf('data: ') !== 0) continue;
                        try {{
                            var data = JSON.parse(line.slice(6));
                            if (data.conversation_id && !window.__ls.conv_id) {{
                                window.__ls.conv_id = data.conversation_id;
                            }}
                            if (data.person_info_list || data.persons || data.results || data.total) {{
                                window.__ls.has_results = true;
                            }}
                            if (data.status === 'done' || data.status === 'finished' ||
                                data.status === 'complete' || data.is_finished) {{
                                window.__ls.status = 'done';
                                return;
                            }}
                        }} catch(e) {{}}
                    }}
                    read();
                }}).catch(function(e) {{
                    window.__ls.error = e.message;
                    window.__ls.status = 'error';
                }});
            }}
            read();
        }}).catch(function(e) {{
            window.__ls.error = e.message;
            window.__ls.status = 'error';
        }});
        return 'started';
    }})()""", timeout=15)

    if phase1.get("value") != "started":
        print(f"[share_cdp] Phase 1 failed: {phase1}")
        return None

    print("[share_cdp] Search stream started, polling...")

    # ── Phase 2: Poll until stream completes (max ~120s) ──
    conv_id = None
    for i in range(40):  # 40 * 3s = 120s
        time.sleep(3)
        state = _bw("eval", "JSON.stringify(window.__ls || {})", timeout=10)
        try:
            s = json.loads(state.get("value", "{}"))
        except (json.JSONDecodeError, TypeError):
            continue

        status = s.get("status", "")
        conv_id = s.get("conv_id")

        if status == "error":
            print(f"[share_cdp] Stream error: {s.get('error')}")
            return None

        if status == "done" and conv_id:
            has = "with" if s.get("has_results") else "without"
            print(f"[share_cdp] Search done ({has} results), conv={conv_id[:16]}...")
            break

        # Early exit: got conv_id but stream seems stalled after 60s
        if conv_id and i >= 20:
            print(f"[share_cdp] Stream stalled but have conv_id, proceeding")
            break

        if i > 0 and i % 10 == 0:
            print(f"[share_cdp] Still waiting... ({i * 3}s)")
    else:
        if conv_id:
            print(f"[share_cdp] Timeout but have conv_id, trying share anyway")
        else:
            print("[share_cdp] Timeout: no conversation_id after 120s")
            return None

    # Brief pause for server to finalize results
    time.sleep(2)

    # ── Phase 3: Create public share link ──
    conv_id_safe = json.dumps(conv_id)  # proper JS string escaping
    share_js = f"""(async function(){{
        var resp = await fetch("/sourcing-api/shares/v1", {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify({{
                conversation_id: {conv_id_safe},
                access_permission: 2
            }})
        }});
        return await resp.json();
    }})()"""

    share_result = _bw("eval", share_js, timeout=20)
    data = share_result.get("value")

    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            pass

    if isinstance(data, dict):
        if data.get("code") == 200:
            share_id = (data.get("data") or {}).get("share_id")
            if share_id:
                url = f"https://app.lessie.ai/share/{share_id}"
                print(f"[share_cdp] share link created: {url}")
                return url

        print(f"[share_cdp] Share API unexpected response: {data}")
    else:
        print(f"[share_cdp] Could not parse share response: {share_result}")

    return None
