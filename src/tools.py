"""E2B operations registered as MCP tools.

The official MCP SDK derives ``tools/list`` schemas from the Python signatures
below and handles ``tools/call`` responses and errors. This module only
contains the E2B-specific work.
"""
from __future__ import annotations

import posixpath
import re
import shlex
from typing import Dict, Literal, Optional, TypedDict

import fileops
from e2b_adapter import SandboxAccessError, connect, list_sandboxes
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from reqctx import RequestContext, get_request_context
from state_store import get_last_sandbox_id, set_last_sandbox_id

ReadMode = Literal["full", "lines", "head", "tail", "bytes"]
WriteMode = Literal[
    "overwrite", "create", "append", "prepend", "insert_at_line",
    "replace_lines", "insert_at_offset",
]
Encoding = Literal["text", "base64"]

_PROJECTS_ROOT = "/home/user/repos"

class PauseResult(TypedDict):
    ok: bool
    sandbox_id: str
    action: str

class ExecResult(TypedDict, total=False):
    exit_code: int
    stdout: str
    stderr: str
    compacted: bool

class ProjectsListResult(TypedDict):
    projects: list[str]

class ProjectCreateResult(TypedDict, total=False):
    name: str
    created: bool
    git_initialized: bool

class FileEntry(TypedDict):
    name: Optional[str]
    path: Optional[str]
    type: Optional[str]

class FileWriteResult(TypedDict):
    ok: bool
    path: str
    mode: str
    bytes_written: int

class FileStatResult(TypedDict):
    path: str
    exists: bool

def _project_name(value: str) -> str:
    """Validate a direct child name under ``/home/user/repos``."""
    name = (value or "").strip()
    if not name:
        raise ToolError("project name must not be empty")
    if name in {".", ".."} or "/" in name or "\x00" in name or "\n" in name or "\r" in name:
        raise ToolError("project name must be a single directory name under /home/user/repos")
    return name

def _command_result(result):
    """Normalize E2B command result fields used by small internal helpers."""
    return (
        int(getattr(result, "exit_code", 0) or 0),
        _clean_terminal_text(getattr(result, "stdout", "")),
        _clean_terminal_text(getattr(result, "stderr", "")),
    )

def _project_path(project: str, path: str = ".") -> str:
    """Resolve a project-relative path without allowing escape from the project."""
    name = _project_name(project)
    raw = path or "."
    if raw.startswith("/"):
        raise ToolError("when project is set, path/cwd must be relative to that project")
    normalized = posixpath.normpath(raw)
    if normalized == ".." or normalized.startswith("../"):
        raise ToolError("project-relative path must stay inside the project")
    root = f"{_PROJECTS_ROOT}/{name}"
    return root if normalized == "." else f"{root}/{normalized}"


def _context() -> RequestContext:
    return get_request_context()


def _sandbox(sandbox_id: Optional[str]):
    context = _context()
    requested = (sandbox_id or "").strip()

    if requested:
        try:
            sandbox = connect(requested, context.api_key)
        except SandboxAccessError as exc:
            raise ToolError(str(exc)) from exc
        except Exception as exc:
            raise ToolError(f"sandbox unavailable: {exc}") from exc
        set_last_sandbox_id(context.api_key, context.appwrite_key, requested)
        return requested, sandbox

    remembered = get_last_sandbox_id(context.api_key, context.appwrite_key)
    if remembered:
        try:
            sandbox = connect(remembered, context.api_key)
            set_last_sandbox_id(context.api_key, context.appwrite_key, remembered)
            return remembered, sandbox
        except Exception:
            # The remembered sandbox may have expired or been removed. Fall
            # through to the first currently visible sandbox.
            pass

    try:
        sandboxes = list_sandboxes(context.api_key, limit=1)
        if not sandboxes or not sandboxes[0].get("sandbox_id"):
            raise ToolError("no existing E2B sandbox is available")
        sid = str(sandboxes[0]["sandbox_id"])
        sandbox = connect(sid, context.api_key)
        set_last_sandbox_id(context.api_key, context.appwrite_key, sid)
        return sid, sandbox
    except ToolError:
        raise
    except SandboxAccessError as exc:
        raise ToolError(str(exc)) from exc
    except Exception as exc:
        raise ToolError(f"sandbox unavailable: {exc}") from exc


def _text(value) -> str:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace")
    return value


def _as_bytes(value) -> bytes:
    return value.encode("utf-8") if isinstance(value, str) else bytes(value)


_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_NOISY_COMMAND_RE = re.compile(
    r"(?i)(?:^|[;&|()]|\bsudo\s+|\benv\s+)(?:\s*)(?:"
    r"apt(?:-get)?|aptitude|npm|npx|pnpm|yarn|bun|pip3?|python(?:3)?\s+-m\s+pip|"
    r"uv\s+pip|poetry|pdm|conda|mamba|cargo|rustup|gradle|gradlew|mvn|mvnw|"
    r"dotnet\s+(?:build|restore|test|publish)|go\s+(?:build|test|install)|"
    r"make|cmake|ninja|docker\s+(?:build|pull|push)|podman\s+(?:build|pull|push)"
    r")\b"
)
_ERROR_RE = re.compile(
    r"(?i)(?:\berror\b|\berr!\b|\bfailed?\b|\bfailure\b|\bfatal\b|\bexception\b|"
    r"\btraceback\b|\bpanic\b|permission denied|not found|cannot |can't |unable to|"
    r"segmentation fault|\bE[A-Z]{3,}\b)"
)
_WARNING_RE = re.compile(r"(?i)(?:\bwarn(?:ing)?\b|deprecated|deprecation|vulnerabilit)")
_SUMMARY_RE = re.compile(
    r"(?i)(?:success|successful|completed|\bdone\b|finished|built|installed|up to date|"
    r"added \d+|removed \d+|changed \d+|upgraded \d*|audited \d+|packages? .*upgraded|"
    r"tests? passed|passed \d+|BUILD SUCCESSFUL|BUILD FAILED)"
)

# Small output remains untouched. Noisy package/build commands are compacted only
# after they become large; every other command gets a much higher safety limit.
_NOISY_CHAR_LIMIT = 6_000
_NOISY_LINE_LIMIT = 60
_HARD_CHAR_LIMIT = 24_000
_HARD_LINE_LIMIT = 320
_MAX_ERROR_LINES = 28
_MAX_WARNING_LINES = 8
_MAX_SUMMARY_LINES = 12
_MAX_TAIL_LINES = 18
_MAX_COMPACT_CHARS = 9_000


def _clean_terminal_text(value) -> str:
    text = _text(value) or ""
    text = _ANSI_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    # Progress renderers often emit the same line repeatedly with CR. Collapse
    # consecutive duplicates while preserving real command output ordering.
    out = []
    previous = None
    for line in text.splitlines():
        line = line.rstrip()
        if line == previous:
            continue
        out.append(line)
        previous = line
    return "\n".join(out).strip()


def _needs_compaction(command: str, stdout: str, stderr: str) -> bool:
    combined = "\n".join(x for x in (stdout, stderr) if x)
    chars = len(combined)
    lines = combined.count("\n") + (1 if combined else 0)
    if chars > _HARD_CHAR_LIMIT or lines > _HARD_LINE_LIMIT:
        return True
    if _NOISY_COMMAND_RE.search(command):
        return chars > _NOISY_CHAR_LIMIT or lines > _NOISY_LINE_LIMIT
    return False


def _unique_matching(lines, pattern, limit: int):
    selected = []
    seen = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped in seen or not pattern.search(stripped):
            continue
        selected.append(stripped)
        seen.add(stripped)
        if len(selected) >= limit:
            break
    return selected


def _error_context(lines, limit: int = _MAX_ERROR_LINES):
    if not lines:
        return []
    indexes = [i for i, line in enumerate(lines) if _ERROR_RE.search(line)]
    if not indexes:
        return []
    picked = []
    seen = set()
    for index in indexes:
        for pos in range(max(0, index - 1), min(len(lines), index + 3)):
            line = lines[pos].strip()
            if line and line not in seen:
                picked.append(line)
                seen.add(line)
                if len(picked) >= limit:
                    return picked
    return picked


def _excerpt(lines, head: int = 6, tail: int = 8):
    clean = [line.strip() for line in lines if line.strip()]
    if len(clean) <= head + tail:
        return clean
    return clean[:head] + ["… output omitted …"] + clean[-tail:]


def _compact_exec_output(command: str, exit_code: int, stdout, stderr) -> ExecResult:
    stdout = _clean_terminal_text(stdout)
    stderr = _clean_terminal_text(stderr)

    if not _needs_compaction(command, stdout, stderr):
        result: ExecResult = {"exit_code": exit_code}
        if stdout:
            result["stdout"] = stdout
        if stderr:
            result["stderr"] = stderr
        return result

    stdout_lines = stdout.splitlines()
    stderr_lines = stderr.splitlines()
    all_lines = stderr_lines + stdout_lines
    noisy = bool(_NOISY_COMMAND_RE.search(command))

    summaries = _unique_matching(all_lines, _SUMMARY_RE, _MAX_SUMMARY_LINES)
    warnings = _unique_matching(all_lines, _WARNING_RE, _MAX_WARNING_LINES)

    if exit_code:
        errors = _error_context(stderr_lines) or _error_context(stdout_lines)
        if errors:
            compact_stderr = "\n".join(errors)
        elif stderr_lines:
            compact_stderr = "\n".join(_excerpt(stderr_lines, 3, _MAX_TAIL_LINES))
        else:
            compact_stderr = "\n".join(_excerpt(stdout_lines, 3, _MAX_TAIL_LINES))
        compact_stdout = "\n".join(summaries[:6])
    else:
        compact_stderr = "\n".join(warnings)
        if summaries:
            compact_stdout = "\n".join(summaries)
        elif noisy:
            # Exit code 0 is enough to establish success; do not retain package
            # manager progress just to have something in stdout.
            compact_stdout = ""
        else:
            # Generic oversized output might be intentional data rather than
            # boilerplate, so preserve a small head/tail excerpt for orientation.
            compact_stdout = "\n".join(_excerpt(stdout_lines))

    result: ExecResult = {"exit_code": exit_code, "compacted": True}
    if compact_stdout:
        result["stdout"] = compact_stdout
    if compact_stderr:
        result["stderr"] = compact_stderr
    return result


def register_tools(server: MCPServer) -> None:
    """Attach the server's deliberately limited E2B tool surface to ``server``."""

    @server.tool(
        description="Pause an existing sandbox. Its state is preserved for later resume."
    )
    def pause(sandbox_id: Optional[str] = None) -> PauseResult:
        sid, sandbox = _sandbox(sandbox_id)
        sandbox.pause()
        return {"ok": True, "sandbox_id": sid, "action": "paused"}

    @server.tool(
        description=(
            "Run a shell command in an existing sandbox. Set project to run inside "
            "/home/user/repos/<project>; when both project and cwd are set, cwd is project-relative. "
            "Keep output token-efficient: "
            "use precise paths and filters, and bound potentially large output with grep, "
            "sed -n, head, tail, or tool-specific quiet flags. Package/install/build commands "
            "and abnormally large outputs may be compacted automatically to exit status, "
            "actionable errors/warnings, and short summaries; small outputs remain unchanged."
        )
    )
    def exec(
        command: str,
        sandbox_id: Optional[str] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_ms: Optional[int] = None,
        project: Optional[str] = None,
    ) -> ExecResult:
        _, sandbox = _sandbox(sandbox_id)
        if project:
            cwd = _project_path(project, cwd or ".")
        kwargs = {}
        if cwd:
            kwargs["cwd"] = cwd
        if env:
            kwargs["envs"] = env
        if timeout_ms is not None:
            kwargs["timeout"] = max(1, timeout_ms // 1000)
        try:
            result = sandbox.commands.run(command, **kwargs)
            exit_code = getattr(result, "exit_code", 0)
            stdout = getattr(result, "stdout", "")
            stderr = getattr(result, "stderr", "")
        except Exception as exc:  # E2B exposes command result fields on errors.
            exit_code = getattr(exc, "exit_code", 1)
            stdout = getattr(exc, "stdout", "")
            stderr = getattr(exc, "stderr", str(exc))
        return _compact_exec_output(command, exit_code, stdout, stderr)

    @server.tool(
        structured_output=False,
        description=(
            "Search text/code with bounded output. Prefer project + a relative path so the model "
            "does not need to discover or repeat absolute paths. Uses ripgrep when available and "
            "falls back to grep; returns at most max_results matching lines."
        )
    )
    def search_code(
        query: str,
        sandbox_id: Optional[str] = None,
        project: Optional[str] = None,
        path: str = ".",
        glob: Optional[str] = None,
        regex: bool = False,
        max_results: int = 40,
    ) -> str:
        _, sandbox = _sandbox(sandbox_id)
        if not query:
            raise ToolError("query must not be empty")
        run_kwargs = {}
        if project:
            project_root = _project_path(project)
            resolved = _project_path(project, path)
            target = posixpath.relpath(resolved, project_root)
            run_kwargs["cwd"] = project_root
        else:
            target = path
        limit = max(1, min(int(max_results), 200))
        qquery = shlex.quote(query)
        qtarget = shlex.quote(target)
        fixed_rg = "" if regex else "-F "
        fixed_grep = "" if regex else "-F "
        rg_glob = f"-g {shlex.quote(glob)} " if glob else ""
        grep_glob = f"--include={shlex.quote(glob)} " if glob else ""
        command = (
            "if command -v rg >/dev/null 2>&1; then "
            f"rg -n --no-heading --color never {fixed_rg}{rg_glob}-- {qquery} {qtarget} 2>/dev/null | head -n {limit} || true; "
            "else "
            f"grep -RIn {fixed_grep}{grep_glob}--exclude-dir=.git -- {qquery} {qtarget} 2>/dev/null | head -n {limit} || true; "
            "fi"
        )
        try:
            result = sandbox.commands.run(command, **run_kwargs)
            _, stdout, _ = _command_result(result)
            return stdout
        except Exception as exc:
            raise ToolError(f"code search failed: {exc}") from exc

    @server.tool(
        description=(
            "List projects in /home/user/repos. Each direct child directory is one project. "
            "The filesystem is scanned on every call; there is no separate project registry."
        )
    )
    def projects_list(sandbox_id: Optional[str] = None) -> ProjectsListResult:
        _, sandbox = _sandbox(sandbox_id)
        root = shlex.quote(_PROJECTS_ROOT)
        command = (
            f"if [ -d {root} ]; then "
            f"find {root} -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | LC_ALL=C sort; "
            "fi"
        )
        try:
            result = sandbox.commands.run(command)
            exit_code, stdout, stderr = _command_result(result)
        except Exception as exc:
            raise ToolError(f"could not list projects: {exc}") from exc
        if exit_code:
            raise ToolError(stderr or f"could not list projects (exit {exit_code})")
        names = [line for line in stdout.splitlines() if line]
        return {"projects": names}

    @server.tool(
        description=(
            "Create one project as a direct child directory of /home/user/repos. "
            "Rejects path traversal. Optionally initialize an empty Git repository. "
            "Use projects_list to discover projects created by any method."
        )
    )
    def project_create(
        name: str,
        sandbox_id: Optional[str] = None,
        init_git: bool = False,
        exist_ok: bool = False,
    ) -> ProjectCreateResult:
        _, sandbox = _sandbox(sandbox_id)
        project = _project_name(name)
        path = f"{_PROJECTS_ROOT}/{project}"
        qroot = shlex.quote(_PROJECTS_ROOT)
        qpath = shlex.quote(path)
        if exist_ok:
            dir_branch = "printf 'existing\n'"
        else:
            dir_branch = f"printf 'project already exists: %s\n' {qpath} >&2; exit 17"
        command = (
            f"set -eu; mkdir -p {qroot}; "
            f"if [ -d {qpath} ]; then {dir_branch}; "
            f"elif [ -e {qpath} ]; then printf 'project path exists but is not a directory: %s\n' {qpath} >&2; exit 17; "
            f"else mkdir {qpath}; printf 'created\n'; fi"
        )
        if init_git:
            command += (
                "; command -v git >/dev/null 2>&1 || { printf 'git not found\n' >&2; exit 18; }; "
                f"[ -d {qpath}/.git ] || git -C {qpath} init -q"
            )
        try:
            result = sandbox.commands.run(command)
            exit_code, stdout, stderr = _command_result(result)
        except Exception as exc:
            raise ToolError(f"could not create project: {exc}") from exc
        if exit_code:
            raise ToolError(stderr or f"could not create project (exit {exit_code})")
        response: ProjectCreateResult = {
            "name": project,
            "created": stdout.splitlines()[0] == "created" if stdout else False,
        }
        if init_git:
            response["git_initialized"] = True
        return response

    @server.tool(description="List one directory level. With project set, path is relative to /home/user/repos/<project>.")
    def files_list(
        path: str = ".",
        sandbox_id: Optional[str] = None,
        project: Optional[str] = None,
    ) -> list[FileEntry]:
        _, sandbox = _sandbox(sandbox_id)
        if project:
            path = _project_path(project, path)
        entries: list[FileEntry] = []
        for entry in sandbox.files.list(path):
            entry_type = getattr(entry, "type", None)
            entries.append({
                "name": getattr(entry, "name", None),
                "path": getattr(entry, "path", None),
                "type": getattr(entry_type, "value", entry_type),
            })
        return entries

    @server.tool(
        structured_output=False,
        description="Read all or part of a file; prefer lines/head/tail for large files. With project set, path is project-relative; use base64 for binary data."
    )
    def files_read(
        path: str,
        sandbox_id: Optional[str] = None,
        mode: ReadMode = "full",
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        length: Optional[int] = None,
        encoding: Encoding = "text",
        project: Optional[str] = None,
    ) -> str:
        _, sandbox = _sandbox(sandbox_id)
        if project:
            path = _project_path(project, path)
        try:
            if not sandbox.files.exists(path):
                raise fileops.FileOpError(f"file not found: {path}")
            if encoding == "base64" or mode == "bytes":
                data = sandbox.files.read(path, format="bytes")
                if isinstance(data, str):
                    data = data.encode("utf-8")
                if mode == "bytes":
                    data = fileops.slice_by_bytes(data, offset, length)
                return fileops.b64encode(bytes(data))
            content = _text(sandbox.files.read(path))
            if mode == "full":
                return content
            if mode == "lines":
                return fileops.slice_by_lines(content, start_line or 1, end_line)
            if mode == "head":
                return fileops.head_lines(content, limit if limit is not None else 10)
            if mode == "tail":
                return fileops.tail_lines(content, limit if limit is not None else 10)
            raise fileops.FileOpError(f"unsupported read mode: {mode}")
        except fileops.FileOpError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        description="Write, append, or positionally insert content. With project set, path is relative to /home/user/repos/<project>."
    )
    def files_write(
        path: str,
        content: str,
        sandbox_id: Optional[str] = None,
        mode: WriteMode = "overwrite",
        line: Optional[int] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        offset: Optional[int] = None,
        encoding: Encoding = "text",
        project: Optional[str] = None,
    ) -> FileWriteResult:
        _, sandbox = _sandbox(sandbox_id)
        if project:
            path = _project_path(project, path)
        exists = sandbox.files.exists(path)
        try:
            if encoding == "base64":
                new = fileops.apply_bytes_write(
                    _as_bytes(sandbox.files.read(path, format="bytes")) if exists else None,
                    fileops.b64decode(content), mode, offset=offset,
                )
            else:
                old = _text(sandbox.files.read(path)) if exists else None
                new = fileops.apply_text_write(
                    old, content, mode, line=line, start_line=start_line,
                    end_line=end_line, offset=offset,
                )
        except fileops.FileOpError as exc:
            raise ToolError(str(exc)) from exc
        sandbox.files.write(path, new)
        byte_count = len(new.encode("utf-8")) if isinstance(new, str) else len(new)
        return {
            "ok": True, "path": path, "mode": mode, "bytes_written": byte_count,
        }

    @server.tool(description="Report whether a path exists. With project set, path is relative to /home/user/repos/<project>.")
    def files_stat(
        path: str = ".",
        sandbox_id: Optional[str] = None,
        project: Optional[str] = None,
    ) -> FileStatResult:
        _, sandbox = _sandbox(sandbox_id)
        if project:
            path = _project_path(project, path)
        return {"path": path, "exists": bool(sandbox.files.exists(path))}
