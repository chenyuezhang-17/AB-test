# Task: Share Link 生成改用 Browser CDP

## 背景

当前 `bridge/search.py` 里的 `_create_share_link()` 通过 Lessie Web API 生成 share link，需要 JWT token（从浏览器 cookie 拿）。

### 当前方案（JWT）的问题

1. **约 7 天过期** — 服务端控制，过期后所有 share link 生成静默失败，fallback 到 lessie.ai 首页
2. **手动获取** — 每次过期要人去浏览器 F12 → Application → Cookies → 复制 Authorization
3. **不可共享** — JWT 绑定账号 session，团队成员要共享同一个 token
4. **非官方 API** — 我们逆向工程了网页端内部接口，随时可能变

### 目标

用 Shane 的 Browser CDP 方案（`action/browser/`）替代 JWT 方案，直接操作 Lessie 网页生成 share link。

## 实现方案

### 核心流程

跟 `action/browser_post.py` 发推特一样的逻辑，只是操作 Lessie 网页：

```
1. Chrome CDP 连接（Twitter 已登录 + Lessie 已登录）
2. 打开 app.lessie.ai → New Chat
3. 输入搜索 prompt（从 reasoner 传过来的 checkpoint）
4. 等待搜索完成
5. 点击分享按钮 → 选 "Public access"
6. 抓取生成的 share link URL（格式：app.lessie.ai/share/xxxxx）
7. 返回这个 URL
```

### 需要读的代码

- `bridge/search.py` — 看 `_create_share_link()` 函数，了解当前的 API 调用流程
- `action/browser/controller.py` — 你写的 CDP controller，复用同样的模式
- `action/browser_post.py` — 发推特的实现，share link 生成可以参考同样的结构

### 当前 API 流程（供参考）

```python
# Step 1: 创建搜索会话
POST /sourcing-api/chat/v1/stream
Body: {"messages": [{"role": "user", "content": "搜索 prompt"}], ...}
Response: SSE stream, 第一条 data 里有 conversation_id

# Step 2: 创建公开分享
POST /sourcing-api/shares/v1
Body: {"conversation_id": "uuid", "access_permission": 2}
Response: {"data": {"share_id": "xxxxx"}}

# Step 3: 拼链接
https://app.lessie.ai/share/{share_id}
```

### 接口

写一个函数替换 `bridge/search.py` 里的 `_create_share_link()`：

```python
def create_share_link_browser(search_prompt: str) -> str | None:
    """用 Browser CDP 在 Lessie 网页上创建搜索 + 生成 public share link。
    
    Returns: "https://app.lessie.ai/share/xxxxx" 或 None
    """
```

### 注意事项

- Chrome 需要同时登录 Twitter 和 Lessie（同一个浏览器实例）
- Lessie 搜索需要时间（10-60 秒），要等搜索完成后再点分享
- share link 格式固定是 `app.lessie.ai/share/` + 一串 ID
- 如果 CDP 连不上或操作失败，返回 None，bridge 会 fallback 到 lessie.ai 首页
