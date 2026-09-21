"""Per-request context passed from the transport layer down to tool handlers."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass
class RequestContext:
    """Carries credentials needed by one MCP request."""

    api_key: str
    appwrite_key: str = ""


_request_context: ContextVar[Optional[RequestContext]] = ContextVar(
    "e2b_request_context", default=None
)


def set_request_context(context: RequestContext):
    """Make a request's credentials available to the tool being called."""
    return _request_context.set(context)


def reset_request_context(token) -> None:
    _request_context.reset(token)


def get_request_context() -> RequestContext:
    """Return the active request context, or fail closed outside HTTP handling."""
    context = _request_context.get()
    if context is None:
        raise RuntimeError("missing request context")
    return context
