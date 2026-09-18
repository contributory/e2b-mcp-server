"""Pure, transport-agnostic helpers for partial reads and positional writes.

These functions operate on plain Python ``str`` / ``bytes`` so they can be
unit-tested without any E2B or network dependency. The E2B adapter reads the
current file content (only when a mode needs it), calls one of these helpers,
and writes the result back.

Design note: positional inserts are implemented as read-modify-write in the
server layer because the E2B filesystem API exposes whole-file read/write, not
random-access splicing. This is simple and correct but NOT concurrency-safe;
two overlapping insert calls can lose data. Callers that need atomicity should
serialize writes to the same path.
"""
from __future__ import annotations

import base64
from typing import Optional


class FileOpError(ValueError):
    """Raised for invalid partial-read / positional-write parameters."""


# --------------------------------------------------------------------------- #
# Partial read
# --------------------------------------------------------------------------- #
def slice_by_lines(text: str, start_line: int, end_line: Optional[int]) -> str:
    """Return lines ``[start_line, end_line]`` (1-based, inclusive).

    ``end_line=None`` means "to end of file". Out-of-range values are clamped.
    """
    if start_line < 1:
        raise FileOpError("start_line must be >= 1")
    if end_line is not None and end_line < start_line:
        raise FileOpError("end_line must be >= start_line")
    lines = text.splitlines(keepends=True)
    n = len(lines)
    lo = min(start_line, n + 1) - 1
    hi = n if end_line is None else min(end_line, n)
    return "".join(lines[lo:hi])


def head_lines(text: str, limit: int) -> str:
    """Return the first ``limit`` lines."""
    if limit < 0:
        raise FileOpError("limit must be >= 0")
    lines = text.splitlines(keepends=True)
    return "".join(lines[:limit])


def tail_lines(text: str, limit: int) -> str:
    """Return the last ``limit`` lines."""
    if limit < 0:
        raise FileOpError("limit must be >= 0")
    if limit == 0:
        return ""
    lines = text.splitlines(keepends=True)
    return "".join(lines[max(0, len(lines) - limit):])


def slice_by_bytes(data: bytes, offset: int, length: Optional[int]) -> bytes:
    """Return ``data[offset : offset+length]``. ``length=None`` -> to EOF."""
    if offset < 0:
        raise FileOpError("offset must be >= 0")
    if length is not None and length < 0:
        raise FileOpError("length must be >= 0")
    end = None if length is None else offset + length
    return data[offset:end]


# --------------------------------------------------------------------------- #
# Positional write / insert
# --------------------------------------------------------------------------- #
WRITE_MODES = (
    "overwrite",
    "create",
    "append",
    "prepend",
    "insert_at_line",
    "replace_lines",
    "insert_at_offset",
)


def _ensure_trailing_newline(s: str) -> str:
    return s if (s == "" or s.endswith("\n")) else s + "\n"


def apply_text_write(
    existing: Optional[str],
    content: str,
    mode: str,
    *,
    line: Optional[int] = None,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    offset: Optional[int] = None,
) -> str:
    """Compute the complete new file content for a text write/insert.

    ``existing`` is ``None`` when the file does not exist yet.
    """
    if mode not in WRITE_MODES:
        raise FileOpError(f"unknown write mode: {mode}")

    if mode == "overwrite":
        return content

    if mode == "create":
        if existing is not None:
            raise FileOpError("file already exists (mode=create)")
        return content

    base = existing or ""

    if mode == "append":
        if base and not base.endswith("\n"):
            base = base + "\n"
        return base + content

    if mode == "prepend":
        return _ensure_trailing_newline(content) + base

    lines = base.splitlines(keepends=True)
    n = len(lines)

    if mode == "insert_at_line":
        if line is None or line < 1:
            raise FileOpError("insert_at_line requires line >= 1")
        idx = min(line, n + 1) - 1
        block = _ensure_trailing_newline(content)
        # keep the line before the insertion point terminated
        if idx > 0 and not lines[idx - 1].endswith("\n"):
            lines[idx - 1] = lines[idx - 1] + "\n"
        return "".join(lines[:idx] + [block] + lines[idx:])

    if mode == "replace_lines":
        if start_line is None or start_line < 1:
            raise FileOpError("replace_lines requires start_line >= 1")
        e = n if end_line is None else end_line
        if e < start_line:
            raise FileOpError("end_line must be >= start_line")
        lo, hi = start_line - 1, min(e, n)
        block = _ensure_trailing_newline(content) if content != "" else ""
        return "".join(lines[:lo] + ([block] if block else []) + lines[hi:])

    if mode == "insert_at_offset":
        if offset is None or offset < 0:
            raise FileOpError("insert_at_offset requires offset >= 0")
        off = min(offset, len(base))
        return base[:off] + content + base[off:]

    raise FileOpError(f"unhandled mode: {mode}")  # pragma: no cover


def apply_bytes_write(
    existing: Optional[bytes],
    content: bytes,
    mode: str,
    *,
    offset: Optional[int] = None,
) -> bytes:
    """Binary variant: overwrite / create / append / prepend / insert_at_offset."""
    if mode == "overwrite":
        return content
    if mode == "create":
        if existing is not None:
            raise FileOpError("file already exists (mode=create)")
        return content
    base = existing or b""
    if mode == "append":
        return base + content
    if mode == "prepend":
        return content + base
    if mode == "insert_at_offset":
        if offset is None or offset < 0:
            raise FileOpError("insert_at_offset requires offset >= 0")
        off = min(offset, len(base))
        return base[:off] + content + base[off:]
    raise FileOpError(f"unsupported binary write mode: {mode}")


# --------------------------------------------------------------------------- #
# Base64 helpers (binary payloads travel as base64 text over JSON-RPC)
# --------------------------------------------------------------------------- #
def b64decode(s: str) -> bytes:
    try:
        return base64.b64decode(s, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise FileOpError(f"invalid base64 content: {exc}") from exc


def b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
