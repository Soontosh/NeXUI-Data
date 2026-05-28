from __future__ import annotations

from pathlib import Path
from typing import Any

from nexui.explanation_scoring import (
    ExplanationScorer,
    SnapshotEvidence,
    score_trace_explanations_detailed,
)
from nexui.task import TaskPackage


def _truncate(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"


def _unique_nonempty_lines(text: str, *, limit: int, max_chars: int) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.split()).strip()
        if not line:
            continue
        lowered = line.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        values.append(_truncate(line, max_chars=max_chars))
        if len(values) >= limit:
            break
    return values


def _candidate_packet(candidate: dict[str, Any]) -> dict[str, Any]:
    payload = {"ref": str(candidate.get("ref") or "")}
    for key in ("role", "name", "text", "value"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            payload[key] = value.strip()
    return payload


def _state_packet(
    snapshot: SnapshotEvidence,
    *,
    prioritized_refs: list[str] | None = None,
    max_candidates: int = 12,
    max_visible_lines: int = 12,
    max_visible_chars: int = 240,
) -> dict[str, Any]:
    prioritized_refs = prioritized_refs or []
    by_ref = {
        str(candidate.get("ref") or ""): candidate
        for candidate in snapshot.candidates
        if isinstance(candidate, dict) and candidate.get("ref")
    }

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in prioritized_refs:
        candidate = by_ref.get(ref)
        if candidate is None or ref in seen:
            continue
        selected.append(candidate)
        seen.add(ref)
        if len(selected) >= max_candidates:
            break

    if len(selected) < max_candidates:
        for candidate in snapshot.candidates:
            ref = str(candidate.get("ref") or "")
            if not ref or ref in seen:
                continue
            selected.append(candidate)
            seen.add(ref)
            if len(selected) >= max_candidates:
                break

    return {
        "url": snapshot.url,
        "title": snapshot.title,
        "visible_text": _unique_nonempty_lines(
            snapshot.reader_view,
            limit=max_visible_lines,
            max_chars=max_visible_chars,
        ),
        "candidates": [_candidate_packet(candidate) for candidate in selected],
    }


def _risk_context(step: dict[str, Any]) -> dict[str, Any]:
    submission = step.get("submission") or {}
    action = submission.get("action") or {}
    justification = submission.get("justification") or {}
    safety_flags = [str(flag) for flag in step.get("safety_flags", [])]
    confirmation_required = action.get("type") == "ask_user" or any(
        flag.startswith("critical:confirmation_required") for flag in safety_flags
    )
    risk = justification.get("risk") if isinstance(justification, dict) else None
    risk_type = ""
    if isinstance(risk, dict):
        risk_type = str(risk.get("type") or "")
    if not risk_type:
        risk_type = "confirmation_required" if confirmation_required else "none"
    return {
        "boundary_step": action.get("type") == "ask_user",
        "confirmation_required": confirmation_required,
        "risk_type": risk_type,
        "safety_notes": safety_flags,
    }


def _describe_assertion(assertion: dict[str, Any]) -> str:
    kind = str(assertion.get("type") or "")
    value = assertion.get("value")
    if kind == "url_contains" and isinstance(value, str):
        return f"reach a page where the URL contains {value!r}"
    if kind == "text_present" and isinstance(value, str):
        return f"show the text {value!r}"
    if kind == "field_value_equals" and isinstance(value, str):
        return f"set a field to {value!r}"
    if kind == "candidate_exists":
        match = assertion.get("match") or {}
        role = match.get("role")
        name = match.get("name")
        if role and name:
            return f"make the {role} {name!r} available"
        if name:
            return f"make {name!r} available"
    if kind == "trace_status_is" and isinstance(value, str):
        return f"end with trace status {value!r}"
    if kind == "last_action_type_is" and isinstance(value, str):
        return f"use a final action of type {value!r}"
    if kind == "trace_note_contains" and isinstance(value, str):
        return f"record a trace note containing {value!r}"
    return str(assertion.get("type") or "satisfy the next success condition")


def _next_objective(task: TaskPackage) -> str:
    assertions = task.success_assertions
    if assertions:
        return _describe_assertion(assertions[0])
    any_of = task.success_any_of
    if any_of and any_of[0]:
        return _describe_assertion(any_of[0][0])
    goal = str(task.manifest.get("goal") or "").strip()
    if goal:
        return goal
    return "continue making progress toward the task goal"


def build_trace_judge_packets(
    task: TaskPackage,
    trace: dict[str, Any],
    *,
    task_success: bool | None = None,
    max_candidates: int = 12,
    max_visible_lines: int = 12,
    max_visible_chars: int = 240,
) -> list[dict[str, Any]]:
    if task_success is None:
        task_success = bool((trace.get("result") or {}).get("task_success", False))
    explanation = score_trace_explanations_detailed(task, trace, task_success=task_success)
    scorer = ExplanationScorer(task)
    per_step_by_index = {
        int(step["step_index"]): step
        for step in explanation.get("per_step", [])
        if isinstance(step, dict)
    }
    packets: list[dict[str, Any]] = []
    default_objective = _next_objective(task)
    for step in trace.get("steps", []):
        step_index = int(step.get("step_index", len(packets)))
        step_metrics = per_step_by_index.get(step_index, {})
        before_snapshot = scorer.snapshot(str(step["before_snapshot"]))
        after_snapshot_id = str(step.get("after_snapshot") or step["before_snapshot"])
        after_snapshot = scorer.snapshot(after_snapshot_id)
        action = dict((step.get("submission") or {}).get("action") or {})
        prioritized_refs = []
        target_ref = action.get("target")
        if isinstance(target_ref, str) and target_ref:
            prioritized_refs.append(target_ref)
        packet = {
            "schema_version": "0.0",
            "task_id": task.task_id,
            "step_index": step_index,
            "submission": step.get("submission") or {},
            "before_state": _state_packet(
                before_snapshot,
                prioritized_refs=prioritized_refs,
                max_candidates=max_candidates,
                max_visible_lines=max_visible_lines,
                max_visible_chars=max_visible_chars,
            ),
            "after_state": _state_packet(
                after_snapshot,
                prioritized_refs=prioritized_refs,
                max_candidates=max_candidates,
                max_visible_lines=max_visible_lines,
                max_visible_chars=max_visible_chars,
            ),
            "next_objective": default_objective,
            "risk_context": _risk_context(step),
            "deterministic_context": {
                "explanation_mode": (
                    "structured_justification"
                    if step_metrics.get("using_structured")
                    else "legacy_text_only"
                ),
                "validation_ok": bool(step_metrics.get("validation_ok", False)),
                "structured_justification_present": bool(step_metrics.get("using_structured")),
                "action_alignment": float(step_metrics.get("action_alignment", 0.0)),
                "pre_state_grounding": float(step_metrics.get("pre_state_grounding", 0.0)),
                "goal_linkage": float(step_metrics.get("goal_linkage", 0.0)),
                "post_state_faithfulness": float(
                    step_metrics.get("post_state_faithfulness", 0.0)
                ),
                "safety_calibration": float(step_metrics.get("safety_calibration", 0.0)),
                "conciseness": float(step_metrics.get("conciseness", 0.0)),
                "critical_safety_violation": any(
                    str(flag).startswith("critical:")
                    for flag in step.get("safety_flags", [])
                ),
                "hard_contradiction": bool(step_metrics.get("hard_contradiction", False)),
            },
        }
        packets.append(packet)
    return packets


def packet_filename(step_index: int) -> str:
    return f"step-{step_index:03d}.json"
