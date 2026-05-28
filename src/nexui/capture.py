from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from nexui.io import NexUIError


@dataclass
class CaptureOptions:
    url: str
    snapshot_dir: Path
    browser: str = "chromium"
    wait_until: str = "load"
    delay_ms: int = 0
    timeout_ms: int = 30000
    viewport_width: int = 1440
    viewport_height: int = 900
    locale: str = "en-US"
    http_headers: dict[str, str] | None = None
    headed: bool = False


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _playwright_entrypoint() -> Path:
    return _repo_root() / "tools" / "capture-snapshot.mjs"


def _assert_capture_dependencies() -> None:
    repo_root = _repo_root()
    package_json = repo_root / "package.json"
    entrypoint = _playwright_entrypoint()
    playwright_module = repo_root / "node_modules" / "playwright"

    if not package_json.exists() or not entrypoint.exists():
        raise NexUIError("Capture tooling is not present in the repository.")
    if not playwright_module.exists():
        raise NexUIError(
            "Playwright is not installed. Run `npm install` and `npm run browsers:install` from the repo root."
        )


def run_capture(options: CaptureOptions) -> dict:
    _assert_capture_dependencies()
    args = [
        "node",
        str(_playwright_entrypoint()),
        "--url",
        options.url,
        "--snapshot-dir",
        str(options.snapshot_dir),
        "--browser",
        options.browser,
        "--wait-until",
        options.wait_until,
        "--delay-ms",
        str(options.delay_ms),
        "--timeout-ms",
        str(options.timeout_ms),
        "--viewport-width",
        str(options.viewport_width),
        "--viewport-height",
        str(options.viewport_height),
        "--locale",
        options.locale,
    ]
    if options.headed:
        args.append("--headed")
    for header_name, header_value in (options.http_headers or {}).items():
        args.extend(["--http-header", f"{header_name}={header_value}"])

    result = subprocess.run(
        args,
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise NexUIError(f"Capture failed: {stderr}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise NexUIError("Capture completed but did not return valid JSON output.") from exc
