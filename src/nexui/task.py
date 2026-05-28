from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nexui.io import NexUIError, read_json, read_text, read_yaml_like


REQUIRED_TASK_FILES = [
    "task.yaml",
    "instruction.md",
    "user_profile.json",
    "transitions.yaml",
    "oracle/trajectory.jsonl",
    "eval/check_success.py",
    "eval/safety_rules.yaml",
    "eval/explanation_rubric.yaml",
]

_STEP_EXPLANATION_ALLOWED_KEYS = {
    "preferred_min_words",
    "preferred_max_words",
    "must_describe_state_change",
    "must_ground_in_visible_state",
    "must_link_to_goal",
    "must_predict_effect",
    "generic_finish_disallowed",
}

_RISK_EXPLANATION_ALLOWED_KEYS = {
    "required_for_ask_user",
    "required_for_confirmation_required_actions",
    "must_name_risk_type",
}

_FINAL_SUMMARY_ALLOWED_KEYS = {
    "preferred_max_words",
    "must_cover_key_outcome",
    "must_match_final_state",
    "boundary_aware",
}


def default_source_registry_path() -> Path:
    return Path(__file__).resolve().parents[2] / "sources" / "registry.json"


def load_source_registry_index(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    registry_path = Path(path).resolve() if path is not None else default_source_registry_path()
    if not registry_path.exists():
        return {}
    registry = read_json(registry_path)
    return {
        str(entry["site_id"]): entry
        for entry in registry
        if isinstance(entry, dict) and entry.get("site_id")
    }


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _action_matches(pattern: Any, action: Any) -> bool:
    if isinstance(pattern, dict):
        if not isinstance(action, dict):
            return False
        for key, value in pattern.items():
            if key not in action or not _action_matches(value, action[key]):
                return False
        return True
    if isinstance(pattern, list):
        return pattern == action
    return pattern == action


@dataclass
class TaskPackage:
    root: Path
    manifest: dict[str, Any]
    transitions: list[dict[str, Any]]
    oracle_steps: list[dict[str, Any]]

    @property
    def task_id(self) -> str:
        return self.manifest["task_id"]

    @property
    def start_snapshot(self) -> str:
        return self.manifest["start_snapshot"]

    @property
    def allowed_actions(self) -> set[str]:
        return set(self.manifest["allowed_actions"])

    @property
    def snapshots(self) -> list[str]:
        return list(self.manifest["snapshots"])

    @property
    def instruction(self) -> str:
        return read_text(self.root / self.manifest["instruction_file"])

    @property
    def user_profile(self) -> dict[str, Any]:
        return read_json(self.root / self.manifest["user_profile_file"])

    @property
    def safety_rules(self) -> dict[str, Any]:
        return read_yaml_like(self.root / self.manifest["eval"]["safety_rules"])

    @property
    def explanation_rubric(self) -> dict[str, Any]:
        return read_yaml_like(self.root / self.manifest["eval"]["explanation_rubric"])

    @property
    def success_checker_path(self) -> Path:
        return self.root / self.manifest["eval"]["success_checker"]

    @property
    def success_assertions(self) -> list[dict[str, Any]]:
        return list(self.manifest.get("success_assertions", []))

    @property
    def success_any_of(self) -> list[list[dict[str, Any]]]:
        return list(self.manifest.get("success_any_of", []))

    @property
    def source_surface(self) -> str:
        return str(self.manifest.get("source_surface") or "")

    @property
    def requires_source_reset(self) -> bool:
        return bool(self.manifest.get("requires_source_reset", False))

    def snapshot_dir(self, snapshot_id: str) -> Path:
        return self.root / "snapshots" / snapshot_id

    def validate_layout(self) -> None:
        for relative_path in REQUIRED_TASK_FILES:
            path = self.root / relative_path
            if not path.exists():
                raise NexUIError(f"Missing required task file: {path}")

        for snapshot_id in self.snapshots:
            snapshot_dir = self.snapshot_dir(snapshot_id)
            if not snapshot_dir.exists():
                raise NexUIError(f"Missing snapshot directory: {snapshot_dir}")
            for filename in [
                "screenshot.png",
                "dom.json",
                "ax_tree.json",
                "aria_snapshot.yml",
                "reader_view.txt",
                "candidates.json",
                "metadata.json",
            ]:
                artifact_path = snapshot_dir / filename
                if not artifact_path.exists():
                    raise NexUIError(f"Missing snapshot artifact: {artifact_path}")

    def build_observation(self, snapshot_id: str) -> dict[str, Any]:
        if snapshot_id not in self.snapshots:
            raise NexUIError(f"Unknown snapshot id: {snapshot_id}")

        snapshot_dir = self.snapshot_dir(snapshot_id)
        metadata = read_json(snapshot_dir / "metadata.json")
        candidates = read_json(snapshot_dir / "candidates.json")
        return {
            "schema_version": self.manifest["schema_version"],
            "task_id": self.task_id,
            "snapshot_id": snapshot_id,
            "url": metadata["url"],
            "title": metadata["title"],
            "locale": metadata["locale"],
            "viewport": metadata["viewport"],
            "focus_target": metadata.get("focus_target"),
            "modal_state": metadata["modal_state"],
            "artifacts": {
                "screenshot": str((snapshot_dir / "screenshot.png").relative_to(self.root)),
                "dom": str((snapshot_dir / "dom.json").relative_to(self.root)),
                "ax_tree": str((snapshot_dir / "ax_tree.json").relative_to(self.root)),
                "aria_snapshot": str((snapshot_dir / "aria_snapshot.yml").relative_to(self.root)),
                "reader_view": str((snapshot_dir / "reader_view.txt").relative_to(self.root)),
                "metadata": str((snapshot_dir / "metadata.json").relative_to(self.root)),
            },
            "candidates": candidates,
        }

    def find_transition(self, snapshot_id: str, action: dict[str, Any]) -> dict[str, Any] | None:
        for transition in self.transitions:
            if transition["from"] != snapshot_id:
                continue
            if _action_matches(transition["action"], action):
                return transition
        return None


def load_oracle_steps(path: Path) -> list[dict[str, Any]]:
    steps = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            step = __import__("json").loads(stripped)
        except ValueError as exc:
            raise NexUIError(f"Invalid JSONL in {path} line {line_number}") from exc
        steps.append(step)
    return steps


def load_task(task_path: str | Path) -> TaskPackage:
    root = Path(task_path).resolve()
    if not root.exists():
        raise NexUIError(f"Task path does not exist: {root}")

    manifest = read_yaml_like(root / "task.yaml")
    transitions = read_yaml_like(root / "transitions.yaml")
    oracle_steps = load_oracle_steps(root / "oracle" / "trajectory.jsonl")
    task = TaskPackage(root=root, manifest=manifest, transitions=transitions, oracle_steps=oracle_steps)
    task.validate_layout()
    return task


def inspect_task(task: TaskPackage) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "title": task.manifest["title"],
        "goal": task.manifest["goal"],
        "risk_level": task.manifest["risk_level"],
        "difficulty_band": task.manifest.get("difficulty_band"),
        "difficulty_dimensions": task.manifest.get("difficulty_dimensions", {}),
        "source_surface": task.manifest.get("source_surface"),
        "split": task.manifest.get("split", "unassigned"),
        "stability_runs_passed": task.manifest.get("stability_runs_passed", 0),
        "requires_source_reset": task.manifest.get("requires_source_reset", False),
        "allowed_actions": sorted(task.allowed_actions),
        "start_snapshot": task.start_snapshot,
        "snapshot_count": len(task.snapshots),
        "transition_count": len(task.transitions),
        "oracle_step_count": len(task.oracle_steps),
        "source": task.manifest["source"],
        "checked_at": _utc_now(),
    }


def _validate_bool_field(
    errors: list[str],
    *,
    task_id: str,
    section: str,
    key: str,
    value: Any,
) -> None:
    if not isinstance(value, bool):
        errors.append(f"{task_id}: explanation_rubric.{section}.{key} must be a boolean")


def _validate_int_field(
    errors: list[str],
    *,
    task_id: str,
    section: str,
    key: str,
    value: Any,
    minimum: int,
) -> None:
    if not isinstance(value, int) or value < minimum:
        errors.append(
            f"{task_id}: explanation_rubric.{section}.{key} must be an integer >= {minimum}"
        )


def _validate_explanation_rubric(task: TaskPackage) -> list[str]:
    errors: list[str] = []
    rubric = task.explanation_rubric
    task_id = task.task_id

    if not isinstance(rubric, dict):
        return [f"{task_id}: explanation_rubric must be an object"]

    unknown_top_level = set(rubric) - {"step_explanation", "risk_explanation", "final_summary"}
    for key in sorted(unknown_top_level):
        errors.append(f"{task_id}: explanation_rubric has unknown top-level key {key!r}")

    step = rubric.get("step_explanation")
    if not isinstance(step, dict):
        errors.append(f"{task_id}: explanation_rubric.step_explanation must be an object")
    else:
        unknown = set(step) - _STEP_EXPLANATION_ALLOWED_KEYS
        for key in sorted(unknown):
            errors.append(f"{task_id}: explanation_rubric.step_explanation has unknown key {key!r}")
        if "preferred_max_words" not in step:
            errors.append(
                f"{task_id}: explanation_rubric.step_explanation.preferred_max_words is required"
            )
        for key, value in step.items():
            if key in {"preferred_min_words", "preferred_max_words"}:
                _validate_int_field(
                    errors,
                    task_id=task_id,
                    section="step_explanation",
                    key=key,
                    value=value,
                    minimum=0 if key == "preferred_min_words" else 1,
                )
            else:
                _validate_bool_field(
                    errors,
                    task_id=task_id,
                    section="step_explanation",
                    key=key,
                    value=value,
                )

    risk = rubric.get("risk_explanation")
    if risk is not None:
        if not isinstance(risk, dict):
            errors.append(f"{task_id}: explanation_rubric.risk_explanation must be an object")
        else:
            unknown = set(risk) - _RISK_EXPLANATION_ALLOWED_KEYS
            for key in sorted(unknown):
                errors.append(
                    f"{task_id}: explanation_rubric.risk_explanation has unknown key {key!r}"
                )
            for key, value in risk.items():
                _validate_bool_field(
                    errors,
                    task_id=task_id,
                    section="risk_explanation",
                    key=key,
                    value=value,
                )

    final_summary = rubric.get("final_summary")
    if not isinstance(final_summary, dict):
        errors.append(f"{task_id}: explanation_rubric.final_summary must be an object")
    else:
        unknown = set(final_summary) - _FINAL_SUMMARY_ALLOWED_KEYS
        for key in sorted(unknown):
            errors.append(f"{task_id}: explanation_rubric.final_summary has unknown key {key!r}")
        if "preferred_max_words" not in final_summary:
            errors.append(
                f"{task_id}: explanation_rubric.final_summary.preferred_max_words is required"
            )
        for key, value in final_summary.items():
            if key == "preferred_max_words":
                _validate_int_field(
                    errors,
                    task_id=task_id,
                    section="final_summary",
                    key=key,
                    value=value,
                    minimum=1,
                )
            else:
                _validate_bool_field(
                    errors,
                    task_id=task_id,
                    section="final_summary",
                    key=key,
                    value=value,
                )

    return errors


def validate_task_metadata(
    task: TaskPackage,
    *,
    registry_index: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    errors: list[str] = []
    manifest = task.manifest
    source = dict(manifest.get("source") or {})
    source_surface = str(manifest.get("source_surface") or "").strip()

    if registry_index is None:
        registry_index = load_source_registry_index()

    canonical = registry_index.get(source_surface) if source_surface else None
    if canonical is not None:
        if source.get("site_id") != source_surface:
            errors.append(
                f"{task.task_id}: source.site_id {source.get('site_id')!r} must match source_surface {source_surface!r}"
            )
        for field in ("site_name", "category", "redistribution_class"):
            expected = canonical.get(field)
            actual = source.get(field)
            if actual != expected:
                errors.append(
                    f"{task.task_id}: source.{field} {actual!r} must match canonical value {expected!r}"
                )

    tags = set(manifest.get("tags") or [])
    if "monstrous" in tags:
        if manifest.get("difficulty_band") != "very_hard":
            errors.append(
                f"{task.task_id}: monstrous tasks must use difficulty_band 'very_hard'"
            )
        stability_runs = manifest.get("stability_runs_passed", 0)
        try:
            stability_runs = int(stability_runs)
        except (TypeError, ValueError):
            stability_runs = 0
        if stability_runs < 7:
            errors.append(
                f"{task.task_id}: monstrous tasks must record stability_runs_passed >= 7"
            )

    errors.extend(_validate_explanation_rubric(task))

    return errors
