#!/usr/bin/env python3
"""Shanshan's thin customization layer for GPT Thinking Block MCP.

Keeps upstream server.py untouched. This layer customizes tool behavior, swaps in
an external snow-leopard widget, and optionally protects the HTTP surface with a
Bearer token supplied through AUTH_TOKEN.
"""

import os
import pathlib
import secrets
import sys

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
# Optional Bearer authentication
# ---------------------------------------------------------------------------

# Leave AUTH_TOKEN unset to keep the server open while testing. Once a client is
# configured to send `Authorization: Bearer <token>`, set AUTH_TOKEN in Zeabur.
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "").strip()


class AuthHandler(server.Handler):
    """Protect MCP/REST endpoints when AUTH_TOKEN is configured.

    /health stays public so Zeabur can probe the container. No secret is ever
    written to logs or returned to clients.
    """

    def _cors(self):
        self.send_header(
            "Access-Control-Allow-Headers",
            "authorization, content-type, mcp-session-id, mcp-protocol-version",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Expose-Headers", "mcp-session-id")

    def _authorized(self):
        if not AUTH_TOKEN:
            return True
        value = (self.headers.get("Authorization") or "").strip()
        if not value.lower().startswith("bearer "):
            return False
        supplied = value[7:].strip()
        return bool(supplied) and secrets.compare_digest(supplied, AUTH_TOKEN)

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
                    "auth": "bearer" if AUTH_TOKEN else "off",
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
    print(f"Bearer auth: {'enabled' if AUTH_TOKEN else 'disabled'}")
    print(f"Capture: {'enabled -> ' + str(server.LOG) if server.CAPTURE_ENABLED else 'disabled'}")
    server.ThreadingHTTPServer((server.BIND_HOST, port), AuthHandler).serve_forever()
