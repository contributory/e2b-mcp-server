# E2B Sandbox MCP Server

A stateless MCP server deployed as an Appwrite Function. It operates only on
existing E2B sandboxes: it can pause a sandbox, run commands, and inspect or
edit files; it deliberately has no create, delete, or kill operation.

The server uses the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
for protocol handling, JSON-RPC, and generated tool schemas. `src/appwrite_mcp/`
is the adapter from Appwrite's
[`python/mcp-server` template](https://github.com/appwrite/templates/tree/main/python/mcp-server):
Appwrite never runs a Starlette lifespan, so `streamable_http_app()` is unusable
and each request is driven through the SDK's buffered entry points instead.

## Authentication

No environment variables are required. Supply the E2B API key on every
request, preferably as `Authorization: Bearer e2b_xxx`. `X-E2B-Api-Key`,
`?e2b_api_key=`, and the compatibility alias `?api_key=` are also accepted.
Header credentials take precedence. A missing or malformed key returns 401.

Set a default sandbox in the endpoint URL with `?sandbox_id=<id>`. Every tool
that uses a sandbox also accepts an optional `sandbox_id` argument, which takes
precedence over the URL value.

## Tools

| Tool | Purpose |
| --- | --- |
| `pause` | Pause an existing sandbox |
| `exec` | Run a shell command; optionally select a project as cwd |
| `search_code` | Bounded code/text search with ripgrep/grep fallback |
| `projects_list` | Discover projects from direct subdirectories of `~/repos/` |
| `project_create` | Create a project under `~/repos/`, optionally `git init` |
| `files_list` | List one directory level |
| `files_read` | Read all or part of a file |
| `files_write` | Write, append, or positionally modify a file |
| `files_stat` | Check whether a path exists |

Backward-compatible aliases remain available for existing clients: `sandbox_pause`,
`sandbox_exec`, `sandbox_files_list`, `sandbox_files_read`, `sandbox_files_write`,
and `sandbox_files_stat`. The aliases call the same implementations as the short names.

`files_read` supports `full`, `lines`, `head`, `tail`, and `bytes`
modes. `files_write` supports `overwrite`, `create`, `append`,
`prepend`, `insert_at_line`, `replace_lines`, and `insert_at_offset`.

### Project workspace

Projects are intentionally filesystem-native: every direct child directory of
`/home/user/repos` is a project. There is no registry or metadata database to
keep in sync. `projects_list` scans that directory on each call, so a
repository cloned or copied there by any other tool is discovered automatically.

`project_create(name, init_git=false)` creates `/home/user/repos/<name>`;
project names cannot contain `/`, newlines, NUL, `.` or `..`. Set `exist_ok=true`
for idempotent setup. When `init_git=true`, creation fails clearly if Git is not
available instead of silently claiming initialization succeeded.

For shorter, safer tool calls, `exec` and all file tools accept a
`project` argument. With it, `cwd`/`path` is resolved relative to that project's
directory and `..` escapes are rejected. `search_code` follows the same
rule and caps returned matches (`40` by default, `200` maximum) to avoid sending
large grep output through the model context.

## Deployment

Use `src/main.py` as the Appwrite entrypoint and `pip install -r
requirements.txt` as the build command. `main` is `async` — the runtime already
owns the event loop, so it must never call `asyncio.run`.

Optional environment variables: `MCP_SERVER_NAME` (default `e2b-sandbox-mcp`)
and `MCP_TOOL_TIMEOUT` (soft deadline in seconds, default `25`, below
Appwrite's 30s domain hard-cap).

Requests are JSON-mode Streamable HTTP on `/`. Both protocol legs are served:
legacy handshakes (`2024-11-05` … `2025-11-25`) via `serve_one`, and the modern
`2026-07-28` envelope via `handle_modern_request`. `GET`/`DELETE` return 405
(no SSE streams, no sessions); `OPTIONS` returns 204 with CORS headers.

## Layout

```text
src/
├── main.py         # async Appwrite entrypoint: auth + request context
├── app.py          # MCPServer definition (never name it server.py)
├── tools.py        # Python-signature MCP tool registrations
├── appwrite_mcp/   # vendored Appwrite ↔ MCP adapter (template)
├── e2b_adapter.py  # E2B connect-only adapter
├── fileops.py      # partial-read and positional-write helpers
├── reqctx.py       # request-scoped E2B credential/context
└── security.py     # fail-closed credential parsing
```

## Security notes

Use HTTPS and avoid URL credentials when headers are available, since URLs can
be retained in browser history, proxies, and telemetry. This is a
bring-your-own-key proxy: the no-create/no-delete restriction applies only to
this MCP interface, not to direct E2B API access by a key holder.
