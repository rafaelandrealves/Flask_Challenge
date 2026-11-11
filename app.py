import hashlib
import json
import os
import random
import uuid
from datetime import date, timedelta

from flask import Flask, Response, jsonify, request

app = Flask(__name__)

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = {"2025-06-18", "2025-03-26", "2024-11-05"}
SERVER_INFO = {"name": "order-status-mcp", "version": "1.0.0"}

# Optional shared-secret auth. Leave MCP_API_KEY unset to run with no auth
# (simplest option for Salesforce's "No Authentication" setting).
API_KEY = os.environ.get("MCP_API_KEY")

sessions = {}

MOCK_ORDERS = {
    "ORD-1001": {
        "status": "Delivered",
        "items": [{"sku": "WDG-100", "name": "Wireless Mouse", "qty": 1}],
        "carrier": "UPS",
        "tracking_number": "1Z999AA10123456784",
        "estimated_delivery": "2026-11-05",
    },
    "ORD-1002": {
        "status": "Shipped",
        "items": [{"sku": "WDG-200", "name": "Mechanical Keyboard", "qty": 1}],
        "carrier": "FedEx",
        "tracking_number": "771234567890",
        "estimated_delivery": "2026-11-14",
    },
    "ORD-1003": {
        "status": "Processing",
        "items": [
            {"sku": "WDG-300", "name": "USB-C Hub", "qty": 2},
            {"sku": "WDG-301", "name": "Laptop Stand", "qty": 1},
        ],
        "carrier": None,
        "tracking_number": None,
        "estimated_delivery": "2026-11-18",
    },
    "ORD-1004": {
        "status": "Cancelled",
        "items": [{"sku": "WDG-400", "name": "Desk Lamp", "qty": 1}],
        "carrier": None,
        "tracking_number": None,
        "estimated_delivery": None,
    },
}

STATUS_CYCLE = ["Processing", "Shipped", "Out for Delivery", "Delivered"]


def mock_order_for(order_id: str) -> dict:
    """Return the seeded mock order, or a deterministic fake one for any other ID."""
    if order_id in MOCK_ORDERS:
        return {"order_id": order_id, **MOCK_ORDERS[order_id]}

    digest = hashlib.sha256(order_id.encode("utf-8")).hexdigest()
    rng = random.Random(int(digest[:8], 16))
    status = rng.choice(STATUS_CYCLE)
    eta = date.today() + timedelta(days=rng.randint(1, 10))
    return {
        "order_id": order_id,
        "status": status,
        "items": [{"sku": "GEN-001", "name": "Generic Item", "qty": rng.randint(1, 3)}],
        "carrier": rng.choice(["UPS", "FedEx", "USPS", "DHL"]) if status != "Processing" else None,
        "tracking_number": f"{rng.getrandbits(32):010d}" if status != "Processing" else None,
        "estimated_delivery": eta.isoformat() if status != "Delivered" else None,
        "note": "Unrecognized order ID; this is a deterministic mock status for demo purposes.",
    }


TOOLS = [
    {
        "name": "get_order_status",
        "description": (
            "Look up the current status of an order by its order ID. "
            "Returns status, line items, carrier, tracking number and estimated delivery date."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The order ID to look up, e.g. 'ORD-1001'",
                }
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "list_orders",
        "description": "List the mock order IDs seeded on this demo server.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def jsonrpc_result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def jsonrpc_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def check_auth() -> bool:
    if not API_KEY:
        return True
    return request.headers.get("Authorization") == f"Bearer {API_KEY}"


def cors_headers() -> dict:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, Mcp-Session-Id, MCP-Protocol-Version",
    }


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/mcp", methods=["GET", "DELETE", "OPTIONS"])
def mcp_non_post():
    if request.method == "OPTIONS":
        return Response(status=204, headers=cors_headers())
    if request.method == "DELETE":
        sessions.pop(request.headers.get("Mcp-Session-Id"), None)
        return Response(status=204, headers=cors_headers())
    # This mock server never pushes server-initiated messages, so it does
    # not support opening an SSE stream via GET.
    return Response(status=405, headers=cors_headers())


@app.route("/mcp", methods=["POST"])
def mcp_post():
    if not check_auth():
        return jsonify({"error": "unauthorized"}), 401, cors_headers()

    body = request.get_json(silent=True)
    if body is None:
        return jsonify(jsonrpc_error(None, -32700, "Parse error: invalid JSON")), 400, cors_headers()

    if isinstance(body, list):
        responses = [r for r in (handle_message(msg)[0] for msg in body) if r is not None]
        if not responses:
            return Response(status=202, headers=cors_headers())
        return jsonify(responses), 200, cors_headers()

    response, extra_headers = handle_message(body)
    headers = {**cors_headers(), **extra_headers}
    if response is None:
        return Response(status=202, headers=headers)
    return jsonify(response), 200, headers


def handle_message(msg: dict):
    req_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}
    is_notification = "id" not in msg
    headers: dict = {}

    if method == "initialize":
        client_version = params.get("protocolVersion")
        version = client_version if client_version in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        session_id = uuid.uuid4().hex
        sessions[session_id] = {"protocolVersion": version}
        headers["Mcp-Session-Id"] = session_id
        headers["MCP-Protocol-Version"] = version
        result = {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        }
        return jsonrpc_result(req_id, result), headers

    if method == "notifications/initialized":
        return None, headers

    if method == "ping":
        return jsonrpc_result(req_id, {}), headers

    if method == "tools/list":
        return jsonrpc_result(req_id, {"tools": TOOLS}), headers

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}

        if name == "get_order_status":
            order_id = arguments.get("order_id")
            if not order_id:
                return jsonrpc_result(req_id, {
                    "isError": True,
                    "content": [{"type": "text", "text": "Missing required argument: order_id"}],
                }), headers
            data = mock_order_for(str(order_id))
            return jsonrpc_result(req_id, {
                "isError": False,
                "content": [{"type": "text", "text": json.dumps(data, indent=2)}],
            }), headers

        if name == "list_orders":
            return jsonrpc_result(req_id, {
                "isError": False,
                "content": [{"type": "text", "text": json.dumps(sorted(MOCK_ORDERS.keys()))}],
            }), headers

        return jsonrpc_error(req_id, -32602, f"Unknown tool: {name}"), headers

    if is_notification:
        return None, headers

    return jsonrpc_error(req_id, -32601, f"Method not found: {method}"), headers


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
