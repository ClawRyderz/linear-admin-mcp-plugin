#!/usr/bin/env python3

"""Install the Linear Admin MCP bundle and render an absolute stdio config."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from render_mcp_config import main as render_mcp_config_main  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the Linear Admin MCP server into a local directory."
    )
    parser.add_argument(
        "--bundle-root",
        "--plugin-root",
        dest="bundle_root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Source bundle root directory.",
    )
    parser.add_argument(
        "--destination",
        required=True,
        help="Destination directory for the installed server bundle.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing destination directory.",
    )
    args = parser.parse_args(argv)

    bundle_root = Path(args.bundle_root).expanduser().resolve()
    raw_destination = Path(args.destination).expanduser()
    destination = raw_destination if raw_destination.is_absolute() else raw_destination.resolve()
    if not bundle_root.is_dir():
        raise ValueError(f"Bundle root does not exist: {bundle_root}")
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
        bundle_root,
        destination,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc"),
    )
    render_mcp_config_main(
        [
            "--bundle-root",
            str(destination),
            "--output",
            str(destination / ".mcp.json"),
        ]
    )
    print(str(destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
