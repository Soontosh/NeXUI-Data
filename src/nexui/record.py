from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from nexui.capture import _assert_capture_dependencies, _repo_root
from nexui.io import NexUIError


@dataclass
class RecordOptions:
    recipe: Path
    output_dir: Path
    browser: str = "chromium"
    wait_until: str = "load"
    delay_ms: int = 0
    timeout_ms: int = 30000
    viewport_width: int = 1440
    viewport_height: int = 900
    locale: str = "en-US"
    headed: bool = False
    overwrite: bool = False
    reseed_source_runtime: bool = False


def _record_entrypoint() -> Path:
    return _repo_root() / "tools" / "record-task.mjs"


def run_recording(options: RecordOptions) -> dict:
    _assert_capture_dependencies()
    if not _record_entrypoint().exists():
        raise NexUIError("Recorder tooling is not present in the repository.")
    if options.reseed_source_runtime:
        from nexui.source_runtime import reseed_source

        try:
            recipe = json.loads(options.recipe.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise NexUIError(f"Recording recipe is not valid JSON: {options.recipe}") from exc
        source_surface = str(recipe.get("source_surface") or "").strip()
        if not source_surface:
            raise NexUIError("Recording recipe must define source_surface when --reseed-source is used.")
        reseed_source(source_surface)

    args = [
        "node",
        str(_record_entrypoint()),
        "--recipe",
        str(options.recipe.resolve()),
        "--output-dir",
        str(options.output_dir.resolve()),
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
    if options.overwrite:
        args.append("--overwrite")

    result = subprocess.run(
        args,
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise NexUIError(f"Recording failed: {stderr}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise NexUIError("Recorder completed but did not return valid JSON output.") from exc
