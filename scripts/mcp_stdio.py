#!/usr/bin/env python3

"""Small, dependency-free stdio transport for MCP JSON-RPC messages."""

from __future__ import annotations

import json
import sys
from typing import Any, Literal


FramingMode = Literal["jsonl", "content-length"]
_framing_mode: FramingMode = "jsonl"


def read_message() -> dict[str, Any] | None:
    """Read standard JSONL MCP, with legacy Content-Length compatibility."""

    global _framing_mode

    first_line = sys.stdin.buffer.readline()
    while first_line in (b"\n", b"\r\n"):
        first_line = sys.stdin.buffer.readline()
    if not first_line:
        return None

    stripped = first_line.strip()
    if stripped.startswith(b"{"):
        _framing_mode = "jsonl"
        return _decode_object(stripped)

    _framing_mode = "content-length"
    headers = _read_headers(first_line)
    content_length = headers.get("content-length")
    if content_length is None:
        raise ValueError("Missing Content-Length header.")
    try:
        expected_length = int(content_length)
    except ValueError as exc:
        raise ValueError("Invalid Content-Length header.") from exc
    payload = sys.stdin.buffer.read(expected_length)
    if len(payload) != expected_length:
        raise ValueError("Incomplete JSON-RPC payload.")
    return _decode_object(payload)


def write_message(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if _framing_mode == "content-length":
        sys.stdout.buffer.write(f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii"))
        sys.stdout.buffer.write(encoded)
    else:
        sys.stdout.buffer.write(encoded + b"\n")
    sys.stdout.buffer.flush()


def _read_headers(first_line: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    line = first_line
    while line not in (b"\n", b"\r\n"):
        decoded = line.decode("utf-8").strip()
        if ":" not in decoded:
            raise ValueError("Invalid Content-Length framing header.")
        key, value = decoded.split(":", 1)
        headers[key.strip().lower()] = value.strip()
        line = sys.stdin.buffer.readline()
        if not line:
            raise ValueError("Incomplete Content-Length framing headers.")
    return headers


def _decode_object(payload: bytes) -> dict[str, Any]:
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("MCP JSON-RPC messages must be JSON objects.")
    return decoded
