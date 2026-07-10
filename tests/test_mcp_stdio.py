from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


SERVER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "linear_admin_mcp.py"


def test_server_uses_standard_jsonl_stdio_mcp() -> None:
    process = subprocess.Popen(
        [sys.executable, str(SERVER_PATH)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    process.stdin.write(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
            }
        )
        + "\n"
    )
    process.stdin.flush()
    initialized = json.loads(process.stdout.readline())

    process.stdin.write(
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        + "\n"
    )
    process.stdin.flush()
    tools = json.loads(process.stdout.readline())

    process.stdin.close()
    assert process.wait(timeout=5) == 0
    assert initialized["result"]["protocolVersion"] == "2025-06-18"
    assert initialized["result"]["serverInfo"]["name"] == "linear-admin-local"
    assert len(tools["result"]["tools"]) == 5
    annotations = {tool["name"]: tool["annotations"] for tool in tools["result"]["tools"]}
    assert annotations["linear_schema_find"]["readOnlyHint"] is True
    assert annotations["linear_project_setup_apply"]["destructiveHint"] is True


def test_server_preserves_legacy_content_length_framing() -> None:
    process = subprocess.Popen(
        [sys.executable, str(SERVER_PATH)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    request = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
    ).encode("utf-8")
    process.stdin.write(f"Content-Length: {len(request)}\r\n\r\n".encode("ascii") + request)
    process.stdin.flush()

    header = process.stdout.readline().decode("ascii").strip()
    assert header.startswith("Content-Length: ")
    content_length = int(header.split(":", 1)[1].strip())
    assert process.stdout.readline() in (b"\n", b"\r\n")
    response = json.loads(process.stdout.read(content_length).decode("utf-8"))

    process.stdin.close()
    assert process.wait(timeout=5) == 0
    assert response == {"jsonrpc": "2.0", "id": 1, "result": {}}
