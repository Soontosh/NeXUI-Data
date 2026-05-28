from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nexui.io import NexUIError
from nexui.runner import run_task
from nexui.scoring import load_trace, score_trace
from nexui.source_runtime import reseed_source
from nexui.task import TaskPackage, validate_task_metadata


@dataclass(frozen=True)
class ValidationResult:
    task_id: str
    trace_source: str
    score: dict[str, Any]
    assertion_count: int
    any_of_branch_count: int


def validate_task_package(
    task: TaskPackage,
    *,
    trace_path: str | None = None,
    agent_name: str = "oracle",
    max_steps: int = 50,
    reseed_source_runtime: bool = False,
    agent_options: dict[str, Any] | None = None,
) -> ValidationResult:
    metadata_errors = validate_task_metadata(task)
    if metadata_errors:
        raise NexUIError("Task metadata validation failed:\n- " + "\n- ".join(metadata_errors))

    if trace_path:
        trace = load_trace(trace_path)
        trace_source = trace_path
    else:
        if task.requires_source_reset and not reseed_source_runtime:
            raise NexUIError(
                f"Task {task.task_id!r} requires a clean source state; rerun with --reseed-source."
            )
        if reseed_source_runtime:
            if not task.source_surface:
                raise NexUIError(f"Task {task.task_id!r} does not declare source_surface for reseed resolution.")
            reseed_source(task.source_surface)
        trace, _score = run_task(
            task,
            agent_name=agent_name,
            max_steps=max_steps,
            agent_options=agent_options,
        )
        trace_source = f"generated:{agent_name}"

    score = score_trace(task, trace)
    return ValidationResult(
        task_id=task.task_id,
        trace_source=trace_source,
        score=score,
        assertion_count=len(task.success_assertions),
        any_of_branch_count=len(task.success_any_of),
    )
