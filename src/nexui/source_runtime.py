from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from urllib.request import Request, urlopen

from nexui.authoring import default_sources_root, load_source_manifest
from nexui.io import NexUIError


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class SourceRuntimeContext:
    source_id: str
    source_root: Path
    manifest_path: Path
    manifest: dict
    reseed_command: str
    reset_strategy: str
    healthcheck_url: str
    readiness_command: str


def resolve_source_runtime(source: str | Path) -> SourceRuntimeContext:
    candidate = Path(source)
    if candidate.exists():
        manifest_path, manifest = load_source_manifest(candidate)
    else:
        manifest_path, manifest = load_source_manifest(default_sources_root() / str(source))

    source_root = manifest_path.parent
    runtime = manifest.get("runtime") or {}
    return SourceRuntimeContext(
        source_id=str(manifest["site_id"]),
        source_root=source_root,
        manifest_path=manifest_path,
        manifest=manifest,
        reseed_command=str(runtime.get("reseed_command") or "").strip(),
        reset_strategy=str(manifest.get("reset_strategy") or "").strip(),
        healthcheck_url=str(runtime.get("healthcheck_url") or "").strip(),
        readiness_command=str(runtime.get("readiness_command") or "").strip(),
    )


def _wait_for_healthcheck(url: str, *, timeout_seconds: int = 120, poll_seconds: float = 2.0) -> None:
    deadline = monotonic() + timeout_seconds
    last_error = "healthcheck did not respond"
    while monotonic() < deadline:
        try:
            request = Request(url, method="GET")
            with urlopen(request, timeout=10) as response:
                status = getattr(response, "status", None) or response.getcode()
            if 200 <= int(status) < 400:
                return
            last_error = f"healthcheck responded with status {status}"
        except Exception as exc:  # pragma: no cover - network/container startup dependent
            last_error = str(exc)
        sleep(poll_seconds)
    raise NexUIError(f"Healthcheck did not become ready for {url}: {last_error}")


def reseed_source(source: str | Path) -> SourceRuntimeContext:
    context = resolve_source_runtime(source)
    if context.reset_strategy not in {"reseed_command", "docker_reset"}:
        raise NexUIError(
            f"Source {context.source_id!r} is not reseedable (reset_strategy={context.reset_strategy!r})."
        )
    if not context.reseed_command:
        raise NexUIError(f"Source {context.source_id!r} does not define runtime.reseed_command.")

    result = subprocess.run(
        context.reseed_command,
        cwd=_repo_root(),
        shell=True,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or "source reseed command failed"
        raise NexUIError(f"Reseed failed for {context.source_id}: {detail}")
    if context.healthcheck_url:
        _wait_for_healthcheck(context.healthcheck_url)
    if context.readiness_command:
        readiness = subprocess.run(
            context.readiness_command,
            cwd=_repo_root(),
            shell=True,
            text=True,
            capture_output=True,
            check=False,
        )
        if readiness.returncode != 0:
            stderr = readiness.stderr.strip()
            stdout = readiness.stdout.strip()
            detail = stderr or stdout or "source readiness command failed"
            raise NexUIError(f"Readiness check failed for {context.source_id}: {detail}")
    return context
