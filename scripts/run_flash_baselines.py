#!/usr/bin/env python3
from __future__ import annotations

import sys

from nexui.flash_baseline_runner import EXIT_CONFIG, main
from nexui.io import NexUIError


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except NexUIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
