"""Per-request context passed from the transport layer down to tool handlers."""
from __future__ import annotations

from dataclasses import dataclass
from contextvars import ContextVar
from typing import Optional


@dataclass
class RequestContext:
    """Carries the caller's credential and the default sandbox for one request.

    * ``api_key`` — E2B API key taken from a header or endpoint query parameter.
    * ``default_sandbox_id`` — from the ``?sandbox_id=`` URL query param; used by
      tools that need a sandbox when the tool call omits ``sandbox_id``.
    """

    api_key: str
    default_sandbox_id: Optional[str] = None


_request_context: ContextVar[Optional[RequestContext]] = ContextVar(
    "e2b_request_context", default=None
)


def set_request_context(context: RequestContext):
    """Make a request's E2B details available to the tool being called."""
    return _request_context.set(context)


def reset_request_context(token) -> None:
    _request_context.reset(token)


def get_request_context() -> RequestContext:
    """Return the active request context, or fail closed outside HTTP handling."""
    context = _request_context.get()
    if context is None:
        raise RuntimeError("missing request context")
    return context
