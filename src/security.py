"""Per-request E2B credential handling.

A caller may supply its E2B key in ``Authorization`` / ``X-E2B-Api-Key`` or,
for MCP clients which only configure an endpoint URL, as ``e2b_api_key`` (or
the compatibility alias ``api_key``) in its query string. Header credentials
win over a URL credential. Never log either form of credential.

Key-shape validation: proxies, gateways, and some runtimes inject an
``Authorization`` header (or an empty placeholder) even when the client sent
none. A header value is therefore only trusted when it actually looks like an
E2B key (``e2b_`` prefix); anything else is treated as *absent* so the URL
query fallback can supply the real key. Empty/garbage values never reach the
E2B API.
"""
from __future__ import annotations

from typing import Mapping, Optional

_E2B_PREFIX = "e2b_"


class AuthError(Exception):
    """Raised when no usable credential is presented."""


def _looks_like_e2b_key(value: str) -> bool:
    """True only for non-empty values shaped like an E2B key (e2b_...)."""
    return value.startswith(_E2B_PREFIX) and len(value) > len(_E2B_PREFIX)


def extract_api_key(headers: Mapping[str, str]) -> Optional[str]:
    """Return the E2B API key from ``Authorization: Bearer <key>``.

    Falls back to an ``X-E2B-Api-Key`` header for clients that cannot set a
    bearer. Appwrite lowercases header keys; both cases are checked. A header
    that exists but is empty or not shaped like an E2B key (injected by a
    proxy, or a bearer token for some OTHER service) is treated as absent —
    never returned as a candidate credential.
    """
    key: Optional[str] = None
    auth = headers.get("authorization") or headers.get("Authorization")
    if auth:
        parts = auth.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            key = parts[1].strip() or None
        else:
            key = auth.strip() or None
    if key is None:
        xkey = headers.get("x-e2b-api-key") or headers.get("X-E2B-Api-Key")
        key = xkey.strip() if xkey else None
    if key is not None and not _looks_like_e2b_key(key):
        # Header present but useless (empty placeholder, foreign token, junk).
        # Treat as missing so the query-string fallback can be consulted.
        return None
    return key


def extract_query_api_key(query: Mapping[str, object]) -> Optional[str]:
    """Return a non-empty URL-supplied key without exposing it in logs.

    ``e2b_api_key`` is the unambiguous preferred parameter. ``api_key`` is
    accepted for clients already using that conventional spelling.
    """
    for name in ("e2b_api_key", "api_key"):
        value = query.get(name)
        # Request frameworks may represent repeated query parameters as lists.
        if isinstance(value, (list, tuple)):
            value = value[-1] if value else None
        if value is not None:
            key = str(value).strip()
            if key:
                return key
    return None


def require_credential(
    headers: Mapping[str, str], query: Optional[Mapping[str, object]] = None
) -> str:
    """Return a well-formed header key first, then an URL key; else fail closed."""
    key = extract_api_key(headers)
    if not key and query is not None:
        key = extract_query_api_key(query)
    if not key:
        raise AuthError(
            "missing E2B API key; send Authorization: Bearer <key>, "
            "X-E2B-Api-Key, or ?e2b_api_key=<key>"
        )
    if not _looks_like_e2b_key(key):
        # Fail closed with a precise message instead of forwarding junk to E2B
        # (which would answer with its own opaque 'malformed' error).
        raise AuthError(
            "invalid E2B API key: expected the 'e2b_' prefix; check the key "
            "passed via header or ?e2b_api_key=<key>"
        )
    return key
