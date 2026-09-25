import assert from "node:assert/strict";
import test from "node:test";
import { allTools, tools } from "../convex/mcp.ts";

test("get_sandbox_id is the discovery tool", () => {
  const discovery = tools.find((tool) => tool.name === "get_sandbox_id");
  assert.ok(discovery);
  assert.match(discovery.description, /MUST be called before any other tool/);
  assert.deepEqual(discovery.inputSchema, {
    type: "object",
    properties: {},
    additionalProperties: false,
  });
});

test("every non-discovery tool requires sandbox_id", () => {
  for (const tool of allTools) {
    if (tool.name === "get_sandbox_id") continue;
    assert.ok("required" in tool.inputSchema && tool.inputSchema.required.includes("sandbox_id"), `${tool.name} must require sandbox_id`);
    assert.match(tool.description, /call get_sandbox_id first/i, `${tool.name} must tell the model to discover the sandbox first`);
  }
});
