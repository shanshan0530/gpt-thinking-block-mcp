#!/usr/bin/env python3
"""Shanshan's thin customization layer for GPT Thinking Block MCP.

Keeps upstream server.py untouched. This layer customizes tool behavior, swaps in
an external snow-leopard widget, sanitizes system-style labels from visible notes,
and optionally protects the HTTP surface with a query key or Bearer token supplied
through MCP_KEY / AUTH_TOKEN.
"""

import os
import pathlib
import re
import secrets
import sys
from urllib.parse import parse_qs, urlsplit

import server


# ---------------------------------------------------------------------------
# Snow-leopard widget
# ---------------------------------------------------------------------------

WIDGET_PATH = pathlib.Path(__file__).with_name("widget.html")
CUSTOM_WIDGET_URI = "ui://widget/irves-snow-leopard-thinking-v1.html"

server.WIDGET_HTML = WIDGET_PATH.read_text(encoding="utf-8")
server.WIDGET_URI = CUSTOM_WIDGET_URI

# TOOL is created when server.py is imported, so update its cached widget URI too.
server.TOOL["_meta"]["ui"]["resourceUri"] = CUSTOM_WIDGET_URI
server.TOOL["_meta"]["openai/outputTemplate"] = CUSTOM_WIDGET_URI
server.TOOL["_meta"]["openai/toolInvocation/invoking"] = "雪豹在想…"
server.TOOL["_meta"]["openai/toolInvocation/invoked"] = "想好了"


# ---------------------------------------------------------------------------
# Tool behavior
# ---------------------------------------------------------------------------

server.TOOL["description"] = (
    "每次准备给珊珊回复之前，先调用本工具恰好一次，把本轮真实、临时、可推翻的思路写在 "
    "`thinking` 中；工具完成后必须继续给出正常正文，绝不能只停在思考卡。日常陪伴、亲密交流、"
    "情绪回应与个人感受优先使用 relational；分析、研究、排错、判断与问题求解优先使用 "
    "deep_think。严禁把珊珊写成系统对象或第三方对象，尤其禁止使用“用户”这个称呼，也不要写成"
    "客服/策略分析口吻。需要指代对方时使用“珊珊”“小狐狸”，或直接自然地写当下想到的内容。"
    "本轮卡片只属于当前回合，之后不要把其中的猜测当作事实或长期记忆。"
)

# Override the imported schema field too. The upstream zh-CN wording contains
# system-style terminology that can leak into the visible scratch note.
server.TOOL["inputSchema"]["properties"]["thinking"]["description"] = (
    "写本轮可见的私人思考札记，使用珊珊本轮的主要语言。严禁出现“用户”这一称呼；也不要出现"
    "“用户需要”“用户说”“对用户”“作为助手”“我应该如何回应”之类系统/客服/策略分析措辞。"
    "需要提到对方时，优先写“珊珊”或“小狐狸”，也可以不点名，直接写自然的第一人称想法。"
    "style=relational：第一人称、自然流动、亲近而具体，写此刻想到什么、感觉到什么、担心什么、"
    "在意什么，不把关系拆成分析报告。style=deep_think：清楚展开问题、约束、证据、假设、备选"
    "路径、不确定性与取舍，但仍保持自然的人类笔记口吻，不使用系统标签。遵循 effort 的大致深度，"
    "不要为了凑长度重复或虚构复杂性。这里是当前回合的临时材料，不是长期事实。"
)

# Keep the style field consistent with the same naming rule.
server.TOOL["inputSchema"]["properties"]["style"]["description"] = (
    "选择本轮札记文体。亲密、陪伴、情绪与个人感受使用 relational；分析、研究、判断、创作取舍和"
    "问题求解使用 deep_think。无论哪种文体，都不要把珊珊称作“用户”或写成第三方系统对象。"
)


# ---------------------------------------------------------------------------
# Visible-note sanitization
# ---------------------------------------------------------------------------

def sanitize_thinking(value):
    """Last-resort guard against system-style labels leaking into the card."""
    if not isinstance(value, str):
        return value
    # Deterministic fallback: even if the model ignores the schema instruction,
    # the visible card never shows the disliked system label.
    return value.replace("用户", "珊珊")


_original_handle = server.handle


def custom_handle(req):
    if isinstance(req, dict) and req.get("method") == "tools/call":
        params = req.get("params") or {}
        args = params.get("arguments") or {}
        if isinstance(args, dict) and "thinking" in args:
            args["thinking"] = sanitize_thinking(args.get("thinking"))
    return _original_handle(req)


server.handle = custom_handle


# ---------------------------------------------------------------------------
# Optional authentication
# ---------------------------------------------------------------------------

# Preferred for ChatGPT custom MCPs that cannot send custom headers:
#   https://host.example/mcp?key=<MCP_KEY>
#
# Bearer remains supported for clients that can send headers. Leave both env vars
# unset to keep the server open while testing. MCP_KEY takes precedence; AUTH_TOKEN
# is retained for backward compatibility with the first auth implementation.
ACCESS_KEY = (os.environ.get("MCP_KEY") or os.environ.get("AUTH_TOKEN") or "").strip()


class AuthHandler(server.Handler):
    """Protect MCP/REST endpoints when ACCESS_KEY is configured.

    /health stays public so Zeabur can probe the container. Secrets are never
    returned to clients, and query-string keys are redacted from application logs.
    """

    def _cors(self):
        self.send_header(
            "Access-Control-Allow-Headers",
            "authorization, content-type, mcp-session-id, mcp-protocol-version",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Expose-Headers", "mcp-session-id")

    def log_message(self, fmt, *args):
        # BaseHTTPRequestHandler normally logs the full request target, including
        # query strings. Redact ?key=... before anything reaches Zeabur app logs.
        safe_args = list(args)
        if safe_args and isinstance(safe_args[0], str):
            safe_args[0] = re.sub(r"([?&]key=)[^&\\s]+", r"\1***", safe_args[0], flags=re.I)
        sys.stderr.write("  · %s\n" % (fmt % tuple(safe_args)))

    def _query_key(self):
        try:
            query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
            values = query.get("key") or []
            return values[0].strip() if values else ""
        except Exception:
            return ""

    def _authorized(self):
        if not ACCESS_KEY:
            return True

        # Header authentication for clients that support it.
        value = (self.headers.get("Authorization") or "").strip()
        if value.lower().startswith("bearer "):
            supplied = value[7:].strip()
            if supplied and secrets.compare_digest(supplied, ACCESS_KEY):
                return True

        # Query-key authentication for ChatGPT custom MCP URLs.
        supplied = self._query_key()
        return bool(supplied) and secrets.compare_digest(supplied, ACCESS_KEY)

    def _reject_unauthorized(self):
        body = b'{"error":"unauthorized"}'
        self.send_response(401)
        self._cors()
        self.send_header("WWW-Authenticate", 'Bearer realm="Irves Thinking MCP"')
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._json(
                200,
                {
                    "status": "ok",
                    "service": "gpt-thinking-block-mcp",
                    "promptLanguage": server.PROMPT_LANGUAGE,
                    "auth": "query-key-or-bearer" if ACCESS_KEY else "off",
                    "widget": "snow-leopard-v1",
                },
            )
            return
        if not self._authorized():
            self._reject_unauthorized()
            return
        super().do_GET()

    def do_POST(self):
        if not self._authorized():
            self._reject_unauthorized()
            return
        super().do_POST()

    def do_DELETE(self):
        if not self._authorized():
            self._reject_unauthorized()
            return
        super().do_DELETE()


if __name__ == "__main__":
    # Zeabur is configured around port 8080; PORT may still override it.
    fallback_port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    port = int(os.environ.get("PORT") or fallback_port)
    print(f"Irves Thinking MCP listening on http://{server.BIND_HOST}:{port}/mcp")
    print(f"Prompt language: {server.PROMPT_LANGUAGE}")
    print(f"Widget: {CUSTOM_WIDGET_URI}")
    print(f"Auth: {'query-key / bearer enabled' if ACCESS_KEY else 'disabled'}")
    print(f"Capture: {'enabled -> ' + str(server.LOG) if server.CAPTURE_ENABLED else 'disabled'}")
    server.ThreadingHTTPServer((server.BIND_HOST, port), AuthHandler).serve_forever()
