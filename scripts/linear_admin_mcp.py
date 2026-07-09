#!/usr/bin/env python3

"""Local-only MCP server for Linear admin GraphQL and project setup work."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from linear_plugin_runtime import (  # noqa: E402
    SCHEMA_FIND_QUERY,
    SCHEMA_TYPE_QUERY,
    default_config_path as default_provider_config_path,
    filter_schema_find_payload,
    graphql_request,
    resolve_linear_access_token,
)
from linear_project_setup import (  # noqa: E402
    fetch_setup_snapshot,
    load_project_setup_config,
    plan_project_setup,
    apply_plan,
    serialize_planned_mutation,
    summarize_plan,
)


SERVER_NAME = "linear-admin-local"
SERVER_VERSION = "1.0.0"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"
TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "name": "linear_schema_find",
        "description": "Search the live Linear GraphQL schema for matching types and root fields.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "contains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1
                },
                "provider_config_file": {"type": "string"}
            },
            "required": ["contains"],
            "additionalProperties": False
        }
    },
    {
        "name": "linear_schema_type",
        "description": "Inspect one named type from the live Linear GraphQL schema.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "provider_config_file": {"type": "string"}
            },
            "required": ["name"],
            "additionalProperties": False
        }
    },
    {
        "name": "linear_graphql_query",
        "description": "Run a raw GraphQL query with the local Linear app token path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "variables": {"type": "object"},
                "provider_config_file": {"type": "string"}
            },
            "required": ["query"],
            "additionalProperties": False
        }
    },
    {
        "name": "linear_project_setup_plan",
        "description": "Preview shared-view and template mutations for a project config.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_config_file": {"type": "string"},
                "provider_config_file": {"type": "string"}
            },
            "required": ["project_config_file"],
            "additionalProperties": False
        }
    },
    {
        "name": "linear_project_setup_apply",
        "description": "Apply shared-view and template mutations for a project config.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_config_file": {"type": "string"},
                "provider_config_file": {"type": "string"}
            },
            "required": ["project_config_file"],
            "additionalProperties": False
        }
    }
)


def read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\n", b"\r\n"):
            break
        decoded = line.decode("utf-8").strip()
        if ":" not in decoded:
            continue
        key, value = decoded.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    content_length = headers.get("content-length")
    if content_length is None:
        raise ValueError("Missing Content-Length header.")
    payload = sys.stdin.buffer.read(int(content_length))
    return json.loads(payload.decode("utf-8"))


def write_message(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def write_result(request_id: Any, result: dict[str, Any]) -> None:
    write_message({"jsonrpc": "2.0", "id": request_id, "result": result})


def write_error(request_id: Any, code: int, message: str) -> None:
    write_message({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def tool_text(payload: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2, sort_keys=True)}]}


def resolve_provider_config(arguments: dict[str, Any]) -> Path:
    value = arguments.get("provider_config_file")
    if value is None:
        return default_provider_config_path()
    if not isinstance(value, str) or not value.strip():
        raise ValueError("provider_config_file must be a non-empty string when present.")
    return Path(value).expanduser()


def resolve_project_config(arguments: dict[str, Any]) -> Path:
    value = arguments.get("project_config_file")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("project_config_file is required and must be a non-empty string.")
    return Path(value).expanduser()


def handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    provider_config = resolve_provider_config(arguments)
    access_token = resolve_linear_access_token(config_file=provider_config)

    if name == "linear_schema_find":
        contains = arguments.get("contains")
        if not isinstance(contains, list) or not contains or not all(isinstance(item, str) for item in contains):
            raise ValueError("contains must be a non-empty array of strings.")
        payload = graphql_request(
            access_token=access_token,
            query=SCHEMA_FIND_QUERY,
            variables={},
        )
        return tool_text(filter_schema_find_payload(payload=payload, needles=contains))

    if name == "linear_schema_type":
        type_name = arguments.get("name")
        if not isinstance(type_name, str) or not type_name.strip():
            raise ValueError("name must be a non-empty string.")
        payload = graphql_request(
            access_token=access_token,
            query=SCHEMA_TYPE_QUERY,
            variables={"name": type_name},
        )
        return tool_text(payload)

    if name == "linear_graphql_query":
        query = arguments.get("query")
        variables = arguments.get("variables", {})
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string.")
        if not isinstance(variables, dict):
            raise ValueError("variables must be an object when present.")
        payload = graphql_request(
            access_token=access_token,
            query=query,
            variables=variables,
        )
        return tool_text(payload)

    if name in {"linear_project_setup_plan", "linear_project_setup_apply"}:
        project_config_path = resolve_project_config(arguments)
        project_config = load_project_setup_config(project_config_path)
        snapshot = fetch_setup_snapshot(
            access_token=access_token,
            project_config=project_config,
            timeout_seconds=30.0,
        )
        plan = plan_project_setup(snapshot, project_config)
        if name == "linear_project_setup_plan":
            return tool_text(
                {
                    "mode": "plan",
                    "summary": summarize_plan(plan),
                    "mutations": [serialize_planned_mutation(item) for item in plan],
                }
            )
        results = apply_plan(access_token=access_token, plan=plan, timeout_seconds=30.0)
        return tool_text(
            {
                "mode": "apply",
                "summary": summarize_plan(plan),
                "results": results,
            }
        )

    raise ValueError(f"Unknown tool {name!r}.")


def handle_request(message: dict[str, Any]) -> None:
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
        write_result(
            request_id,
            {
                "protocolVersion": DEFAULT_PROTOCOL_VERSION,
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "capabilities": {"tools": {}},
            },
        )
        return

    if method == "notifications/initialized":
        return

    if method == "tools/list":
        write_result(request_id, {"tools": list(TOOL_SCHEMAS)})
        return

    if method == "tools/call":
        params = message.get("params")
        if not isinstance(params, dict):
            raise ValueError("tools/call requires params.")
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError("tools/call requires a tool name.")
        if not isinstance(arguments, dict):
            raise ValueError("tools/call arguments must be an object.")
        write_result(request_id, handle_tool_call(tool_name, arguments))
        return

    if request_id is not None:
        write_error(request_id, -32601, f"Method not found: {method}")


def main() -> int:
    while True:
        message = read_message()
        if message is None:
            return 0
        request_id = message.get("id")
        try:
            handle_request(message)
        except Exception as exc:  # noqa: BLE001
            if request_id is not None:
                write_error(request_id, -32000, str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
