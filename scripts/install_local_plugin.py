#!/usr/bin/env python3

"""Backward-compatible entrypoint for the original Codex-oriented installer name."""

from install import main


if __name__ == "__main__":
    raise SystemExit(main())
