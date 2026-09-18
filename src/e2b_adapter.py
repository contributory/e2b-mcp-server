"""Thin adapter over the E2B SDK.

CONNECT + LIST only. There is no ``create`` and no ``kill`` / ``delete`` path,
so a client driving this server can attach to and inspect existing sandboxes
but can never spin up or destroy them.

The API key is always passed in per request (zero-ENV); nothing here reads the
environment. The E2B SDK is imported lazily so the module imports (and
``tools/list`` works) even when the dependency is absent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class SandboxAccessError(Exception):
    """Raised when a sandbox cannot be resolved / connected under policy."""


def _import_sandbox():
    try:
        from e2b import Sandbox  # type: ignore

        return Sandbox
    except Exception as exc:  # noqa: BLE001
        raise SandboxAccessError(
            "e2b SDK not installed; add 'e2b' to requirements.txt"
        ) from exc


def resolve_sandbox_id(requested: Optional[str], default: Optional[str]) -> str:
    """Effective sandbox id: explicit arg wins, else the URL query default."""
    sid = (requested or default or "").strip()
    if not sid:
        raise SandboxAccessError(
            "no sandbox_id: pass it in the tool arguments or the ?sandbox_id= "
            "URL query param"
        )
    return sid


def connect(sandbox_id: str, api_key: str):
    """Connect to an EXISTING sandbox with the caller's key."""
    if not api_key:
        raise SandboxAccessError("missing E2B API key")
    Sandbox = _import_sandbox()
    return Sandbox.connect(sandbox_id, api_key=api_key)


def _collect(res: Any, limit: int) -> List[Any]:
    """Normalize whatever Sandbox.list returns (list or paginator) to a list."""
    out: List[Any] = []
    if isinstance(res, list):
        return res[:limit]
    if hasattr(res, "next_items"):
        while len(out) < limit:
            batch = res.next_items()
            if not batch:
                break
            out.extend(batch)
        return out[:limit]
    try:
        for x in res:
            out.append(x)
            if len(out) >= limit:
                break
    except TypeError:
        pass
    return out


def _to_dict(item: Any) -> Dict[str, Any]:
    state = getattr(item, "state", None) or getattr(item, "status", None)
    return {
        "sandbox_id": getattr(item, "sandbox_id", None) or getattr(item, "id", None),
        "template_id": getattr(item, "template_id", None),
        "name": getattr(item, "name", None) or getattr(item, "alias", None),
        "state": getattr(state, "value", state),
        "started_at": (str(getattr(item, "started_at", "")) or None),
        "end_at": (str(getattr(item, "end_at", "")) or None),
        "metadata": getattr(item, "metadata", None),
    }


def list_sandboxes(
    api_key: str,
    *,
    limit: int = 50,
    metadata: Optional[Dict[str, str]] = None,
    state: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List sandboxes visible to the given API key (read-only).

    Filtering by ``metadata`` / ``state`` is applied client-side for
    portability across SDK versions.
    """
    if not api_key:
        raise SandboxAccessError("missing E2B API key")
    Sandbox = _import_sandbox()
    res = Sandbox.list(api_key=api_key)
    items = [_to_dict(x) for x in _collect(res, max(limit, 1) * 4)]

    if metadata:
        items = [
            it
            for it in items
            if it.get("metadata")
            and all(str(it["metadata"].get(k)) == str(v) for k, v in metadata.items())
        ]
    if state:
        items = [it for it in items if it.get("state") == state]
    return items[:limit]
