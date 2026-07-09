#!/usr/bin/env python3

"""Render an absolute-path .mcp.json for the current plugin install location."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rewrite .mcp.json with absolute paths for the current plugin location."
    )
    parser.add_argument(
        "--plugin-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Root directory of the plugin install.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for the rendered .mcp.json. Defaults to <plugin-root>/.mcp.json.",
    )
    args = parser.parse_args(argv)

    raw_plugin_root = Path(args.plugin_root).expanduser()
    plugin_root = raw_plugin_root if raw_plugin_root.is_absolute() else raw_plugin_root.resolve()
    if args.output:
        raw_output_path = Path(args.output).expanduser()
        output_path = raw_output_path if raw_output_path.is_absolute() else raw_output_path.resolve()
    else:
        output_path = plugin_root / ".mcp.json"
    payload = {
        "mcpServers": {
            "linear-admin-local": {
                "command": "python3",
                "args": [str(plugin_root / "scripts" / "linear_admin_mcp.py")],
                "env": {
                    "PYTHONUNBUFFERED": "1",
                    "LINEAR_ADMIN_PLUGIN_CONFIG_FILE": str(plugin_root / "config" / "provider_refs.json"),
                },
            }
        }
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
