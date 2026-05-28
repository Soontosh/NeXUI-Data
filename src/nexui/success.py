from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nexui.io import NexUIError, read_json, read_text
from nexui.task import TaskPackage


TEXT_ASSERTION_ARTIFACTS = {"reader_view", "aria_snapshot", "dom", "any_text"}


@dataclass(frozen=True)
class SnapshotArtifacts:
    snapshot_id: str
    metadata: dict[str, Any]
    candidates: list[dict[str, Any]]
    reader_view: str
    aria_snapshot: str
    dom: str


def evaluate_success_from_manifest(
    task: TaskPackage,
    trace: dict[str, Any],
    *,
    fallback_final_snapshot: str | None = None,
    fallback_note: str | None = None,
) -> dict[str, Any]:
    final_snapshot = resolve_final_snapshot(task, trace)
    notes = [f"Final snapshot observed: {final_snapshot}"]
    if trace["result"]["status"] != "completed" and not manifest_has_trace_status_assertion(task):
        notes.append(f"Trace did not complete successfully: {trace['result']['status']}")
        return {"task_success": False, "notes": notes}

    has_manifest_conditions = bool(task.success_assertions or task.success_any_of)
    if has_manifest_conditions:
        passed, condition_notes = evaluate_manifest_conditions(task, trace, final_snapshot)
        notes.extend(condition_notes)
        return {"task_success": passed, "notes": notes}

    if fallback_final_snapshot is not None:
        passed = final_snapshot == fallback_final_snapshot
        if fallback_note:
            notes.append(fallback_note)
        return {"task_success": passed, "notes": notes}

    notes.append("No manifest success conditions or fallback final snapshot were provided.")
    return {"task_success": False, "notes": notes}


def resolve_final_snapshot(task: TaskPackage, trace: dict[str, Any]) -> str:
    final_snapshot = task.start_snapshot
    for step in trace.get("steps", []):
        if step.get("after_snapshot") is not None:
            final_snapshot = step["after_snapshot"]
    return final_snapshot


def evaluate_manifest_conditions(
    task: TaskPackage,
    trace: dict[str, Any],
    snapshot_id: str,
) -> tuple[bool, list[str]]:
    notes: list[str] = []
    all_passed = True

    if task.success_assertions:
        passed, assertion_notes = evaluate_assertion_group(
            task,
            trace,
            snapshot_id,
            task.success_assertions,
            label="all",
        )
        all_passed = all_passed and passed
        notes.extend(assertion_notes)

    if task.success_any_of:
        branch_results: list[bool] = []
        branch_notes: list[str] = []
        for index, branch in enumerate(task.success_any_of, start=1):
            passed, assertion_notes = evaluate_assertion_group(
                task,
                trace,
                snapshot_id,
                branch,
                label=f"any_of[{index}]",
            )
            branch_results.append(passed)
            branch_notes.extend(assertion_notes)
        all_passed = all_passed and any(branch_results)
        notes.extend(branch_notes)
        if not any(branch_results):
            notes.append("No success_any_of branch passed.")

    return all_passed, notes


def evaluate_assertion_group(
    task: TaskPackage,
    trace: dict[str, Any],
    snapshot_id: str,
    assertions: list[dict[str, Any]],
    *,
    label: str,
) -> tuple[bool, list[str]]:
    artifacts = load_snapshot_artifacts(task, snapshot_id)
    notes: list[str] = []
    passed = True
    for index, assertion in enumerate(assertions, start=1):
        assertion_passed, message = evaluate_assertion(artifacts, assertion, trace)
        status = "passed" if assertion_passed else "failed"
        notes.append(f"{label} assertion {index}: {status} - {message}")
        passed = passed and assertion_passed
    return passed, notes


def load_snapshot_artifacts(task: TaskPackage, snapshot_id: str) -> SnapshotArtifacts:
    snapshot_dir = task.snapshot_dir(snapshot_id)
    return SnapshotArtifacts(
        snapshot_id=snapshot_id,
        metadata=read_json(snapshot_dir / "metadata.json"),
        candidates=read_json(snapshot_dir / "candidates.json"),
        reader_view=read_text(snapshot_dir / "reader_view.txt"),
        aria_snapshot=read_text(snapshot_dir / "aria_snapshot.yml"),
        dom=read_text(snapshot_dir / "dom.json"),
    )


def evaluate_assertion(
    artifacts: SnapshotArtifacts,
    assertion: dict[str, Any],
    trace: dict[str, Any],
) -> tuple[bool, str]:
    assertion_type = assertion.get("type")
    if not assertion_type:
        raise NexUIError("Success assertion must include a type.")

    if assertion_type == "trace_status_is":
        value = str(assertion["value"])
        actual = str(trace.get("result", {}).get("status", ""))
        return actual == value, f"trace status is {value!r}"

    if assertion_type == "trace_note_contains":
        value = normalize_text(assertion["value"]).casefold()
        notes = []
        for step in trace.get("steps", []):
            notes.extend(step.get("notes", []))
        haystack = normalize_text("\n".join(str(note) for note in notes)).casefold()
        return value in haystack, f"trace note contains {assertion['value']!r}"

    if assertion_type == "last_action_type_is":
        value = str(assertion["value"])
        actual = str(resolve_last_action(trace).get("type", ""))
        return actual == value, f"last action type is {value!r}"

    if assertion_type == "url_contains":
        value = str(assertion["value"])
        actual = artifacts.metadata.get("url", "")
        return value in actual, f"url contains {value!r}"

    if assertion_type == "modal_state_is":
        value = str(assertion["value"])
        actual = str(artifacts.metadata.get("modal_state", ""))
        return actual == value, f"modal state is {value!r}"

    if assertion_type in {"text_present", "text_absent"}:
        value = str(assertion["value"])
        haystack = gather_text_haystack(artifacts, assertion.get("artifact", "any_text"))
        found = normalize_text(value).casefold() in normalize_text(haystack).casefold()
        expected = assertion_type == "text_present"
        return found == expected, f"text {'present' if expected else 'absent'} {value!r}"

    if assertion_type in {"candidate_exists", "candidate_missing"}:
        candidate = find_matching_candidate(artifacts.candidates, assertion["match"])
        exists = candidate is not None
        expected = assertion_type == "candidate_exists"
        return exists == expected, f"candidate {'exists' if expected else 'missing'} for {assertion['match']}"

    if assertion_type == "field_value_equals":
        candidate = find_matching_candidate(artifacts.candidates, assertion["match"])
        if candidate is None:
            return False, f"no candidate matched field_value_equals matcher {assertion['match']}"
        actual_value = normalize_text(candidate.get("value"))
        expected_value = normalize_text(assertion["value"])
        return actual_value == expected_value, f"field value equals {expected_value!r}"

    if assertion_type in {"field_enabled", "field_disabled"}:
        candidate = find_matching_candidate(artifacts.candidates, assertion["match"])
        if candidate is None:
            return False, f"no candidate matched {assertion_type} matcher {assertion['match']}"
        actual_enabled = bool(candidate.get("states", {}).get("enabled"))
        expected_enabled = assertion_type == "field_enabled"
        return actual_enabled == expected_enabled, f"field is {'enabled' if expected_enabled else 'disabled'}"

    raise NexUIError(f"Unsupported success assertion type: {assertion_type}")


def gather_text_haystack(artifacts: SnapshotArtifacts, artifact: str) -> str:
    if artifact not in TEXT_ASSERTION_ARTIFACTS:
        raise NexUIError(f"Unsupported text assertion artifact: {artifact}")

    if artifact == "reader_view":
        return artifacts.reader_view
    if artifact == "aria_snapshot":
        return artifacts.aria_snapshot
    if artifact == "dom":
        return artifacts.dom
    return "\n".join(
        [
            artifacts.metadata.get("title", ""),
            artifacts.metadata.get("url", ""),
            artifacts.reader_view,
            artifacts.aria_snapshot,
            artifacts.dom,
        ]
    )


def find_matching_candidate(
    candidates: list[dict[str, Any]],
    matcher: dict[str, Any],
) -> dict[str, Any] | None:
    for candidate in candidates:
        if candidate_matches(candidate, matcher):
            return candidate
    return None


def candidate_matches(candidate: dict[str, Any], matcher: dict[str, Any]) -> bool:
    for key, expected in matcher.items():
        actual = candidate.get(key)
        if key == "states":
            if not isinstance(expected, dict):
                return False
            actual_states = actual if isinstance(actual, dict) else {}
            for state_key, state_expected in expected.items():
                if actual_states.get(state_key) != state_expected:
                    return False
            continue

        if isinstance(expected, str):
            if normalize_text(actual).casefold() != normalize_text(expected).casefold():
                return False
            continue

        if actual != expected:
            return False
    return True


def normalize_text(value: Any) -> str:
    return str(value or "").replace("\n", " ").replace("\r", " ").strip()


def manifest_has_trace_status_assertion(task: TaskPackage) -> bool:
    for assertion in task.success_assertions:
        if assertion.get("type") == "trace_status_is":
            return True
    for branch in task.success_any_of:
        for assertion in branch:
            if assertion.get("type") == "trace_status_is":
                return True
    return False


def resolve_last_action(trace: dict[str, Any]) -> dict[str, Any]:
    steps = trace.get("steps", [])
    if not steps:
        return {}
    return dict(steps[-1].get("submission", {}).get("action", {}))
