from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class NexUIError(Exception):
    """Base exception for CLI and runtime errors."""


class RuntimeAgentError(NexUIError):
    """Provider or transport failure that should not be scored as a model failure."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        category: str,
        retryable: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.category = category
        self.retryable = retryable
        self.details = dict(details or {})


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def write_text(path: Path, content: str) -> None:
    _atomic_write_bytes(path, content.encode("utf-8"))


def read_json(path: Path) -> Any:
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise NexUIError(f"Invalid JSON in {path}") from exc


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, indent=2, sort_keys=False) + "\n")


def append_jsonl_atomic(path: Path, payload: dict[str, Any]) -> None:
    existing = read_text(path) if path.exists() else ""
    line = json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n"
    write_text(path, existing + line)


def read_yaml_like(path: Path) -> Any:
    """
    Read a `.yaml` or `.yml` file using JSON-compatible YAML.

    The current repository avoids third-party YAML dependencies, so the runtime
    accepts YAML files that are also valid JSON.
    """

    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise NexUIError(
            f"{path} must be JSON-compatible YAML for the current stdlib-only tooling"
        ) from exc
