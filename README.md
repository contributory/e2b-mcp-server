# E2B Sandbox MCP on Convex

Stateless MCP-over-HTTP bridge for controlling **existing** E2B sandboxes from a Convex deployment.

The server runs as a Convex HTTP Action at `/mcp`. E2B SDK calls run in a Convex Node.js Action so command execution and filesystem access can use the official `e2b` package directly.

## Runtime

- Convex `1.46.0`
- E2B JavaScript SDK `2.51.0`
- Convex Node.js runtime pinned to Node `22` in `convex.json`
- TypeScript only; there is no Anvil/Appwrite/PubNub runtime or Python dependency

## Tool flow

`get_sandbox_id` is the discovery tool and **must be called before any other tool**. It returns the ID of the first sandbox visible to the supplied E2B API key.

Every other tool requires `sandbox_id` as a mandatory argument. The server also validates this at runtime, so a tool call without `sandbox_id` fails with an instruction to call `get_sandbox_id` first.

Available tools:

- `get_sandbox_id`
- `pause`
- `exec`
- `search_code`
- `projects_list`
- `project_create`
- `files_list`
- `files_read`
- `files_write`
- `files_stat`

Compatibility aliases are retained for `sandbox_pause`, `sandbox_exec`, `sandbox_files_list`, `sandbox_files_read`, `sandbox_files_write`, and `sandbox_files_stat`.

The bridge does not create or delete E2B sandboxes.

## Authentication

Each request supplies its own E2B API key. Supported forms, in priority order:

1. `Authorization: Bearer e2b_...`
2. `X-E2B-Api-Key: e2b_...`
3. `?e2b_api_key=e2b_...` (or compatibility alias `?api_key=...`)

Keys are passed directly to the E2B SDK and are not persisted by Convex.

## Deploy

```bash
npm install
npx convex login
npx convex dev
```

After linking the directory to a Convex project, deploy production functions with:

```bash
npx convex deploy
```

The MCP URL is:

```text
https://<deployment>.convex.site/mcp
```

For MCP clients that cannot set headers:

```text
https://<deployment>.convex.site/mcp?e2b_api_key=e2b_...
```

## Development checks

```bash
npm test
npm run check
```

The contract tests ensure `get_sandbox_id` is the discovery tool and that every other exposed tool requires `sandbox_id`.
