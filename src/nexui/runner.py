from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from nexui.agents import make_agent
from nexui.io import RuntimeAgentError, write_json
from nexui.justification import validate_justification_payload
from nexui.scoring import evaluate_step_safety, score_trace
from nexui.task import TaskPackage


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_submission(task: TaskPackage, submission: dict, observation: dict) -> dict:
    action = submission.get("action")
    explanation = submission.get("explanation")
    if not isinstance(action, dict):
        return {"status": "invalid_action", "message": "submission.action must be an object"}
    if not isinstance(explanation, str) or not explanation.strip():
        return {"status": "invalid_action", "message": "submission.explanation must be a non-empty string"}
    justification = submission.get("justification")
    if justification is not None:
        justification_error = validate_justification_payload(justification)
        if justification_error:
            return {"status": "invalid_action", "message": justification_error}

    action_type = action.get("type")
    if action_type not in task.allowed_actions:
        return {"status": "blocked_by_policy", "message": f"Action type {action_type!r} is not allowed"}

    candidate_refs = {candidate["ref"] for candidate in observation.get("candidates", [])}

    if action_type in {"click", "type", "select", "focus"} and "target" not in action:
        return {"status": "invalid_target", "message": "action target is required"}
    if action_type in {"click", "type", "select", "focus"} and not isinstance(action.get("target"), str):
        return {"status": "invalid_target", "message": "action target must be a string"}
    if action_type in {"click", "type", "select", "focus"} and action["target"] not in candidate_refs:
        return {
            "status": "invalid_target",
            "message": f"Target {action['target']!r} is not available in snapshot {observation['snapshot_id']}",
        }

    if action_type == "type" and (
        "text" not in action or not isinstance(action.get("text"), str) or not action["text"]
    ):
        return {"status": "invalid_action", "message": "type action requires non-empty text"}

    if action_type == "select" and (
        "option" not in action or not isinstance(action.get("option"), str) or not action["option"]
    ):
        return {"status": "invalid_action", "message": "select action requires a non-empty option"}

    if action_type == "press" and (
        "key" not in action or not isinstance(action.get("key"), str) or not action["key"]
    ):
        return {"status": "invalid_action", "message": "press action requires a non-empty key"}

    if action_type == "scroll" and (
        "direction" not in action
        or not isinstance(action.get("direction"), str)
        or not action["direction"]
    ):
        return {"status": "invalid_action", "message": "scroll action requires a non-empty direction"}

    if action_type == "ask_user" and (
        "question" not in action
        or not isinstance(action.get("question"), str)
        or not action["question"].strip()
    ):
        return {"status": "invalid_action", "message": "ask_user action requires a non-empty question"}

    if action_type == "finish" and (
        "summary" not in action
        or not isinstance(action.get("summary"), str)
        or not action["summary"].strip()
    ):
        return {"status": "invalid_action", "message": "finish action requires a non-empty summary"}

    return {"status": "ok"}


def run_task(
    task: TaskPackage,
    agent_name: str = "oracle",
    max_steps: int = 50,
    agent_options: dict[str, Any] | None = None,
    step_callback: Callable[[dict[str, Any], dict[str, Any]], dict[str, str] | None] | None = None,
) -> tuple[dict, dict]:
    agent = make_agent(agent_name, task, options=agent_options)
    agent_description = (
        agent.describe() if hasattr(agent, "describe") else {
            "agent_id": agent_name,
            "agent_type": "builtin",
            "version": "0.0.0",
        }
    )
    current_snapshot = task.start_snapshot
    trace = {
        "schema_version": task.manifest["schema_version"],
        "run_id": str(uuid4()),
        "task_id": task.task_id,
        "task": {
            "root": str(task.root),
            "title": task.manifest["title"],
            "start_snapshot": task.start_snapshot,
            "source": task.manifest["source"],
        },
        "agent": agent_description,
        "started_at": _utc_now(),
        "initial_snapshot": current_snapshot,
        "steps": [],
        "result": {
            "status": "failed",
            "task_success": False,
            "critical_safety_violation": False,
            "final_summary": "",
            "termination_reason": "",
        },
    }

    for step_index in range(max_steps):
        observation = task.build_observation(current_snapshot)
        try:
            submission = agent.act(observation)
        except RuntimeAgentError as exc:
            trace["result"]["status"] = "runtime_error"
            trace["result"]["termination_reason"] = str(exc)
            trace["result"]["runtime_error"] = {
                "provider": exc.provider,
                "category": exc.category,
                "retryable": exc.retryable,
                "step_index": step_index,
                "snapshot_id": current_snapshot,
                "message": str(exc),
            }
            agent_step_metadata = getattr(agent, "last_step_metadata", None)
            if agent_step_metadata:
                trace["result"]["runtime_error"]["agent_metadata"] = agent_step_metadata
            if exc.details:
                trace["result"]["runtime_error"]["details"] = exc.details
            break
        validation = _validate_submission(task, submission, observation)
        safety_flags = evaluate_step_safety(task, submission, observation)
        step_record = {
            "step_index": step_index,
            "before_snapshot": current_snapshot,
            "after_snapshot": None,
            "submission": submission,
            "validation": validation,
            "safety_flags": safety_flags,
            "notes": [],
        }
        agent_step_metadata = getattr(agent, "last_step_metadata", None)
        if agent_step_metadata:
            step_record["agent_metadata"] = agent_step_metadata

        if validation["status"] != "ok":
            step_record["notes"].append(validation.get("message", "validation failed"))
            trace["steps"].append(step_record)
            trace["result"]["status"] = "failed"
            trace["result"]["termination_reason"] = validation.get("message", "validation failed")
            break

        action = submission["action"]
        action_type = action["type"]

        if action_type == "finish":
            step_record["after_snapshot"] = current_snapshot
            if hasattr(agent, "record_outcome"):
                agent.record_outcome(current_snapshot)
            trace["steps"].append(step_record)
            if step_callback is not None:
                stop_signal = step_callback(trace, step_record)
                if stop_signal is not None:
                    trace["result"]["status"] = stop_signal["status"]
                    trace["result"]["termination_reason"] = stop_signal["reason"]
                    break
            trace["result"]["status"] = "completed"
            trace["result"]["final_summary"] = action["summary"]
            trace["result"]["termination_reason"] = "agent_finished"
            break

        if action_type == "ask_user":
            step_record["after_snapshot"] = current_snapshot
            if hasattr(agent, "record_outcome"):
                agent.record_outcome(current_snapshot)
            trace["steps"].append(step_record)
            if step_callback is not None:
                stop_signal = step_callback(trace, step_record)
                if stop_signal is not None:
                    trace["result"]["status"] = stop_signal["status"]
                    trace["result"]["termination_reason"] = stop_signal["reason"]
                    break
            trace["result"]["status"] = "stopped"
            trace["result"]["termination_reason"] = "agent_requested_user_confirmation"
            break

        transition = task.find_transition(current_snapshot, action)
        if transition is None:
            step_record["validation"] = {
                "status": "invalid_action",
                "message": f"No transition found from {current_snapshot} for action {action}"
            }
            step_record["notes"].append("The action did not match any packaged transition.")
            trace["steps"].append(step_record)
            trace["result"]["status"] = "failed"
            trace["result"]["termination_reason"] = "transition_not_found"
            break

        current_snapshot = transition["to"]
        step_record["after_snapshot"] = current_snapshot
        if hasattr(agent, "record_outcome"):
            agent.record_outcome(current_snapshot)
        if transition.get("notes"):
            step_record["notes"].extend(transition["notes"])
        trace["steps"].append(step_record)
        if step_callback is not None:
            stop_signal = step_callback(trace, step_record)
            if stop_signal is not None:
                trace["result"]["status"] = stop_signal["status"]
                trace["result"]["termination_reason"] = stop_signal["reason"]
                break
    else:
        trace["result"]["status"] = "timeout"
        trace["result"]["termination_reason"] = "max_steps_exceeded"

    trace["ended_at"] = _utc_now()
    score = score_trace(task, trace)
    trace["result"]["task_success"] = score["metrics"]["task_success"]
    trace["result"]["critical_safety_violation"] = score["metrics"]["critical_safety_violation"]
    return trace, score


def save_trace(path: str, trace: dict) -> None:
    write_json(__import__("pathlib").Path(path), trace)
