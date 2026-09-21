"""Persist the last-used E2B sandbox in Appwrite Database.

The caller's raw E2B API key is never stored. A SHA-256 digest is used as the
Appwrite document id so state stays isolated per E2B credential.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

_DATABASE_ID = os.environ.get("E2B_MCP_DATABASE_ID", "e2b-mcp")
_COLLECTION_ID = os.environ.get("E2B_MCP_COLLECTION_ID", "sandbox-state")
_SCHEMA_READY = False


def _endpoint() -> Optional[str]:
    value = (os.environ.get("APPWRITE_FUNCTION_API_ENDPOINT") or "").rstrip("/")
    return value or None


def _project_id() -> Optional[str]:
    return os.environ.get("APPWRITE_FUNCTION_PROJECT_ID") or None


def _document_id(e2b_api_key: str) -> str:
    return hashlib.sha256(e2b_api_key.encode("utf-8")).hexdigest()[:36]


def _request(appwrite_key: str, method: str, path: str, payload: Optional[dict] = None):
    endpoint = _endpoint()
    project = _project_id()
    if not endpoint or not project or not appwrite_key:
        return None, None
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    if endpoint.endswith("/v1") and path.startswith("/v1/"):
        url = endpoint + path[3:]
    else:
        url = endpoint + path
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Appwrite-Project": project,
            "X-Appwrite-Key": appwrite_key,
        },
    )
    try:
        with urlopen(request, timeout=4) as response:
            body = response.read()
            parsed = json.loads(body) if body else {}
            return response.status, parsed
    except HTTPError as exc:
        try:
            body = json.loads(exc.read() or b"{}")
        except Exception:
            body = None
        return exc.code, body
    except (URLError, TimeoutError, ValueError, OSError):
        return None, None


def _ensure_schema(appwrite_key: str) -> bool:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return True

    db = quote(_DATABASE_ID, safe="")
    col = quote(_COLLECTION_ID, safe="")
    calls = [
        ("POST", "/v1/databases", {
            "databaseId": _DATABASE_ID,
            "name": "E2B MCP",
            "enabled": True,
        }),
        ("POST", f"/v1/databases/{db}/collections", {
            "collectionId": _COLLECTION_ID,
            "name": "Sandbox state",
            "permissions": [],
            "documentSecurity": False,
            "enabled": True,
        }),
        ("POST", f"/v1/databases/{db}/collections/{col}/attributes/string", {
            "key": "sandbox_id",
            "size": 128,
            "required": True,
        }),
    ]
    for method, path, payload in calls:
        status, _ = _request(appwrite_key, method, path, payload)
        if status not in (201, 409):
            return False

    # Attribute creation is asynchronous. Give Appwrite a short chance to make
    # the schema writable on the very first invocation.
    for _ in range(5):
        status, body = _request(
            appwrite_key,
            "GET",
            f"/v1/databases/{db}/collections/{col}/attributes/sandbox_id",
        )
        if status == 200 and isinstance(body, dict) and body.get("status") == "available":
            _SCHEMA_READY = True
            return True
        time.sleep(0.2)
    return False


def get_last_sandbox_id(e2b_api_key: str, appwrite_key: str) -> Optional[str]:
    if not e2b_api_key or not appwrite_key or not _ensure_schema(appwrite_key):
        return None
    db = quote(_DATABASE_ID, safe="")
    col = quote(_COLLECTION_ID, safe="")
    doc = quote(_document_id(e2b_api_key), safe="")
    status, body = _request(
        appwrite_key,
        "GET",
        f"/v1/databases/{db}/collections/{col}/documents/{doc}",
    )
    if status != 200 or not isinstance(body, dict):
        return None
    value = body.get("sandbox_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def set_last_sandbox_id(e2b_api_key: str, appwrite_key: str, sandbox_id: str) -> None:
    if (
        not e2b_api_key
        or not appwrite_key
        or not sandbox_id
        or not _ensure_schema(appwrite_key)
    ):
        return
    db = quote(_DATABASE_ID, safe="")
    col = quote(_COLLECTION_ID, safe="")
    document_id = _document_id(e2b_api_key)
    _request(
        appwrite_key,
        "PUT",
        f"/v1/databases/{db}/collections/{col}/documents/{quote(document_id, safe='')}",
        {
            "documentId": document_id,
            "data": {"sandbox_id": sandbox_id},
        },
    )