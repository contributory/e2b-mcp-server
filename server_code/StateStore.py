"""Remember the last selected sandbox per E2B API key in Anvil Data Tables."""
from __future__ import annotations

import hashlib
from typing import Optional

from anvil.tables import app_tables


def _key_digest(e2b_api_key: str) -> str:
    return hashlib.sha256(e2b_api_key.encode("utf-8")).hexdigest()


def get_last_sandbox_id(e2b_api_key: str) -> Optional[str]:
    if not e2b_api_key:
        return None
    row = app_tables.sandbox_state.get(key_digest=_key_digest(e2b_api_key))
    if row is None:
        return None
    value = row["sandbox_id"]
    return value.strip() if isinstance(value, str) and value.strip() else None


def set_last_sandbox_id(e2b_api_key: str, sandbox_id: str) -> None:
    if not e2b_api_key or not sandbox_id:
        return
    digest = _key_digest(e2b_api_key)
    row = app_tables.sandbox_state.get(key_digest=digest)
    if row is None:
        app_tables.sandbox_state.add_row(key_digest=digest, sandbox_id=sandbox_id)
    elif row["sandbox_id"] != sandbox_id:
        row["sandbox_id"] = sandbox_id
