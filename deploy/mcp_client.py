#!/usr/bin/env python3
"""Minimal MCP (Streamable HTTP) client used to drive the EasyPanel MCP server.

Only the JSON-RPC surface needed for deployment work: initialize, tools/list and
tools/call. Works with servers that answer either application/json or
text/event-stream, and keeps the Mcp-Session-Id across calls.

Examples:
  python deploy/mcp_client.py --url https://panel.example.com/api/mcp --token "$KEY" list
  python deploy/mcp_client.py --url ... --token ... call search_procedures '{"query":"list projects"}'
  python deploy/mcp_client.py --url ... --token ... search "create app service"
  python deploy/mcp_client.py --url ... --token ... mutate createAppService '{"projectName":"openmontage"}'
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests


class MCPError(RuntimeError):
    pass


class MCPClient:
    def __init__(self, url: str, token: str, timeout: int = 120) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.session_id: str | None = None
        self._id = 0
        self.http = requests.Session()
        self.http.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
        )

    # -- transport ---------------------------------------------------------
    def _post(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        headers = {}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        response = self.http.post(self.url, json=payload, headers=headers, timeout=self.timeout)
        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self.session_id = session_id
        if response.status_code >= 400:
            raise MCPError(f"HTTP {response.status_code}: {response.text[:500]}")
        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            return self._parse_sse(response.text)
        body = response.text.strip()
        return json.loads(body) if body else None

    @staticmethod
    def _parse_sse(text: str) -> dict[str, Any] | None:
        last: dict[str, Any] | None = None
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                last = json.loads(data)
            except json.JSONDecodeError:
                continue
        return last

    # -- JSON-RPC ----------------------------------------------------------
    def request(self, method: str, params: dict[str, Any] | None = None, *, notify: bool = False) -> Any:
        self._id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notify:
            payload["id"] = self._id
        response = self._post(payload)
        if notify:
            return None
        if response is None:
            raise MCPError(f"empty response for {method}")
        if "error" in response:
            raise MCPError(json.dumps(response["error"])[:800])
        return response.get("result")

    def initialize(self) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "openmontage-deploy", "version": "0.1.0"},
            },
        )
        self.request("notifications/initialized", {}, notify=True)
        return result or {}

    def list_tools(self) -> list[dict[str, Any]]:
        return list((self.request("tools/list", {}) or {}).get("tools", []))

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        return self.request("tools/call", {"name": name, "arguments": arguments})


def _print(obj: Any) -> None:
    if isinstance(obj, (dict, list)):
        print(json.dumps(obj, indent=2, ensure_ascii=False))
    else:
        print(obj)


def _content(result: Any) -> Any:
    """Unwrap MCP tool results ({content: [{type: text, text: ...}]}) when present."""
    if isinstance(result, dict) and isinstance(result.get("content"), list):
        texts = [c.get("text", "") for c in result["content"] if c.get("type") == "text"]
        joined = "\n".join(t for t in texts if t)
        if joined:
            try:
                return json.loads(joined)
            except json.JSONDecodeError:
                return joined
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Minimal EasyPanel MCP client")
    parser.add_argument("--url", required=True, help="MCP endpoint, e.g. https://panel/api/mcp")
    parser.add_argument("--token", required=True, help="EasyPanel user API key")
    parser.add_argument("--timeout", type=int, default=120)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="initialize the session and print server capabilities")
    sub.add_parser("list", help="list available MCP tools")

    p_search = sub.add_parser("search", help="call search_procedures")
    p_search.add_argument("query")

    p_call = sub.add_parser("call", help="call any tool with raw JSON arguments")
    p_call.add_argument("tool")
    p_call.add_argument("arguments", nargs="?", default="{}")

    p_query = sub.add_parser("query", help="execute_query")
    p_query.add_argument("arguments", nargs="?", default="{}")

    p_mutate = sub.add_parser("mutate", help="execute_mutation")
    p_mutate.add_argument("arguments", nargs="?", default="{}")

    args = parser.parse_args(argv)

    client = MCPClient(args.url, args.token, timeout=args.timeout)
    init = client.initialize()

    if args.command == "init":
        _print(init)
        return 0
    if args.command == "list":
        _print(client.list_tools())
        return 0
    if args.command == "search":
        _print(_content(client.call("search_procedures", {"query": args.query})))
        return 0
    if args.command == "call":
        _print(_content(client.call(args.tool, json.loads(args.arguments))))
        return 0
    if args.command == "query":
        _print(_content(client.call("execute_query", json.loads(args.arguments))))
        return 0
    if args.command == "mutate":
        _print(_content(client.call("execute_mutation", json.loads(args.arguments))))
        return 0
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MCPError as exc:
        print(f"mcp error: {exc}", file=sys.stderr)
        raise SystemExit(1)
