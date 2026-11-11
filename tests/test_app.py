import json

import pytest

from app import app


@pytest.fixture
def client():
    return app.test_client()


def rpc(client, method, params=None, msg_id=1):
    body = {"jsonrpc": "2.0", "method": method}
    if msg_id is not None:
        body["id"] = msg_id
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_initialize_returns_session_header(client):
    resp = rpc(client, "initialize", {"protocolVersion": "2025-06-18"})
    assert resp.status_code == 200
    assert "Mcp-Session-Id" in resp.headers
    result = resp.get_json()["result"]
    assert result["serverInfo"]["name"] == "order-status-mcp"
    assert result["protocolVersion"] == "2025-06-18"


def test_tools_list_includes_get_order_status(client):
    resp = rpc(client, "tools/list")
    names = [t["name"] for t in resp.get_json()["result"]["tools"]]
    assert "get_order_status" in names
    assert "list_orders" in names


def test_tools_call_known_order(client):
    resp = rpc(client, "tools/call", {"name": "get_order_status", "arguments": {"order_id": "ORD-1002"}})
    result = resp.get_json()["result"]
    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["order_id"] == "ORD-1002"
    assert data["status"] == "Shipped"


def test_tools_call_unknown_order_is_deterministic(client):
    resp1 = rpc(client, "tools/call", {"name": "get_order_status", "arguments": {"order_id": "ORD-9999"}})
    resp2 = rpc(client, "tools/call", {"name": "get_order_status", "arguments": {"order_id": "ORD-9999"}})
    data1 = json.loads(resp1.get_json()["result"]["content"][0]["text"])
    data2 = json.loads(resp2.get_json()["result"]["content"][0]["text"])
    assert data1["status"] == data2["status"]


def test_tools_call_missing_order_id(client):
    resp = rpc(client, "tools/call", {"name": "get_order_status", "arguments": {}})
    result = resp.get_json()["result"]
    assert result["isError"] is True


def test_notification_gets_no_body(client):
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp.status_code == 202
    assert resp.data == b""


def test_unknown_method(client):
    resp = rpc(client, "nonexistent/method")
    assert resp.get_json()["error"]["code"] == -32601
