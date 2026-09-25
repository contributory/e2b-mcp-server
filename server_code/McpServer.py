"""MCP server definition for the E2B sandbox tools."""
from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer

from .Tools import register_tools

server = MCPServer(
    name=os.environ.get("MCP_SERVER_NAME") or "e2b-sandbox-mcp",
    version="1.3.0",
    instructions=(
        "Connects to EXISTING E2B sandboxes only — there is no create and no "
        "kill path. The caller supplies its own E2B API key per request "
        "(Authorization / X-E2B-Api-Key header, or ?e2b_api_key= for clients "
        "that can only configure a URL). A tool-level sandbox_id wins; otherwise "
        "the last successfully used sandbox is loaded from Anvil Data Tables, "
        "falling back to the first existing E2B sandbox. Tools must finish "
        "within ~25s."
    ),
)

register_tools(server)
