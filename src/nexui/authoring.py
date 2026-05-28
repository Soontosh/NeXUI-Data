from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from typing import Any

from nexui.capture import CaptureOptions, run_capture
from nexui.io import NexUIError, read_json, read_text, read_yaml_like, write_json, write_text


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_sources_root() -> Path:
    return _repo_root() / "sources"


def default_registry_path() -> Path:
    return default_sources_root() / "registry.json"


@dataclass
class InitSourceOptions:
    site_id: str
    site_name: str
    base_url: str
    source_track: str
    category: str
    hosting_mode: str
    redistribution_class: str
    reset_strategy: str
    determinism_level: str
    output_dir: Path
    registry_path: Path


@dataclass
class SurveySourceOptions:
    source_path: Path
    entry_id: str | None = None
    overwrite: bool = False
    headed: bool = False


@dataclass
class ValidateSourceOptions:
    source_path: Path
    check_remote: bool = False


def _source_template_root() -> Path:
    return _repo_root() / "templates" / "source-template"


def _load_manifest_path(source_path: Path) -> Path:
    if source_path.is_file():
        return source_path
    return source_path / "site.yaml"


def load_source_manifest(source_path: str | Path) -> tuple[Path, dict[str, Any]]:
    manifest_path = _load_manifest_path(Path(source_path).resolve())
    if not manifest_path.exists():
        raise NexUIError(f"Source manifest not found: {manifest_path}")
    manifest = read_yaml_like(manifest_path)
    return manifest_path, manifest


def _resolve_entry_url(source_root: Path, entry: dict[str, Any]) -> str:
    url = entry.get("url")
    if url:
        return str(url)

    relative_path = entry.get("path")
    if not relative_path:
        raise NexUIError(f"Entry point {entry.get('entry_id', '<unknown>')} must provide either url or path.")

    resolved_path = (source_root / relative_path).resolve()
    if not resolved_path.exists():
        raise NexUIError(f"Entry path does not exist: {resolved_path}")
    return resolved_path.as_uri()


def _replace_placeholders(text: str, replacements: dict[str, str]) -> str:
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text


def _copy_source_template(destination: Path, replacements: dict[str, str]) -> None:
    template_root = _source_template_root()
    for path in template_root.rglob("*"):
        relative = path.relative_to(template_root)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        content = read_text(path)
        write_text(target, _replace_placeholders(content, replacements))


def _load_registry(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return read_json(path)


def _save_registry(path: Path, registry: list[dict[str, Any]]) -> None:
    registry = sorted(registry, key=lambda entry: entry["site_id"])
    write_json(path, registry)


def _manifest_registry_path(source_root: Path) -> Path | None:
    candidate = source_root.parent / "registry.json"
    if candidate.exists():
        return candidate
    return None


def init_source(options: InitSourceOptions) -> Path:
    source_root = options.output_dir.resolve() / options.site_id
    if source_root.exists():
        raise NexUIError(f"Source package already exists: {source_root}")

    replacements = {
        "__SITE_ID__": options.site_id,
        "__SITE_NAME__": options.site_name,
        "__BASE_URL__": options.base_url,
        "__SOURCE_TRACK__": options.source_track,
        "__CATEGORY__": options.category,
        "__HOSTING_MODE__": options.hosting_mode,
        "__REDISTRIBUTION_CLASS__": options.redistribution_class,
        "__RESET_STRATEGY__": options.reset_strategy,
        "__DETERMINISM_LEVEL__": options.determinism_level,
    }
    _copy_source_template(source_root, replacements)

    try:
        manifest_path = str((source_root / "site.yaml").resolve().relative_to(_repo_root()))
    except ValueError:
        manifest_path = str((source_root / "site.yaml").resolve())

    registry_path = options.registry_path.resolve()
    registry = _load_registry(registry_path)
    registry = [entry for entry in registry if entry["site_id"] != options.site_id]
    registry.append(
        {
            "site_id": options.site_id,
            "site_name": options.site_name,
            "manifest_path": manifest_path,
            "base_url": options.base_url,
            "source_track": options.source_track,
            "category": options.category,
            "hosting_mode": options.hosting_mode,
            "redistribution_class": options.redistribution_class,
            "authoring_status": "intake",
            "reset_strategy": options.reset_strategy,
            "determinism_level": options.determinism_level,
            "runtime_healthcheck_url": "",
            "runtime_checkout_path": "",
            "notes": "Created from the source template."
        }
    )
    _save_registry(registry_path, registry)
    return source_root


def list_sources(registry_path: str | Path) -> list[dict[str, Any]]:
    return _load_registry(Path(registry_path).resolve())


def survey_source(options: SurveySourceOptions) -> dict[str, Any]:
    manifest_path, manifest = load_source_manifest(options.source_path)
    source_root = manifest_path.parent
    capture_defaults = manifest["capture_defaults"]

    captures: list[dict[str, Any]] = []
    selected_entries = manifest["entry_points"]
    if options.entry_id:
        selected_entries = [entry for entry in selected_entries if entry["entry_id"] == options.entry_id]
        if not selected_entries:
            raise NexUIError(f"Entry id {options.entry_id!r} not found in {manifest_path}")

    for entry in selected_entries:
        snapshot_dir = source_root / "captures" / entry["entry_id"] / "s000"
        if snapshot_dir.exists() and not options.overwrite:
            raise NexUIError(f"Capture already exists: {snapshot_dir}. Use --overwrite to replace it.")
        capture_url = _resolve_entry_url(source_root, entry)
        summary = run_capture(
            CaptureOptions(
                url=capture_url,
                snapshot_dir=snapshot_dir,
                browser=capture_defaults["browser"],
                wait_until=capture_defaults["wait_until"],
                delay_ms=int(capture_defaults.get("delay_ms", 0)),
                timeout_ms=int(capture_defaults.get("timeout_ms", 30000)),
                viewport_width=int(capture_defaults["viewport_width"]),
                viewport_height=int(capture_defaults["viewport_height"]),
                locale=capture_defaults["locale"],
                http_headers=dict(capture_defaults.get("http_headers") or {}),
                headed=options.headed,
            )
        )
        captures.append(
            {
                "entry_id": entry["entry_id"],
                "label": entry["label"],
                "entry_target": entry.get("url") or entry.get("path"),
                "snapshot_dir": str(snapshot_dir.resolve()),
                "url": summary["url"],
                "title": summary["title"],
                "candidate_count": summary["candidate_count"],
                "modal_state": summary["modal_state"],
            }
        )

    survey_summary = {
        "site_id": manifest["site_id"],
        "site_name": manifest["site_name"],
        "surveyed_entry_count": len(captures),
        "captures": captures,
    }

    if captures:
        manifest["authoring_status"] = "surveyed"
        write_json(manifest_path, manifest)
        registry_path = _manifest_registry_path(source_root)
        if registry_path is not None:
            registry = _load_registry(registry_path)
            updated = []
            for entry in registry:
                if entry["site_id"] == manifest["site_id"]:
                    updated.append({**entry, "authoring_status": "surveyed"})
                else:
                    updated.append(entry)
            _save_registry(registry_path, updated)

    write_json(source_root / "survey-summary.json", survey_summary)
    return survey_summary


def _check_doc_exists(source_root: Path, relative_path: str, label: str) -> tuple[bool, str]:
    target = (source_root / relative_path).resolve()
    if not target.exists():
        return False, f"{label} is missing: {target}"
    return True, f"{label} exists: {target}"


def _check_remote_url(url: str) -> tuple[bool, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return True, f"remote check skipped for non-http URL: {url}"

    request = Request(url, method="HEAD")
    try:
        with urlopen(request, timeout=10) as response:
            status = getattr(response, "status", None) or response.getcode()
        return 200 <= int(status) < 400, f"remote URL responded with status {status}: {url}"
    except Exception as exc:  # pragma: no cover - network-dependent
        return False, f"remote URL check failed for {url}: {exc}"


def _run_runtime_command(command: str) -> tuple[bool, str]:
    result = subprocess.run(
        command,
        cwd=_repo_root(),
        shell=True,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return True, f"runtime readiness command passed: {command}"
    detail = (result.stderr or result.stdout or "command failed").strip()
    detail = detail.splitlines()[0] if detail else "command failed"
    return False, f"runtime readiness command failed: {detail}"


def _runtime_status_from_manifest(
    source_root: Path,
    manifest: dict[str, Any],
    *,
    check_remote: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], list[str]]:
    runtime = manifest.get("runtime") or {}
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []

    checkout_value = str(runtime.get("local_checkout_path") or "").strip()
    healthcheck_url = str(runtime.get("healthcheck_url") or "").strip()
    bootstrap_commands = list(runtime.get("bootstrap_commands") or [])
    start_command = str(runtime.get("start_command") or "").strip()
    reseed_command = str(runtime.get("reseed_command") or "").strip()
    readiness_command = str(runtime.get("readiness_command") or "").strip()

    checkout_exists = None
    resolved_checkout_path = None
    if checkout_value:
        resolved_checkout_path = (source_root / checkout_value).resolve()
        checkout_exists = resolved_checkout_path.exists()
        message = f"checkout path {'exists' if checkout_exists else 'missing'}: {resolved_checkout_path}"
        checks.append(
            {
                "type": "runtime_checkout",
                "target": manifest["site_id"],
                "passed": checkout_exists,
                "message": message,
            }
        )
        if not checkout_exists:
            warnings.append(message)

    healthcheck_passed = None
    if healthcheck_url:
        if check_remote:
            healthcheck_passed, message = _check_remote_url(healthcheck_url)
            checks.append(
                {
                    "type": "runtime_healthcheck",
                    "target": manifest["site_id"],
                    "passed": healthcheck_passed,
                    "message": message,
                }
            )
            if not healthcheck_passed:
                warnings.append(message)
        else:
            checks.append(
                {
                    "type": "runtime_healthcheck",
                    "target": manifest["site_id"],
                    "passed": True,
                    "message": f"healthcheck configured but not probed: {healthcheck_url}",
                }
            )

    readiness_passed = None
    if readiness_command:
        if check_remote:
            readiness_passed, message = _run_runtime_command(readiness_command)
            checks.append(
                {
                    "type": "runtime_readiness_command",
                    "target": manifest["site_id"],
                    "passed": readiness_passed,
                    "message": message,
                }
            )
            if not readiness_passed:
                warnings.append(message)
        else:
            checks.append(
                {
                    "type": "runtime_readiness_command",
                    "target": manifest["site_id"],
                    "passed": True,
                    "message": f"readiness command configured but not run: {readiness_command}",
                }
            )

    hosting_mode = manifest.get("hosting_mode")
    if hosting_mode in {"self_hosted", "benchmark_env"}:
        if not checkout_value:
            warnings.append("runtime.local_checkout_path is not set for this self-hosted or benchmark source")
        if not healthcheck_url:
            warnings.append("runtime.healthcheck_url is not set for this self-hosted or benchmark source")
        if not bootstrap_commands:
            warnings.append("runtime.bootstrap_commands is empty for this self-hosted or benchmark source")
        if not start_command:
            warnings.append("runtime.start_command is empty for this self-hosted or benchmark source")
        if manifest.get("reset_strategy") in {"reseed_command", "docker_reset"} and not reseed_command:
            warnings.append("runtime.reseed_command is empty for a source that declares reseedable reset behavior")

    is_ready = True
    if checkout_exists is False:
        is_ready = False
    if healthcheck_passed is False:
        is_ready = False
    if readiness_passed is False:
        is_ready = False
    if hosting_mode in {"self_hosted", "benchmark_env"} and (not checkout_value or not healthcheck_url or not start_command):
        is_ready = False

    return (
        {
            "is_ready": is_ready,
            "checkout_path": str(resolved_checkout_path) if resolved_checkout_path else checkout_value,
            "healthcheck_url": healthcheck_url,
            "bootstrap_commands": bootstrap_commands,
            "start_command": start_command,
            "reseed_command": reseed_command,
            "readiness_command": readiness_command,
        },
        checks,
        warnings,
        errors,
    )


def validate_source(options: ValidateSourceOptions) -> dict[str, Any]:
    manifest_path, manifest = load_source_manifest(options.source_path)
    source_root = manifest_path.parent
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []

    onboarding = manifest.get("onboarding", {})
    for key, label in (
        ("bootstrap_doc", "bootstrap doc"),
        ("reset_doc", "reset doc"),
        ("seed_notes_doc", "seed notes doc"),
    ):
        relative_path = onboarding.get(key)
        if not relative_path:
            errors.append(f"onboarding.{key} is missing")
            continue
        passed, message = _check_doc_exists(source_root, str(relative_path), label)
        checks.append({"type": "onboarding_doc", "target": key, "passed": passed, "message": message})
        if not passed:
            errors.append(message)

    for entry in manifest.get("entry_points", []):
        entry_id = entry.get("entry_id", "<unknown>")
        has_url = bool(entry.get("url"))
        has_path = bool(entry.get("path"))
        if not has_url and not has_path:
            errors.append(f"entry point {entry_id} must define url or path")
            checks.append(
                {"type": "entry_point", "target": entry_id, "passed": False, "message": "missing url/path"}
            )
            continue

        if has_path:
            resolved_path = (source_root / str(entry["path"])).resolve()
            passed = resolved_path.exists()
            message = f"path {'exists' if passed else 'missing'}: {resolved_path}"
            checks.append({"type": "entry_point_path", "target": entry_id, "passed": passed, "message": message})
            if not passed:
                errors.append(f"entry point {entry_id} path does not exist: {resolved_path}")

        if has_url and options.check_remote:
            passed, message = _check_remote_url(str(entry["url"]))
            checks.append({"type": "entry_point_url", "target": entry_id, "passed": passed, "message": message})
            if not passed:
                warnings.append(message)

    for idea in manifest.get("task_ideas", []):
        if "risk_level" not in idea:
            warnings.append(f"task idea {idea.get('idea_id', '<unknown>')} is missing risk_level")

    runtime_status, runtime_checks, runtime_warnings, runtime_errors = _runtime_status_from_manifest(
        source_root,
        manifest,
        check_remote=options.check_remote,
    )
    checks.extend(runtime_checks)
    warnings.extend(runtime_warnings)
    errors.extend(runtime_errors)

    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))

    passed = not errors
    if options.check_remote and runtime_status.get("is_ready") is False:
        passed = False

    return {
        "site_id": manifest["site_id"],
        "site_name": manifest["site_name"],
        "manifest_path": str(manifest_path.resolve()),
        "passed": passed,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "runtime_status": runtime_status,
    }
