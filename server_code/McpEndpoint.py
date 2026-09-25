"""Anvil HTTP endpoint for stateless JSON-mode MCP over Streamable HTTP."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import anvil.server

from .McpServer import server
from .RequestContext import RequestContext, reset_request_context, set_request_context
from .Security import AuthError, require_credential
from .mcp_bridge.dispatch import dispatch

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS, GET, DELETE",
    "Access-Control-Allow-Headers": (
        "Content-Type, Accept, Authorization, X-E2B-Api-Key, MCP-Protocol-Version, "
        "Mcp-Session-Id, Mcp-Method, Mcp-Name"
    ),
    "Access-Control-Expose-Headers": "MCP-Protocol-Version",
}


def _error(code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": message}}


def _response(status: int, body: Any = "", headers: dict[str, str] | None = None):
    return anvil.server.HttpResponse(
        status,
        body,
        headers={**_CORS_HEADERS, **(headers or {})},
    )


def handle_request(request):
    """Convert one Anvil request into a buffered MCP response."""
    method = (request.method or "GET").upper()
    if method == "OPTIONS":
        return _response(204)
    if method != "POST":
        return _response(
            405,
            _error(-32000, f"{method} not supported on this stateless MCP endpoint (use POST)."),
            {"Allow": "POST, OPTIONS"},
        )

    headers = {str(k).lower(): str(v) for k, v in (request.headers or {}).items()}
    try:
        api_key = require_credential(headers, request.query_params or {})
    except AuthError as exc:
        return _response(401, _error(-32001, str(exc)), {"WWW-Authenticate": "Bearer"})

    raw = request.body.get_bytes() if request.body else b""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    try:
        timeout = float(os.environ.get("MCP_TOOL_TIMEOUT", "25"))
        if timeout <= 0:
            raise ValueError("timeout must be positive")
    except ValueError:
        timeout = 25.0

    token = set_request_context(RequestContext(api_key=api_key))
    try:
        status, out_headers, payload = asyncio.run(asyncio.wait_for(
            dispatch(
                server,
                method=method,
                path="/mcp",
                headers=headers,
                body=raw,
                host=headers.get("host", "anvil").split(":")[0],
            ),
            timeout=timeout,
        ))
    except asyncio.TimeoutError:
        return _response(504, _error(-32000, f"Request timed out after {timeout:g}s."))
    except Exception:
        return _response(500, _error(-32603, "Internal MCP error."))
    finally:
        reset_request_context(token)

    if not payload:
        return _response(status, "", out_headers)
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "replace")
    return _response(status, payload, out_headers)


@anvil.server.http_endpoint(
    "/mcp", methods=["POST", "GET", "DELETE", "OPTIONS"], enable_cors=True
)
def mcp_endpoint(**_params):
    return handle_request(anvil.server.request)
