# E2B Sandbox MCP Server (Anvil)

A stateless JSON-mode Streamable HTTP MCP endpoint hosted in an Anvil Server Module. It operates only on existing E2B sandboxes; there are no create, kill or delete operations.

## Deploy to Anvil

1. In Anvil, create an app using **Clone from GitHub** with this repository. Under **Settings → Python version**, select **Python 3.10** and make sure the updated `anvil.yaml` is pulled into the app. Its `runtime_options.server_spec.base: python310-standard` pins the server environment; `client_version: '3'` controls only browser-side Python. Anvil loads server modules from `server_code/` and the `sandbox_state` Data Table from `anvil.yaml`. If Anvil reports `future feature annotations is not defined` in `dispatch.py`, the app is running an older server Python: reselect Python 3.10 and pull the latest GitHub revision.
2. In the app's Python version settings, install the packages from the app requirements (`server_code/requirements.txt`; mirrored at root as `requirements.txt`): `mcp==2.2.0`, `e2b==2.51.0`, and `anyio==4.15.1`. Anvil supports installing packages through its app-specific requirements editor.
3. Publish the app and use `https://<your-app>.anvil.app/_/api/mcp` as the MCP URL. The endpoint must be publicly reachable; E2B credentials authenticate every POST request. A private Anvil app requires its private access-key segment in the URL.
4. Send the caller's E2B API key in `Authorization: Bearer e2b_...`, `X-E2B-Api-Key`, or `?e2b_api_key=...` if the MCP client only accepts a URL. The compatibility query alias `?api_key=...` remains supported. Headers take precedence over query parameters.

The endpoint accepts POST and OPTIONS; GET and DELETE return 405. It sends JSON responses without an SSE stream or session. Legacy and modern MCP handshakes are handled by the existing buffered MCP dispatcher. The default request deadline is 25 seconds (`MCP_TOOL_TIMEOUT` can override it in the server environment).

## Sandbox selection

Every sandbox-backed tool accepts an optional `sandbox_id`. An explicit ID is used and remembered. Without one, the server first tries the last-used ID; if it no longer exists, the server connects to the first available E2B sandbox. The `sandbox_state` table has `key_digest` and `sandbox_id` text columns and server-only access. The key digest is SHA-256 of the E2B API key; the raw key is never stored. There is no Appwrite Database or Storage dependency.

Projects are directories directly under `/home/user/repos` in the selected E2B sandbox. The MCP server has no separate project registry.

## Tools

| Tool | Purpose |
| --- | --- |
| `pause` | Pause an existing sandbox |
| `exec` | Run a shell command, optionally in a project |
| `search_code` | Search source files with bounded output |
| `projects_list`, `project_create` | Discover or create project directories |
| `files_list`, `files_read`, `files_write`, `files_stat` | Inspect and edit sandbox files |

The compatibility aliases for the earlier sandbox-prefixed tool names are retained.

## Source layout

- `server_code/McpEndpoint.py`: Anvil HTTP endpoint, authentication, CORS and request deadline.
- `server_code/mcp_bridge/dispatch.py`: Buffered MCP protocol dispatcher.
- `server_code/McpServer.py`, `server_code/Tools.py`: Tool schemas and handlers.
- `server_code/StateStore.py`: Anvil Data Table persistence for the selected sandbox.
- `server_code/E2BAdapter.py`, `server_code/FileOps.py`, `server_code/Security.py`, `server_code/RequestContext.py`: E2B operations and helpers.
- `anvil.yaml`: Anvil app configuration and Data Table schema.

## Local checks

Run `python3 -m compileall -q server_code` to check syntax, and `python3 -m unittest discover -s tests -v` for adapter/state tests. The Anvil HTTP endpoint and package installation still need verification in a published Anvil app.
