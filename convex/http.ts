import { httpActionGeneric, httpRouter, makeFunctionReference } from "convex/server";
import { allTools, PROTOCOL_VERSION, SERVER_NAME, SERVER_VERSION } from "./mcp";

const http = httpRouter();
const runTool = makeFunctionReference<"action">("e2b:runToolAction") as any;

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization, Content-Type, X-E2B-Api-Key, MCP-Protocol-Version",
  "Access-Control-Expose-Headers": "MCP-Protocol-Version",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...corsHeaders,
      "Content-Type": "application/json",
      "MCP-Protocol-Version": PROTOCOL_VERSION,
    },
  });
}

function rpcResult(id: unknown, result: unknown) {
  return { jsonrpc: "2.0", id: id ?? null, result };
}

function rpcError(id: unknown, code: number, message: string, data?: unknown) {
  return {
    jsonrpc: "2.0",
    id: id ?? null,
    error: { code, message, ...(data === undefined ? {} : { data }) },
  };
}

function looksLikeE2BKey(value: string | null | undefined) {
  return !!value && value.startsWith("e2b_") && value.length > 4;
}

function apiKeyFrom(request: Request) {
  const auth = request.headers.get("authorization");
  let candidate: string | null = null;
  if (auth) {
    const match = auth.match(/^Bearer\s+(.+)$/i);
    candidate = (match ? match[1] : auth).trim();
    if (!looksLikeE2BKey(candidate)) candidate = null;
  }
  if (!candidate) {
    const header = request.headers.get("x-e2b-api-key")?.trim();
    if (looksLikeE2BKey(header)) candidate = header!;
  }
  if (!candidate) {
    const url = new URL(request.url);
    const query = (url.searchParams.get("e2b_api_key") ?? url.searchParams.get("api_key"))?.trim();
    if (looksLikeE2BKey(query)) candidate = query!;
  }
  if (!candidate) {
    throw new Error("missing or invalid E2B API key; send Authorization: Bearer <e2b_...>, X-E2B-Api-Key, or ?e2b_api_key=<e2b_...>");
  }
  return candidate;
}

async function dispatch(ctx: any, apiKey: string, message: any) {
  const id = message?.id;
  const method = message?.method;

  if (!message || message.jsonrpc !== "2.0" || typeof method !== "string") {
    return rpcError(id, -32600, "Invalid Request");
  }

  if (method === "initialize") {
    return rpcResult(id, {
      protocolVersion: PROTOCOL_VERSION,
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: SERVER_NAME, version: SERVER_VERSION },
      instructions:
        "You MUST call get_sandbox_id before calling any other tool. Every other tool requires the sandbox_id returned by get_sandbox_id.",
    });
  }

  if (method === "ping") return rpcResult(id, {});
  if (method === "notifications/initialized" || method.startsWith("notifications/")) return null;

  if (method === "tools/list") {
    return rpcResult(id, { tools: allTools });
  }

  if (method === "tools/call") {
    const name = message?.params?.name;
    const args = message?.params?.arguments ?? {};
    if (typeof name !== "string") return rpcError(id, -32602, "Invalid params: tool name is required");

    try {
      const value = await ctx.runAction(runTool, { apiKey, name, arguments: args });
      const text = typeof value === "string" ? value : JSON.stringify(value);
      return rpcResult(id, {
        content: [{ type: "text", text }],
        ...(typeof value === "string" ? {} : { structuredContent: value }),
      });
    } catch (error: any) {
      return rpcResult(id, {
        content: [{ type: "text", text: error?.message ? String(error.message) : String(error) }],
        isError: true,
      });
    }
  }

  return rpcError(id, -32601, `Method not found: ${method}`);
}

const mcpPost = httpActionGeneric(async (ctx, request) => {
  let apiKey: string;
  try {
    apiKey = apiKeyFrom(request);
  } catch (error: any) {
    return json(rpcError(null, -32001, error.message), 401);
  }

  let payload: any;
  try {
    payload = await request.json();
  } catch {
    return json(rpcError(null, -32700, "Parse error"), 400);
  }

  if (Array.isArray(payload)) {
    if (!payload.length) return json(rpcError(null, -32600, "Invalid Request"), 400);
    const results = (await Promise.all(payload.map((message) => dispatch(ctx, apiKey, message)))).filter(Boolean);
    return results.length ? json(results) : new Response(null, { status: 202, headers: corsHeaders });
  }

  const result = await dispatch(ctx, apiKey, payload);
  return result ? json(result) : new Response(null, { status: 202, headers: corsHeaders });
});

http.route({ path: "/mcp", method: "POST", handler: mcpPost });
http.route({
  path: "/mcp",
  method: "OPTIONS",
  handler: httpActionGeneric(async () => new Response(null, { status: 204, headers: corsHeaders })),
});

export default http;
