#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


RISKY_PREFIXES = (
    "downloads/",
    "logs/",
    "external/",
    "examples/tasks/",
)


def run_git(root: Path, args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True)


def human_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{size}B"


def tracked_files(root: Path) -> list[tuple[int, str]]:
    files = run_git(root, ["ls-files"]).splitlines()
    rows: list[tuple[int, str]] = []
    for rel in files:
        path = root / rel
        if path.is_file():
            rows.append((path.stat().st_size, rel))
    return sorted(rows, reverse=True)


def top_history_blobs(root: Path, top_n: int) -> list[tuple[int, str, str]]:
    command = (
        "git rev-list --objects --all | "
        "git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)'"
    )
    output = subprocess.check_output(["bash", "-lc", command], cwd=root, text=True)
    rows: list[tuple[int, str, str]] = []
    for line in output.splitlines():
        parts = line.split(" ", 3)
        if len(parts) < 4 or parts[0] != "blob":
            continue
        _, oid, size_text, path = parts
        rows.append((int(size_text), oid, path))
    rows.sort(reverse=True)
    return rows[:top_n]


def classify_path(rel: str) -> str:
    if rel.startswith("downloads/"):
        return "stop_tracking_fetch_on_demand"
    if rel.startswith("logs/"):
        return "stop_tracking_runtime_output"
    if rel.startswith("external/"):
        return "nested_repo_only"
    if rel.startswith("examples/tasks/"):
        return "keep_in_git"
    return "review"


def print_threshold_section(rows: list[tuple[int, str]], threshold_mb: int) -> None:
    threshold = threshold_mb * 1024 * 1024
    print(f"## tracked files > {threshold_mb} MB")
    found = False
    for size, rel in rows:
        if size > threshold:
            print(f"- {human_size(size)}\t{rel}")
            found = True
    if not found:
        print("- none")
    print()


def print_risky_prefix_summary(rows: list[tuple[int, str]]) -> None:
    grouped: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for size, rel in rows:
        for prefix in RISKY_PREFIXES:
            if rel.startswith(prefix):
                grouped[prefix].append((size, rel))
                break

    print("## tracked files under risky prefixes")
    for prefix in RISKY_PREFIXES:
        files = grouped.get(prefix, [])
        total = sum(size for size, _ in files)
        print(f"- {prefix}: {len(files)} files, {human_size(total)} tracked")
    print()


def print_top_risky_files(rows: list[tuple[int, str]], limit: int) -> None:
    risky = [(size, rel) for size, rel in rows if rel.startswith(RISKY_PREFIXES)]
    print(f"## top {limit} tracked files under risky prefixes")
    for size, rel in risky[:limit]:
        print(f"- {human_size(size)}\t{rel}\t[{classify_path(rel)}]")
    if not risky:
        print("- none")
    print()


def print_history_section(rows: list[tuple[int, str, str]]) -> None:
    print("## largest historical git blobs")
    for size, oid, rel in rows:
        print(f"- {human_size(size)}\t{oid}\t{rel}\t[{classify_path(rel)}]")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit large tracked files and large historical blobs in the repository."
    )
    parser.add_argument(
        "--repo-root",
        default=Path(__file__).resolve().parent.parent,
        type=Path,
        help="Path to the repository root.",
    )
    parser.add_argument(
        "--threshold-mb",
        action="append",
        type=int,
        default=[10, 50],
        help="Tracked-file size thresholds in MB. May be passed multiple times.",
    )
    parser.add_argument(
        "--top-history",
        type=int,
        default=20,
        help="Number of historical blobs to print.",
    )
    parser.add_argument(
        "--top-risky-tracked",
        type=int,
        default=25,
        help="Number of tracked files under risky prefixes to print.",
    )
    args = parser.parse_args()

    root = args.repo_root.resolve()
    if not (root / ".git").exists():
        print(f"Not a git repository root: {root}", file=sys.stderr)
        return 2

    tracked = tracked_files(root)
    print(f"# Repository asset audit\n")
    print(f"repo_root: {root}")
    print()
    for threshold in sorted(set(args.threshold_mb)):
        print_threshold_section(tracked, threshold)
    print_risky_prefix_summary(tracked)
    print_top_risky_files(tracked, args.top_risky_tracked)
    print_history_section(top_history_blobs(root, args.top_history))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
