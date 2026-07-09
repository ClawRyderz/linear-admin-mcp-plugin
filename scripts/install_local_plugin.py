#!/usr/bin/env python3

"""Copy the Linear Admin plugin to a local install path and render absolute MCP config."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from render_mcp_config import main as render_mcp_config_main  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the Linear Admin plugin into a local Codex plugin directory."
    )
    parser.add_argument(
        "--plugin-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Source plugin root directory.",
    )
    parser.add_argument(
        "--destination",
        required=True,
        help="Destination directory for the installed plugin.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing destination directory.",
    )
    args = parser.parse_args(argv)

    plugin_root = Path(args.plugin_root).expanduser().resolve()
    raw_destination = Path(args.destination).expanduser()
    destination = raw_destination if raw_destination.is_absolute() else raw_destination.resolve()
    if not plugin_root.is_dir():
        raise ValueError(f"Plugin root does not exist: {plugin_root}")
    if destination.exists():
        if not args.force:
            raise ValueError(
                f"Destination already exists: {destination}. Use --force to replace it."
            )
        if destination.is_symlink() or destination.is_file():
            destination.unlink()
        else:
            shutil.rmtree(destination)

    shutil.copytree(
        plugin_root,
        destination,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc"),
    )
    render_mcp_config_main(
        [
            "--plugin-root",
            str(destination),
            "--output",
            str(destination / ".mcp.json"),
        ]
    )
    print(str(destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
