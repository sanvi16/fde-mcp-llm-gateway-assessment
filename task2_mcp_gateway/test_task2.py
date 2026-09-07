import json

from task2_mcp_gateway.gateway import authorize_payload, extract_role


def body(response):
    return json.loads(response.body)


def test_bearer_role_extraction():
    assert extract_role("Bearer admin-secret-token") == "admin"
    assert extract_role("Bearer viewer-secret-token") == "viewer"
    assert extract_role("Basic abc") is None
    assert extract_role(None) is None


def test_tools_list_allowed_for_viewer():
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    assert authorize_payload(payload, "viewer") is None


def test_viewer_blocked_from_admin_tool():
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "admin_reset_key", "arguments": {}},
    }
    response = authorize_payload(payload, "viewer")
    assert response is not None
    parsed = body(response)
    assert parsed["error"]["code"] == -32001
    assert parsed["id"] == 2


def test_admin_allowed_admin_tool():
    payload = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "admin_reset_key", "arguments": {}},
    }
    assert authorize_payload(payload, "admin") is None


def test_viewer_allowed_non_admin_tool():
    payload = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "get_customer", "arguments": {}},
    }
    assert authorize_payload(payload, "viewer") is None


def test_missing_auth_rejected():
    payload = {"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}}
    response = authorize_payload(payload, None)
    assert response is not None
    assert body(response)["error"]["code"] == -32000
