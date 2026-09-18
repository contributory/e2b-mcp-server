"""MCP server definition for the E2B sandbox tools.

Do not name this module ``server.py`` — Open Runtimes already ships one.
"""
from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer

from tools import register_tools

server = MCPServer(
    name=os.environ.get("MCP_SERVER_NAME") or "e2b-sandbox-mcp",
    version="1.2.0",
    instructions=(
        "Connects to EXISTING E2B sandboxes only — there is no create and no "
        "kill path. The caller supplies its own E2B API key per request "
        "(Authorization / X-E2B-Api-Key header, or ?e2b_api_key= for clients "
        "that can only configure a URL) and the default sandbox via "
        "?sandbox_id=. Tools must finish within ~25s."
    ),
)

register_tools(server)
