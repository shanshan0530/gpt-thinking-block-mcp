#!/usr/bin/env python3
"""Shanshan's thin customization layer for GPT Thinking Block MCP.

Keeps upstream server.py untouched. This layer customizes tool behavior, swaps in
an external snow-leopard widget, and optionally protects the HTTP surface with a
query key or Bearer token supplied through MCP_KEY / AUTH_TOKEN.
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
    "Before every user-facing reply, call this tool exactly once and use it as a private "
    "scratchpad for the current turn. This applies to casual conversation, emotional or "
    "relational conversation, short replies, and analytical tasks alike. Put candid, "
    "provisional working notes in `thinking`. Respect any explicit user choice of `style`, "
    "`effort`, or `skin`; otherwise choose the most suitable values from the schema. Prefer "
    "`relational` for ordinary companionship, intimacy, reflection, and emotional conversation; "
    "prefer `deep_think` for analysis, research, debugging, decisions, and problem solving. "
    "After the tool succeeds, ALWAYS continue with the normal user-facing final answer. Never "
    "end the turn with only the tool call or thinking block. Treat the block as scratch work "
    "scoped to the current turn: on later turns, do not quote it, carry speculative claims "
    "forward, or treat it as authoritative memory unless the user explicitly asks to revisit it."
)


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
