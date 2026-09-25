"use node";

import { Buffer } from "node:buffer";
import { internalActionGeneric } from "convex/server";
import { v } from "convex/values";
import { Sandbox } from "e2b";
import { canonicalTool } from "./mcp";

const PROJECTS_ROOT = "/home/user/repos";

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

function requireSandboxId(args: any): string {
  const sandboxId = String(args?.sandbox_id ?? "").trim();
  if (!sandboxId) {
    throw new Error("sandbox_id is required; call get_sandbox_id first and pass its sandbox_id to this tool");
  }
  return sandboxId;
}

async function firstSandboxId(apiKey: string): Promise<string> {
  const paginator = Sandbox.list({ apiKey, limit: 1 });
  const items = await paginator.nextItems();
  if (!items.length) throw new Error("no existing E2B sandbox is available");
  return items[0].sandboxId;
}

async function connect(apiKey: string, sandboxId: string) {
  return await Sandbox.connect(sandboxId, { apiKey });
}

function projectName(value: unknown) {
  const name = String(value ?? "").trim();
  if (!name || name === "." || name === ".." || /[\/\0\r\n]/.test(name)) {
    throw new Error("project name must be a single directory name under /home/user/repos");
  }
  return name;
}

function projectPath(project: unknown, relative = ".") {
  const name = projectName(project);
  const raw = String(relative || ".");
  if (raw.startsWith("/")) throw new Error("project-relative path must not be absolute");
  const parts: string[] = [];
  for (const part of raw.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") {
      if (!parts.length) throw new Error("project-relative path must stay inside the project");
      parts.pop();
    } else {
      parts.push(part);
    }
  }
  return `${PROJECTS_ROOT}/${name}${parts.length ? "/" + parts.join("/") : ""}`;
}

function shellQuote(value: unknown) {
  const s = String(value ?? "");
  if (!s) return "''";
  if (/^[\w@%+=:,./-]+$/.test(s)) return s;
  return `'${s.replace(/'/g, `'"'"'`)}'`;
}

function cleanText(value: unknown) {
  return String(value ?? "")
    .replace(/\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))/g, "")
    .replace(/\r\n?/g, "\n")
    .trim();
}

function normalizeExec(result: any) {
  const output: Record<string, Json> = { exit_code: Number(result?.exitCode ?? 0) };
  const stdout = cleanText(result?.stdout);
  const stderr = cleanText(result?.stderr);
  if (stdout) output.stdout = stdout;
  if (stderr) output.stderr = stderr;
  return output;
}

function textLines(text: string) {
  return text.match(/.*(?:\n|$)/g)?.filter(Boolean) ?? [];
}

function sliceLines(text: string, start: number, end?: number | null) {
  if (start < 1) throw new Error("start_line must be >= 1");
  if (end != null && end < start) throw new Error("end_line must be >= start_line");
  const lines = textLines(text);
  return lines.slice(start - 1, end == null ? undefined : end).join("");
}

function applyText(existing: string | null, content: string, mode: string, args: any) {
  if (mode === "overwrite") return content;
  if (mode === "create") {
    if (existing !== null) throw new Error("file already exists (mode=create)");
    return content;
  }
  const base = existing ?? "";
  if (mode === "append") return base && !base.endsWith("\n") ? `${base}\n${content}` : base + content;
  if (mode === "prepend") return content === "" || content.endsWith("\n") ? content + base : `${content}\n${base}`;
  if (mode === "insert_at_offset") {
    const offset = Number(args.offset);
    if (!Number.isInteger(offset) || offset < 0) throw new Error("insert_at_offset requires offset >= 0");
    const i = Math.min(offset, base.length);
    return base.slice(0, i) + content + base.slice(i);
  }
  const lines = textLines(base);
  if (mode === "insert_at_line") {
    const line = Number(args.line);
    if (!Number.isInteger(line) || line < 1) throw new Error("insert_at_line requires line >= 1");
    const i = Math.min(line - 1, lines.length);
    const block = content === "" || content.endsWith("\n") ? content : content + "\n";
    lines.splice(i, 0, block);
    return lines.join("");
  }
  if (mode === "replace_lines") {
    const start = Number(args.start_line);
    if (!Number.isInteger(start) || start < 1) throw new Error("replace_lines requires start_line >= 1");
    const end = args.end_line == null ? lines.length : Number(args.end_line);
    if (!Number.isInteger(end) || end < start) throw new Error("end_line must be >= start_line");
    const block = content === "" || content.endsWith("\n") ? content : content + "\n";
    lines.splice(start - 1, Math.max(0, end - start + 1), ...(block ? [block] : []));
    return lines.join("");
  }
  throw new Error(`unsupported write mode: ${mode}`);
}

function applyBytes(existing: Uint8Array | null, incoming: Uint8Array, mode: string, args: any) {
  if (mode === "overwrite") return incoming;
  if (mode === "create") {
    if (existing !== null) throw new Error("file already exists (mode=create)");
    return incoming;
  }
  const base = existing ?? new Uint8Array();
  if (mode === "append") return Buffer.concat([base, incoming]);
  if (mode === "prepend") return Buffer.concat([incoming, base]);
  if (mode === "insert_at_offset") {
    const offset = Number(args.offset);
    if (!Number.isInteger(offset) || offset < 0) throw new Error("insert_at_offset requires offset >= 0");
    const i = Math.min(offset, base.length);
    return Buffer.concat([base.slice(0, i), incoming, base.slice(i)]);
  }
  throw new Error(`unsupported binary write mode: ${mode}`);
}

async function runTool(apiKey: string, rawName: string, args: any): Promise<Json> {
  const name = canonicalTool(rawName);

  if (name === "get_sandbox_id") {
    return { sandbox_id: await firstSandboxId(apiKey) };
  }

  const sandboxId = requireSandboxId(args);
  const sandbox = await connect(apiKey, sandboxId);

  if (name === "pause") {
    await Sandbox.pause(sandboxId, { apiKey });
    return { ok: true, sandbox_id: sandboxId, action: "paused" };
  }

  if (name === "exec") {
    const command = String(args?.command ?? "");
    if (!command) throw new Error("command must not be empty");
    let cwd = args?.cwd ? String(args.cwd) : undefined;
    if (args?.project) cwd = projectPath(args.project, cwd ?? ".");
    const options: Record<string, any> = {};
    if (cwd) options.cwd = cwd;
    if (args?.env) options.envs = args.env;
    if (args?.timeout_ms != null) options.timeoutMs = Math.max(1, Number(args.timeout_ms));
    try {
      return normalizeExec(await sandbox.commands.run(command, options));
    } catch (error: any) {
      if (typeof error?.exitCode === "number") return normalizeExec(error);
      throw error;
    }
  }

  if (name === "search_code") {
    const query = String(args?.query ?? "");
    if (!query) throw new Error("query must not be empty");
    const maxResults = Math.max(1, Math.min(Number(args?.max_results ?? 40), 200));
    let target = String(args?.path ?? ".");
    const options: Record<string, any> = {};
    if (args?.project) {
      const root = projectPath(args.project);
      const resolved = projectPath(args.project, target);
      target = resolved === root ? "." : resolved.slice(root.length + 1);
      options.cwd = root;
    }
    const fixed = args?.regex ? "" : "-F ";
    const rgGlob = args?.glob ? `-g ${shellQuote(args.glob)} ` : "";
    const grepGlob = args?.glob ? `--include=${shellQuote(args.glob)} ` : "";
    const command =
      `if command -v rg >/dev/null 2>&1; then rg -n --no-heading --color never ${fixed}${rgGlob}-- ${shellQuote(query)} ${shellQuote(target)} 2>/dev/null | head -n ${maxResults} || true; ` +
      `else grep -RIn ${fixed}${grepGlob}--exclude-dir=.git -- ${shellQuote(query)} ${shellQuote(target)} 2>/dev/null | head -n ${maxResults} || true; fi`;
    const result = await sandbox.commands.run(command, options);
    return cleanText(result.stdout);
  }

  if (name === "projects_list") {
    const root = shellQuote(PROJECTS_ROOT);
    const result = await sandbox.commands.run(
      `if [ -d ${root} ]; then find ${root} -mindepth 1 -maxdepth 1 -type d -printf '%f\\n' | LC_ALL=C sort; fi`,
    );
    return { projects: cleanText(result.stdout).split("\n").filter(Boolean) };
  }

  if (name === "project_create") {
    const project = projectName(args?.name);
    const path = `${PROJECTS_ROOT}/${project}`;
    const qroot = shellQuote(PROJECTS_ROOT);
    const qpath = shellQuote(path);
    const existing = args?.exist_ok
      ? "printf 'existing\\n'"
      : `printf 'project already exists: %s\\n' ${qpath} >&2; exit 17`;
    let command =
      `set -eu; mkdir -p ${qroot}; if [ -d ${qpath} ]; then ${existing}; ` +
      `elif [ -e ${qpath} ]; then printf 'project path exists but is not a directory: %s\\n' ${qpath} >&2; exit 17; ` +
      `else mkdir ${qpath}; printf 'created\\n'; fi`;
    if (args?.init_git) {
      command += `; command -v git >/dev/null 2>&1 || { printf 'git not found\\n' >&2; exit 18; }; [ -d ${qpath}/.git ] || git -C ${qpath} init -q`;
    }
    const result = await sandbox.commands.run(command);
    const first = cleanText(result.stdout).split("\n")[0] ?? "";
    return {
      name: project,
      created: first === "created",
      ...(args?.init_git ? { git_initialized: true } : {}),
    };
  }

  if (name === "files_list") {
    let path = String(args?.path ?? ".");
    if (args?.project) path = projectPath(args.project, path);
    const entries = await sandbox.files.list(path);
    return entries.map((entry: any) => ({
      name: entry?.name ?? null,
      path: entry?.path ?? null,
      type: entry?.type ?? null,
    })) as Json;
  }

  if (name === "files_read") {
    let path = String(args?.path ?? "");
    if (!path) throw new Error("path must not be empty");
    if (args?.project) path = projectPath(args.project, path);
    if (!(await sandbox.files.exists(path))) throw new Error(`file not found: ${path}`);
    const mode = String(args?.mode ?? "full");
    const encoding = String(args?.encoding ?? "text");
    if (encoding === "base64" || mode === "bytes") {
      let data = await sandbox.files.read(path, { format: "bytes" });
      if (mode === "bytes") {
        const offset = Number(args?.offset ?? 0);
        const length = args?.length == null ? undefined : Number(args.length);
        if (!Number.isInteger(offset) || offset < 0) throw new Error("offset must be >= 0");
        if (length != null && (!Number.isInteger(length) || length < 0)) throw new Error("length must be >= 0");
        data = data.slice(offset, length == null ? undefined : offset + length);
      }
      return Buffer.from(data).toString("base64");
    }
    const content = await sandbox.files.read(path);
    if (mode === "full") return content;
    if (mode === "lines") return sliceLines(content, Number(args?.start_line ?? 1), args?.end_line == null ? null : Number(args.end_line));
    if (mode === "head") return textLines(content).slice(0, Math.max(0, Number(args?.limit ?? 10))).join("");
    if (mode === "tail") {
      const limit = Math.max(0, Number(args?.limit ?? 10));
      const lines = textLines(content);
      return limit === 0 ? "" : lines.slice(-limit).join("");
    }
    throw new Error(`unsupported read mode: ${mode}`);
  }

  if (name === "files_write") {
    let path = String(args?.path ?? "");
    if (!path) throw new Error("path must not be empty");
    if (args?.project) path = projectPath(args.project, path);
    const exists = await sandbox.files.exists(path);
    const mode = String(args?.mode ?? "overwrite");
    const encoding = String(args?.encoding ?? "text");
    let data: string | Uint8Array;
    if (encoding === "base64") {
      const existing = exists ? await sandbox.files.read(path, { format: "bytes" }) : null;
      data = applyBytes(existing, Buffer.from(String(args?.content ?? ""), "base64"), mode, args);
    } else {
      const existing = exists ? await sandbox.files.read(path) : null;
      data = applyText(existing, String(args?.content ?? ""), mode, args);
    }
    const payload = typeof data === "string" ? data : (Uint8Array.from(data).buffer as ArrayBuffer);
    await sandbox.files.write(path, payload);
    return {
      ok: true,
      path,
      mode,
      bytes_written: typeof data === "string" ? Buffer.byteLength(data) : data.byteLength,
    };
  }

  if (name === "files_stat") {
    let path = String(args?.path ?? ".");
    if (args?.project) path = projectPath(args.project, path);
    return { path, exists: await sandbox.files.exists(path) };
  }

  throw new Error(`unknown tool: ${rawName}`);
}

export const runToolAction = internalActionGeneric({
  args: {
    apiKey: v.string(),
    name: v.string(),
    arguments: v.any(),
  },
  handler: async (_ctx, args) => await runTool(args.apiKey, args.name, args.arguments),
});
