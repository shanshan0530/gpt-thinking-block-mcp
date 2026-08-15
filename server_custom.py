#!/usr/bin/env python3
"""Shanshan's thin customization layer for GPT Thinking Block MCP.

Keeps upstream server.py untouched and only strengthens tool-call behavior.
"""

import sys
import server

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

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print(f"GPT Thinking Block MCP (custom) listening on http://{server.BIND_HOST}:{port}/mcp")
    print(f"Prompt language: {server.PROMPT_LANGUAGE}")
    print(f"Capture: {'enabled -> ' + str(server.LOG) if server.CAPTURE_ENABLED else 'disabled'}")
    server.ThreadingHTTPServer((server.BIND_HOST, port), server.Handler).serve_forever()
