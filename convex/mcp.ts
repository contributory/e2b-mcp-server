export const SERVER_NAME = "e2b-sandbox-mcp";
export const SERVER_VERSION = "2.0.0";
export const PROTOCOL_VERSION = "2025-06-18";

const nullableString = { anyOf: [{ type: "string" }, { type: "null" }], default: null };
const nullableInt = { anyOf: [{ type: "integer" }, { type: "null" }], default: null };
const sandboxId = {
  type: "string",
  description: "Required E2B sandbox ID. Call get_sandbox_id first and pass the returned sandbox_id.",
};
const prefix = "REQUIRED FLOW: call get_sandbox_id first, then pass its sandbox_id to this tool. ";

export const tools = [
  {
    name: "get_sandbox_id",
    description: "MUST be called before any other tool. Returns the sandbox_id of the first E2B sandbox visible to the supplied API key.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "pause",
    description: prefix + "Pause an existing sandbox. Its state is preserved for later resume.",
    inputSchema: { type: "object", required: ["sandbox_id"], properties: { sandbox_id: sandboxId } },
  },
  {
    name: "exec",
    description: prefix + "Run a shell command in an existing sandbox.",
    inputSchema: {
      type: "object",
      required: ["command", "sandbox_id"],
      properties: {
        command: { type: "string" }, sandbox_id: sandboxId, cwd: nullableString,
        env: { anyOf: [{ type: "object", additionalProperties: { type: "string" } }, { type: "null" }], default: null },
        timeout_ms: nullableInt, project: nullableString,
      },
    },
  },
  {
    name: "search_code",
    description: prefix + "Search text/code with bounded output.",
    inputSchema: {
      type: "object",
      required: ["query", "sandbox_id"],
      properties: {
        query: { type: "string" }, sandbox_id: sandboxId, project: nullableString,
        path: { type: "string", default: "." }, glob: nullableString,
        regex: { type: "boolean", default: false }, max_results: { type: "integer", default: 40 },
      },
    },
  },
  {
    name: "projects_list",
    description: prefix + "List projects in /home/user/repos.",
    inputSchema: { type: "object", required: ["sandbox_id"], properties: { sandbox_id: sandboxId } },
  },
  {
    name: "project_create",
    description: prefix + "Create one project under /home/user/repos.",
    inputSchema: {
      type: "object", required: ["name", "sandbox_id"],
      properties: {
        name: { type: "string" }, sandbox_id: sandboxId,
        init_git: { type: "boolean", default: false }, exist_ok: { type: "boolean", default: false },
      },
    },
  },
  {
    name: "files_list",
    description: prefix + "List one directory level.",
    inputSchema: {
      type: "object", required: ["sandbox_id"],
      properties: { path: { type: "string", default: "." }, sandbox_id: sandboxId, project: nullableString },
    },
  },
  {
    name: "files_read",
    description: prefix + "Read all or part of a file.",
    inputSchema: {
      type: "object", required: ["path", "sandbox_id"],
      properties: {
        path: { type: "string" }, sandbox_id: sandboxId,
        mode: { type: "string", enum: ["full", "lines", "head", "tail", "bytes"], default: "full" },
        start_line: nullableInt, end_line: nullableInt, limit: nullableInt,
        offset: { type: "integer", default: 0 }, length: nullableInt,
        encoding: { type: "string", enum: ["text", "base64"], default: "text" }, project: nullableString,
      },
    },
  },
  {
    name: "files_write",
    description: prefix + "Write, append, or positionally insert content.",
    inputSchema: {
      type: "object", required: ["path", "content", "sandbox_id"],
      properties: {
        path: { type: "string" }, content: { type: "string" }, sandbox_id: sandboxId,
        mode: { type: "string", enum: ["overwrite", "create", "append", "prepend", "insert_at_line", "replace_lines", "insert_at_offset"], default: "overwrite" },
        line: nullableInt, start_line: nullableInt, end_line: nullableInt, offset: nullableInt,
        encoding: { type: "string", enum: ["text", "base64"], default: "text" }, project: nullableString,
      },
    },
  },
  {
    name: "files_stat",
    description: prefix + "Report whether a path exists.",
    inputSchema: {
      type: "object", required: ["sandbox_id"],
      properties: { path: { type: "string", default: "." }, sandbox_id: sandboxId, project: nullableString },
    },
  },
] as const;

const aliases: Record<string, string> = {
  sandbox_pause: "pause",
  sandbox_exec: "exec",
  sandbox_files_list: "files_list",
  sandbox_files_read: "files_read",
  sandbox_files_write: "files_write",
  sandbox_files_stat: "files_stat",
};

export const allTools = [
  ...tools,
  ...Object.entries(aliases).map(([name, target]) => ({
    ...tools.find((tool) => tool.name === target)!,
    name,
  })),
];

export function canonicalTool(name: string) {
  return aliases[name] ?? name;
}
