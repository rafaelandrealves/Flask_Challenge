# Flask_Challenge

A mock **MCP (Model Context Protocol) server** for order status, built with Flask. It implements the MCP [Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#streamable-http) so it can be registered as an **External MCP Server** in Salesforce (Agentforce) and called from an agent action.

## What it exposes

A single MCP endpoint at `POST /mcp` implementing the standard JSON-RPC methods (`initialize`, `tools/list`, `tools/call`, `ping`) plus two tools:

| Tool | Arguments | Description |
|---|---|---|
| `get_order_status` | `order_id` (string, required) | Returns status, line items, carrier, tracking number and estimated delivery for an order. Unknown IDs get a deterministic mock status instead of an error, so any order ID "works" for demo purposes. |
| `list_orders` | — | Lists the seeded mock order IDs (`ORD-1001`–`ORD-1004`). |

There's also a plain `GET /health` endpoint for uptime checks.

## Run it locally

```bash
pip install -r requirements.txt
python app.py
```

The server listens on `http://0.0.0.0:5000` (override with `PORT`).

### Quick manual test

```bash
curl -i -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}'
```

```bash
curl -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_order_status","arguments":{"order_id":"ORD-1001"}}}'
```

## Run the tests

```bash
pip install -r requirements.txt pytest
python -m pytest
```

## Optional auth

By default the server requires no authentication (matches Salesforce's "No Authentication" option). To require a bearer token instead, set `MCP_API_KEY` before starting the server; requests must then send `Authorization: Bearer <MCP_API_KEY>`.

## Connecting it to Salesforce's External MCP Server tab

Salesforce needs to reach your server over the public internet via HTTPS, so expose it first:

```bash
# from a separate terminal, with the Flask app already running on :5000
ngrok http 5000
```

Then in Salesforce **Setup → Agentforce → External MCP Servers** (naming may vary by org/release):

1. Click **New External MCP Server**.
2. **Server URL**: `https://<your-ngrok-subdomain>.ngrok-free.app/mcp`
3. **Authentication**: "No Authentication" (or "Custom"/Bearer token with the value of `MCP_API_KEY`, if you set one).
4. Save — Salesforce will call `initialize` and `tools/list` to discover `get_order_status` and `list_orders`.
5. Add the discovered tool(s) to an Agentforce agent action so the agent can answer "what's the status of order ORD-1001?" style questions.

Note: this is a mock/demo server (in-memory, single process, Flask dev server) — fine for testing an Agentforce integration, not for production traffic.
