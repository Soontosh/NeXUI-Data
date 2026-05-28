from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from nexui.io import NexUIError, read_json, write_json
from nexui.task import inspect_task, load_source_registry_index, load_task, validate_task_metadata


SPLIT_IDS = ("dev", "validation", "test", "challenge")
PRIMARY_SPLIT_IDS = ("dev", "validation", "test")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_tasks_root() -> Path:
    return _repo_root() / "examples" / "tasks"


def default_splits_root() -> Path:
    return _repo_root() / "splits"


def split_manifest_path(splits_root: str | Path, split_id: str) -> Path:
    return Path(splits_root).resolve() / f"{split_id}.json"


def load_split_manifest(path: str | Path) -> dict[str, Any]:
    split_path = Path(path).resolve()
    if not split_path.exists():
        raise NexUIError(f"Split manifest not found: {split_path}")
    return read_json(split_path)


def load_split_manifests(splits_root: str | Path) -> dict[str, dict[str, Any]]:
    root = Path(splits_root).resolve()
    manifests: dict[str, dict[str, Any]] = {}
    for split_id in SPLIT_IDS:
        path = split_manifest_path(root, split_id)
        if not path.exists():
            raise NexUIError(f"Missing split manifest: {path}")
        manifests[split_id] = read_json(path)
    return manifests


def write_split_manifest(path: str | Path, manifest: dict[str, Any]) -> None:
    write_json(Path(path).resolve(), manifest)


def discover_tasks(tasks_root: str | Path) -> list[Any]:
    root = Path(tasks_root).resolve()
    if not root.exists():
        raise NexUIError(f"Tasks root does not exist: {root}")
    tasks = []
    for task_file in sorted(root.glob("*/task.yaml")):
        tasks.append(load_task(task_file.parent))
    return tasks


def _split_membership(manifests: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    membership: dict[str, list[str]] = defaultdict(list)
    for split_id, manifest in manifests.items():
        for task_id in manifest.get("task_ids", []):
            membership[task_id].append(split_id)
    return dict(membership)


def list_task_inventory(
    *,
    tasks_root: str | Path,
    splits_root: str | Path,
) -> list[dict[str, Any]]:
    tasks = discover_tasks(tasks_root)
    split_manifests = load_split_manifests(splits_root)
    membership = _split_membership(split_manifests)
    inventory = []
    for task in tasks:
        summary = inspect_task(task)
        manifest = task.manifest
        declared_split = manifest.get("split", "unassigned")
        assigned_splits = membership.get(task.task_id, [])
        production = manifest.get("source", {}).get("site_id") != "packaged-demo"
        inventory.append(
            {
                "task_id": task.task_id,
                "title": summary["title"],
                "source_id": manifest["source"]["site_id"],
                "source_surface": manifest.get("source_surface"),
                "risk_level": manifest["risk_level"],
                "difficulty_band": manifest.get("difficulty_band"),
                "declared_split": declared_split,
                "assigned_splits": assigned_splits,
                "stability_runs_passed": manifest.get("stability_runs_passed", 0),
                "production": production,
            }
        )
    return inventory


def validate_split_manifests(
    *,
    tasks_root: str | Path,
    splits_root: str | Path,
) -> dict[str, Any]:
    tasks = discover_tasks(tasks_root)
    task_ids = {task.task_id for task in tasks}
    production_task_ids = {
        task.task_id
        for task in tasks
        if task.manifest.get("source", {}).get("site_id") != "packaged-demo"
    }
    manifests = load_split_manifests(splits_root)
    registry_index = load_source_registry_index()

    errors: list[str] = []
    warnings: list[str] = []
    membership = _split_membership(manifests)
    counts = {split_id: len(manifest.get("task_ids", [])) for split_id, manifest in manifests.items()}

    for split_id, manifest in manifests.items():
        if manifest.get("split_id") != split_id:
            errors.append(f"{split_id}.json declares split_id={manifest.get('split_id')!r}")
        for task_id in manifest.get("task_ids", []):
            if task_id not in task_ids:
                errors.append(f"{split_id}.json references unknown task_id {task_id!r}")

    for split_id in PRIMARY_SPLIT_IDS:
        for other_split in PRIMARY_SPLIT_IDS:
            if split_id >= other_split:
                continue
            overlap = set(manifests[split_id]["task_ids"]) & set(manifests[other_split]["task_ids"])
            if overlap:
                errors.append(
                    f"{split_id} and {other_split} are not disjoint: {', '.join(sorted(overlap))}"
                )

    for task in tasks:
        if task.task_id not in production_task_ids:
            continue
        errors.extend(validate_task_metadata(task, registry_index=registry_index))

    challenge_tasks = set(manifests["challenge"]["task_ids"])
    test_tasks = set(manifests["test"]["task_ids"])
    if not challenge_tasks.issubset(test_tasks):
        missing = sorted(challenge_tasks - test_tasks)
        errors.append(
            f"challenge split must be a subset of test split; missing from test: {', '.join(missing)}"
        )

    unassigned_production = sorted(production_task_ids - set(membership))
    if unassigned_production:
        warnings.append(
            f"{len(unassigned_production)} production tasks are not assigned to a split"
        )

    declared_split_mismatches = []
    for task in tasks:
        declared_split = task.manifest.get("split")
        if not declared_split or declared_split == "unassigned":
            continue
        assigned = membership.get(task.task_id, [])
        if declared_split not in assigned:
            declared_split_mismatches.append(
                f"{task.task_id}: manifest split {declared_split!r} not present in split manifests"
            )
    if declared_split_mismatches:
        warnings.extend(declared_split_mismatches)

    band_counts = Counter(
        task.manifest.get("difficulty_band", "unknown")
        for task in tasks
        if task.manifest.get("source", {}).get("site_id") != "packaged-demo"
    )

    return {
        "passed": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "split_counts": counts,
        "difficulty_band_counts": dict(sorted(band_counts.items())),
        "production_task_count": len(production_task_ids),
        "unassigned_production_tasks": unassigned_production,
    }
