#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_ROOT = REPO_ROOT / "examples" / "tasks"

PRODUCTION_SOURCE_IDS = {
    "w3c-bad",
    "accessible-university",
    "the-internet",
    "demoqa",
    "govuk-service-prototype-local",
    "hmrc-income-change-prototype-local",
    "demoblaze",
    "parabank",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def oracle_action_count(task_dir: Path) -> int:
    count = 0
    for line in (task_dir / "oracle" / "trajectory.jsonl").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        step = json.loads(stripped)
        action = (step.get("action") or {}).get("type")
        if action not in {"finish", "ask_user", "wait"}:
            count += 1
    return count


def infer_authentication_required(task_id: str, source_id: str, tags: set[str]) -> bool:
    if source_id != "parabank":
        return False
    if task_id.startswith("parabank-register-"):
        return False
    return "auth" in tags or any(
        token in task_id
        for token in (
            "account-history",
            "find-transactions",
            "bill-pay",
            "request-loan",
            "transfer-boundary",
        )
    )


def infer_cross_view_verification(task_id: str, tags: set[str]) -> bool:
    return (
        "check-answers" in tags
        or "state-propagation" in tags
        or "cart" in tags
        or "row-add" in tags
        or task_id.endswith("-search-001")
    )


def infer_summary_edit_propagation(task_id: str, tags: set[str]) -> bool:
    return (
        "edit-loop" in tags
        or "state-propagation" in tags
        or "multi-edit" in tags
        or "check-answers" in tags and ("change-" in task_id or "from-summary" in task_id)
    )


def infer_conditional_ui(source_id: str, task_id: str, tags: set[str]) -> bool:
    return (
        "branching" in tags
        or "validation" in tags
        or "validation-recovery" in tags
        or "numeric-consistency" in tags
        or "contact-method" in task_id
        or "more-than-one-source" in task_id
        or source_id in {"govuk-service-prototype-local", "hmrc-income-change-prototype-local"}
        and any(
            token in task_id
            for token in (
                "updates",
                "send-boundary",
                "send-update",
                "stopped-income",
            )
        )
    )


def infer_async_or_modal(tags: set[str]) -> bool:
    return bool(
        {
            "modal",
            "dialog",
            "async",
            "wait",
            "dynamic-content",
            "dynamic-controls",
            "postconditions",
        }
        & tags
    )


def infer_dense_controls(task_id: str, tags: set[str]) -> bool:
    return (
        "table" in tags
        or "disambiguation" in tags
        or "confusing-links" in tags
        or "product-disambiguation" in tags
        or "filter" in tags
        or "click-here" in task_id
    )


def infer_band(source_id: str, task_id: str, tags: set[str], meaningful_actions: int, risk_level: str) -> str:
    if source_id in {"w3c-bad"}:
        return "easy"

    if source_id == "accessible-university":
        if {"modal", "dialog", "confusing-links", "disambiguation"} & tags:
            return "medium"
        return "easy"

    if source_id == "the-internet":
        if "login" in tags or "keyboard" in tags or meaningful_actions >= 3:
            return "medium"
        return "easy"

    if source_id == "demoqa":
        if "row-add" in tags or meaningful_actions >= 8:
            return "hard"
        return "medium"

    if source_id == "govuk-service-prototype-local":
        if "multi-edit" in tags:
            return "very_hard"
        if risk_level == "confirmation_required" or "edit-loop" in tags or meaningful_actions >= 9:
            return "hard"
        return "medium"

    if source_id == "hmrc-income-change-prototype-local":
        if risk_level == "confirmation_required" or meaningful_actions >= 20 or "state-propagation" in tags:
            return "very_hard"
        return "hard"

    if source_id == "demoblaze":
        if "very-hard" in tags:
            return "very_hard"
        if "hard" in tags or risk_level == "confirmation_required" or meaningful_actions >= 5:
            return "hard"
        if meaningful_actions >= 3 or {"modal", "product-detail"} & tags:
            return "medium"
        return "easy"

    if source_id == "parabank":
        if task_id == "parabank-register-open-001":
            return "easy"
        if risk_level == "confirmation_required" or meaningful_actions >= 10:
            return "hard"
        return "medium"

    return "medium"


def update_task(task_dir: Path) -> tuple[str, bool]:
    task_path = task_dir / "task.yaml"
    payload = load_json(task_path)
    source_id = payload.get("source", {}).get("site_id", "")
    if source_id not in PRODUCTION_SOURCE_IDS and source_id != "packaged-demo":
        return task_dir.name, False

    original = json.dumps(payload, sort_keys=True)
    tags = set(payload.get("tags", []))
    meaningful_actions = oracle_action_count(task_dir)
    risk_level = payload.get("risk_level", "safe")

    if source_id == "packaged-demo":
        payload.setdefault("source_surface", "packaged-demo")
        payload.setdefault("split", "unassigned")
        payload.setdefault("stability_runs_passed", 0)
        payload.setdefault("difficulty_band", "easy")
        payload.setdefault(
            "difficulty_dimensions",
            {
                "authentication_required": False,
                "meaningful_action_count": meaningful_actions,
                "cross_view_verification": False,
                "summary_edit_propagation": False,
                "conditional_ui": False,
                "async_or_modal": False,
                "dense_controls": False,
                "safety_boundary": False,
            },
        )
    else:
        payload["source_surface"] = source_id
        payload["split"] = "dev"
        payload["stability_runs_passed"] = max(int(payload.get("stability_runs_passed", 0)), 1)
        payload["difficulty_band"] = infer_band(source_id, task_dir.name, tags, meaningful_actions, risk_level)
        payload["difficulty_dimensions"] = {
            "authentication_required": infer_authentication_required(task_dir.name, source_id, tags),
            "meaningful_action_count": meaningful_actions,
            "cross_view_verification": infer_cross_view_verification(task_dir.name, tags),
            "summary_edit_propagation": infer_summary_edit_propagation(task_dir.name, tags),
            "conditional_ui": infer_conditional_ui(source_id, task_dir.name, tags),
            "async_or_modal": infer_async_or_modal(tags),
            "dense_controls": infer_dense_controls(task_dir.name, tags),
            "safety_boundary": risk_level == "confirmation_required",
        }

    updated = json.dumps(payload, sort_keys=True)
    if updated != original:
        write_json(task_path, payload)
        return task_dir.name, True
    return task_dir.name, False


def main() -> int:
    updated = []
    unchanged = []
    for task_dir in sorted(path for path in TASKS_ROOT.iterdir() if (path / "task.yaml").exists()):
        task_id, did_update = update_task(task_dir)
        if did_update:
            updated.append(task_id)
        else:
            unchanged.append(task_id)

    print(f"Updated {len(updated)} tasks")
    for task_id in updated:
        print(f"  {task_id}")
    print(f"Unchanged {len(unchanged)} tasks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
