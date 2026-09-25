"""Local checks for the Anvil adapter without an Anvil account or E2B calls."""
import importlib
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MemoryTable:
    def __init__(self):
        self.rows = []

    def get(self, **values):
        return next((row for row in self.rows if all(row.get(k) == v for k, v in values.items())), None)

    def add_row(self, **values):
        self.rows.append(values)
        return values


class Response:
    def __init__(self, status=200, body="", headers=None):
        self.status = status
        self.body = body
        self.headers = headers or {}


class Request:
    def __init__(self, method="POST", key=None, data=None):
        self.method = method
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}
        self.query_params = {}
        self.body = types.SimpleNamespace(get_bytes=lambda: json.dumps(data).encode()) if data else None


server = types.ModuleType("anvil.server")
server.HttpResponse = Response
server.http_endpoint = lambda *args, **kwargs: lambda fn: fn
server.request = None
table = MemoryTable()
tables = types.ModuleType("anvil.tables")
tables.app_tables = types.SimpleNamespace(sandbox_state=table)
anvil = types.ModuleType("anvil")
anvil.server = server
anvil.tables = tables
sys.modules.update({"anvil": anvil, "anvil.server": server, "anvil.tables": tables})
spec = importlib.util.spec_from_file_location(
    "E2BSandboxMCP", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
)
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
state = importlib.import_module("E2BSandboxMCP.StateStore")
endpoint = importlib.import_module("E2BSandboxMCP.McpEndpoint")


class AnvilAdapterTests(unittest.TestCase):
    def setUp(self):
        table.rows.clear()

    def test_last_sandbox_is_isolated_by_hashed_key(self):
        state.set_last_sandbox_id("e2b_first", "sandbox-1")
        self.assertEqual(state.get_last_sandbox_id("e2b_first"), "sandbox-1")
        self.assertIsNone(state.get_last_sandbox_id("e2b_second"))
        state.set_last_sandbox_id("e2b_first", "sandbox-2")
        self.assertEqual(len(table.rows), 1)
        self.assertEqual(state.get_last_sandbox_id("e2b_first"), "sandbox-2")
        self.assertNotIn("e2b_first", repr(table.rows))

    def test_non_post_and_missing_credential(self):
        self.assertEqual(endpoint.handle_request(Request("OPTIONS")).status, 204)
        self.assertEqual(endpoint.handle_request(Request("GET")).status, 405)
        response = endpoint.handle_request(Request())
        self.assertEqual(response.status, 401)
        self.assertEqual(response.body["error"]["code"], -32001)

    def test_query_credential_and_tool_list(self):
        request = Request(data={"jsonrpc": "2.0", "id": 8, "method": "tools/list", "params": {}})
        request.query_params = {"e2b_api_key": "e2b_test"}
        response = endpoint.handle_request(request)
        self.assertEqual(response.status, 200)
        names = {tool["name"] for tool in json.loads(response.body)["result"]["tools"]}
        self.assertIn("exec", names)
        self.assertIn("files_read", names)

    def test_mcp_initialize_through_anvil_adapter(self):
        request = Request(key="e2b_test", data={
            "jsonrpc": "2.0", "id": 7, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "local-test", "version": "1"}},
        })
        response = endpoint.handle_request(request)
        self.assertEqual(response.status, 200)
        message = json.loads(response.body)
        self.assertEqual(message["id"], 7)
        self.assertIn("result", message)
        self.assertEqual(message["result"]["serverInfo"]["name"], "e2b-sandbox-mcp")


if __name__ == "__main__":
    unittest.main()
