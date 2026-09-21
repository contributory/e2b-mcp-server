"""Appwrite Function entrypoint — thin adapter around the official MCP SDK."""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from app import server
from appwrite_mcp import handle_http
from appwrite_mcp.transport import CORS_HEADERS
from reqctx import RequestContext, reset_request_context, set_request_context
from security import AuthError, require_credential


def _query_params(req) -> dict:
    raw = getattr(req, "query_string", None)
    if raw:
        return parse_qs(raw if isinstance(raw, str) else raw.decode("latin-1"))
    return dict(getattr(req, "query", None) or {})


async def main(context):
    req = context.req
    method = (getattr(req, "method", None) or "GET").upper()
    headers = {str(key).lower(): str(value) for key, value in (req.headers or {}).items()}

    if method != "POST":
        return await handle_http(server, context)

    query = _query_params(req)
    try:
        api_key = require_credential(headers, query)
    except AuthError as exc:
        body = {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32001, "message": str(exc)},
        }
        return context.res.json(
            body, 401, {**CORS_HEADERS, "WWW-Authenticate": "Bearer"}
        )

    token = set_request_context(RequestContext(
        api_key=api_key,
        appwrite_key=headers.get("x-appwrite-key", ""),
    ))
    try:
        return await handle_http(server, context)
    finally:
        reset_request_context(token)
