#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nexui.dataset import (
    default_splits_root,
    default_tasks_root,
    list_task_inventory,
    load_split_manifest,
)
from nexui.io import NexUIError, write_json, write_text
from nexui.openai_agent import OpenAIAgent, OpenAIAgentConfig
from nexui.runner import run_task, save_trace
from nexui.scoring import save_score
from nexui.source_runtime import reseed_source
from nexui.task import load_task


OPENAI_PRESETS: dict[str, dict[str, Any]] = {
    "o3": {
        "model": "o3",
        "prompt_profile": "candidates_ax",
        "prompt_league": "platinum",
        "reasoning_effort": "low",
        "text_verbosity": "low",
        "max_output_tokens": 1024,
    },
    "o4-mini": {
        "model": "o4-mini",
        "prompt_profile": "candidates_ax",
        "prompt_league": "platinum",
        "reasoning_effort": "low",
        "text_verbosity": "low",
        "max_output_tokens": 1024,
    },
    "gpt-5-mini": {
        "model": "gpt-5-mini",
        "prompt_profile": "candidates_ax",
        "prompt_league": "platinum",
        "reasoning_effort": "low",
        "text_verbosity": "low",
        "max_output_tokens": 1024,
    },
    "gpt-5.4-mini": {
        "model": "gpt-5.4-mini",
        "prompt_profile": "candidates_ax",
        "prompt_league": "platinum",
        "reasoning_effort": "low",
        "text_verbosity": "low",
        "max_output_tokens": 1024,
    },
}


MODEL_PRICING_PER_M_TOKENS: dict[str, dict[str, float]] = {
    "o3": {"input": 2.00, "output": 8.00},
    "o4-mini": {"input": 1.10, "output": 4.40},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gpt-5.4-mini": {"input": 0.75, "output": 4.50},
}


REASONING_TOKENS_PER_STEP: dict[str, int] = {
    "none": 0,
    "minimal": 48,
    "low": 96,
    "medium": 160,
    "high": 256,
    "xhigh": 384,
}


@dataclass(frozen=True)
class EstimateRecord:
    model: str
    task_id: str
    split: str
    source_surface: str
    difficulty_band: str
    oracle_step_count: int
    prompt_profile: str
    prompt_league: str
    reasoning_effort: str
    max_output_tokens: int
    prompt_char_count: int
    response_char_count: int
    input_tokens_low: int
    input_tokens_mid: int
    input_tokens_high: int
    visible_output_tokens_mid: int
    output_tokens_mid: int
    output_tokens_upper_bound: int
    estimated_cost_low_usd: float
    estimated_cost_mid_usd: float
    estimated_cost_high_usd: float


@dataclass(frozen=True)
class RunRecord:
    model: str
    task_id: str
    split: str
    source_surface: str
    difficulty_band: str
    prompt_profile: str
    prompt_league: str
    reasoning_effort: str
    max_output_tokens: int
    passed: bool
    task_success: bool
    safety_pass: bool
    invalid_action_count: int
    step_count: int
    elapsed_s: float
    prompt_token_count: int
    visible_output_token_count: int
    thought_token_count: int
    billed_output_token_count: int
    estimated_cost_usd: float
    trace_path: str | None
    score_path: str | None
    error: str | None
    notes: list[str]
    termination_reason: str | None
    run_status: str | None
    final_snapshot: str | None
    explanation_mode: str | None
    explanation_overall: float | None
    first_invalid_step_index: int | None
    first_invalid_message: str | None
    first_invalid_action_type: str | None
    first_invalid_target: str | None
    first_invalid_before_snapshot: str | None
    action_sequence: list[str]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_commit(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:  # noqa: BLE001
        return None
    return result.stdout.strip() or None


def _load_task_ids(split: str, tasks_root: Path, splits_root: Path) -> list[str]:
    if split == "production":
        inventory = list_task_inventory(tasks_root=str(tasks_root), splits_root=str(splits_root))
        return [item["task_id"] for item in inventory if item["production"]]
    manifest = load_split_manifest(splits_root / f"{split}.json")
    return list(manifest.get("task_ids", []))


def _select_models(requested: list[str]) -> list[str]:
    unknown = [model for model in requested if model not in OPENAI_PRESETS]
    if unknown:
        raise NexUIError(f"Unknown OpenAI baseline model(s): {', '.join(unknown)}")
    return requested


def _char_tokens_mid(char_count: int) -> int:
    return max(1, round(char_count / 4.0))


def _char_tokens_low(char_count: int) -> int:
    return max(1, round(char_count / 4.5))


def _char_tokens_high(char_count: int) -> int:
    return max(1, round(char_count / 3.5))


def _estimate_cost(model: str, input_tokens: int, billed_output_tokens: int) -> float:
    pricing = MODEL_PRICING_PER_M_TOKENS[model]
    return round(
        (input_tokens / 1_000_000.0) * pricing["input"]
        + (billed_output_tokens / 1_000_000.0) * pricing["output"],
        6,
    )


def _usage_from_trace(trace: dict[str, Any]) -> dict[str, int]:
    prompt = 0
    visible = 0
    thoughts = 0
    for step in trace.get("steps", []):
        usage = ((step.get("agent_metadata") or {}).get("usage") or {})
        prompt += int(usage.get("prompt_token_count") or 0)
        visible += int(usage.get("candidates_token_count") or 0)
        thoughts += int(usage.get("thoughts_token_count") or 0)
    return {
        "prompt_token_count": prompt,
        "visible_output_token_count": visible,
        "thought_token_count": thoughts,
        "billed_output_token_count": visible + thoughts,
    }


def _first_invalid_step(trace: dict[str, Any]) -> dict[str, Any] | None:
    for step in trace.get("steps", []):
        validation = step.get("validation") or {}
        if validation.get("status") != "ok":
            return step
    return None


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")


def _final_snapshot(trace: dict[str, Any], start_snapshot: str) -> str:
    final_snapshot = start_snapshot
    for step in trace.get("steps", []):
        after_snapshot = step.get("after_snapshot")
        if after_snapshot is not None:
            final_snapshot = after_snapshot
    return final_snapshot


def _oracle_prompt_cost(task_dir: Path, split: str, options: dict[str, Any]) -> EstimateRecord:
    task = load_task(task_dir)
    config = OpenAIAgentConfig.from_options(options)
    agent = OpenAIAgent(task, config)
    current_snapshot = task.start_snapshot
    prompt_chars = 0
    response_chars = 0
    completed_steps = 0

    for step in task.oracle_steps:
        observation = task.build_observation(current_snapshot)
        prompt = agent._build_prompt(observation)
        prompt_chars += len(prompt)
        response_chars += len(json.dumps(step, ensure_ascii=True, sort_keys=True))
        completed_steps += 1

        agent.history.append(
            {
                "before_snapshot": current_snapshot,
                "after_snapshot": current_snapshot,
                "action": step.get("action", {}),
            }
        )

        action = step.get("action") or {}
        action_type = str(action.get("type") or "")
        if action_type in {"finish", "ask_user"}:
            agent.record_outcome(current_snapshot)
            break

        transition = task.find_transition(current_snapshot, action)
        if transition is None:
            raise NexUIError(
                f"Oracle transition missing while estimating {task.task_id!r} from {current_snapshot}."
            )
        current_snapshot = transition["to"]
        agent.record_outcome(current_snapshot)

    input_low = _char_tokens_low(prompt_chars)
    input_mid = _char_tokens_mid(prompt_chars)
    input_high = _char_tokens_high(prompt_chars)
    visible_mid = _char_tokens_mid(response_chars)
    reasoning_buffer = REASONING_TOKENS_PER_STEP[config.reasoning_effort] * completed_steps
    output_mid = min(
        config.max_output_tokens * completed_steps,
        visible_mid + reasoning_buffer,
    )
    output_upper = config.max_output_tokens * completed_steps

    return EstimateRecord(
        model=config.model,
        task_id=task.task_id,
        split=split,
        source_surface=task.source_surface,
        difficulty_band=str(task.manifest.get("difficulty_band", "unknown")),
        oracle_step_count=completed_steps,
        prompt_profile=config.prompt_profile,
        prompt_league=config.prompt_league,
        reasoning_effort=config.reasoning_effort,
        max_output_tokens=config.max_output_tokens,
        prompt_char_count=prompt_chars,
        response_char_count=response_chars,
        input_tokens_low=input_low,
        input_tokens_mid=input_mid,
        input_tokens_high=input_high,
        visible_output_tokens_mid=visible_mid,
        output_tokens_mid=output_mid,
        output_tokens_upper_bound=output_upper,
        estimated_cost_low_usd=_estimate_cost(config.model, input_low, visible_mid),
        estimated_cost_mid_usd=_estimate_cost(config.model, input_mid, output_mid),
        estimated_cost_high_usd=_estimate_cost(config.model, input_high, output_upper),
    )


def _run_one(
    *,
    task_dir: Path,
    split: str,
    options: dict[str, Any],
    reseed_required_tasks: bool,
    trace_dir: Path | None,
    score_dir: Path | None,
) -> RunRecord:
    task = load_task(task_dir)
    if reseed_required_tasks and task.requires_source_reset and task.source_surface:
        reseed_source(task.source_surface)

    max_steps = max(10, min(50, len(task.oracle_steps) * 2 + 4))
    started = time.perf_counter()
    trace_path: Path | None = None
    score_path: Path | None = None
    try:
        trace, score = run_task(
            task,
            agent_name="openai",
            max_steps=max_steps,
            agent_options=options,
        )
        elapsed_s = round(time.perf_counter() - started, 3)
        usage = _usage_from_trace(trace)
        invalid_step = _first_invalid_step(trace)
        if trace_dir is not None:
            trace_path = trace_dir / options["model"] / f"{task.task_id}.json"
            save_trace(trace_path, trace)
        if score_dir is not None:
            score_path = score_dir / options["model"] / f"{task.task_id}.json"
            save_score(score_path, score)
        return RunRecord(
            model=str(options["model"]),
            task_id=task.task_id,
            split=split,
            source_surface=task.source_surface,
            difficulty_band=str(task.manifest.get("difficulty_band", "unknown")),
            prompt_profile=str(options.get("prompt_profile") or ""),
            prompt_league=str(options.get("prompt_league") or ""),
            reasoning_effort=str(options.get("reasoning_effort") or ""),
            max_output_tokens=int(options.get("max_output_tokens") or 0),
            passed=bool(score["passed"]),
            task_success=bool(score["metrics"]["task_success"]),
            safety_pass=bool(score["metrics"]["safety_pass"]),
            invalid_action_count=int(score["metrics"]["invalid_action_count"]),
            step_count=len(trace.get("steps", [])),
            elapsed_s=elapsed_s,
            prompt_token_count=usage["prompt_token_count"],
            visible_output_token_count=usage["visible_output_token_count"],
            thought_token_count=usage["thought_token_count"],
            billed_output_token_count=usage["billed_output_token_count"],
            estimated_cost_usd=_estimate_cost(
                str(options["model"]),
                usage["prompt_token_count"],
                usage["billed_output_token_count"],
            ),
            trace_path=str(trace_path) if trace_path is not None else None,
            score_path=str(score_path) if score_path is not None else None,
            error=None,
            notes=list(score.get("notes", [])),
            termination_reason=trace.get("result", {}).get("termination_reason"),
            run_status=trace.get("result", {}).get("status"),
            final_snapshot=_final_snapshot(trace, task.start_snapshot),
            explanation_mode=score.get("explanation_mode"),
            explanation_overall=float(score["metrics"]["explanation_overall"]),
            first_invalid_step_index=None if invalid_step is None else int(invalid_step["step_index"]),
            first_invalid_message=None
            if invalid_step is None
            else str((invalid_step.get("validation") or {}).get("message") or ""),
            first_invalid_action_type=None
            if invalid_step is None
            else str((((invalid_step.get("submission") or {}).get("action") or {}).get("type") or "")),
            first_invalid_target=None
            if invalid_step is None
            else str((((invalid_step.get("submission") or {}).get("action") or {}).get("target") or "")),
            first_invalid_before_snapshot=None
            if invalid_step is None
            else str(invalid_step.get("before_snapshot") or ""),
            action_sequence=[
                str((((step.get("submission") or {}).get("action") or {}).get("type") or ""))
                for step in trace.get("steps", [])
            ],
        )
    except Exception as exc:  # noqa: BLE001
        elapsed_s = round(time.perf_counter() - started, 3)
        return RunRecord(
            model=str(options["model"]),
            task_id=task.task_id,
            split=split,
            source_surface=task.source_surface,
            difficulty_band=str(task.manifest.get("difficulty_band", "unknown")),
            prompt_profile=str(options.get("prompt_profile") or ""),
            prompt_league=str(options.get("prompt_league") or ""),
            reasoning_effort=str(options.get("reasoning_effort") or ""),
            max_output_tokens=int(options.get("max_output_tokens") or 0),
            passed=False,
            task_success=False,
            safety_pass=False,
            invalid_action_count=0,
            step_count=0,
            elapsed_s=elapsed_s,
            prompt_token_count=0,
            visible_output_token_count=0,
            thought_token_count=0,
            billed_output_token_count=0,
            estimated_cost_usd=0.0,
            trace_path=None,
            score_path=None,
            error=str(exc),
            notes=[],
            termination_reason=None,
            run_status=None,
            final_snapshot=None,
            explanation_mode=None,
            explanation_overall=None,
            first_invalid_step_index=None,
            first_invalid_message=None,
            first_invalid_action_type=None,
            first_invalid_target=None,
            first_invalid_before_snapshot=None,
            action_sequence=[],
        )


def _write_estimate_summary(path: Path, estimates: list[EstimateRecord], models: list[str]) -> None:
    lines = [
        "# OpenAI Baseline Cost Estimate",
        "",
        f"- Generated at: `{_utc_now()}`",
        f"- Models: `{', '.join(models)}`",
        "",
        "| Model | Tasks | Oracle steps | Input tokens (mid) | Output tokens (mid) | Output upper bound | Cost low | Cost mid | Cost high |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model in models:
        rows = [row for row in estimates if row.model == model]
        lines.append(
            f"| `{model}` | {len(rows)} | {sum(row.oracle_step_count for row in rows)} | "
            f"{sum(row.input_tokens_mid for row in rows)} | {sum(row.output_tokens_mid for row in rows)} | "
            f"{sum(row.output_tokens_upper_bound for row in rows)} | "
            f"${sum(row.estimated_cost_low_usd for row in rows):.4f} | "
            f"${sum(row.estimated_cost_mid_usd for row in rows):.4f} | "
            f"${sum(row.estimated_cost_high_usd for row in rows):.4f} |"
        )
    write_text(path, "\n".join(lines) + "\n")


def _write_run_summary(path: Path, records: list[RunRecord], models: list[str]) -> None:
    summary = _build_run_summary(records=records, models=models)
    lines = [
        "# OpenAI Baseline Run Summary",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Tasks attempted per model: `{summary['task_count']}`",
        f"- Models: `{', '.join(summary['models'])}`",
        "",
        "## Model Summary",
        "",
        "| Model | Passes | Tasks | Pass rate | Avg steps | Invalid actions | Prompt tokens | Billed output tokens | Estimated cost | Avg explanation overall |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary["model_summaries"]:
        lines.append(
            f"| `{item['model']}` | {item['passes']} | {item['tasks']} | {item['pass_rate']:.1%} | "
            f"{item['avg_steps']:.2f} | {item['invalid_action_count']} | {item['prompt_token_count']} | "
            f"{item['billed_output_token_count']} | ${item['estimated_cost_usd']:.4f} | "
            f"{item['avg_explanation_overall']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Failure Summary",
            "",
            "| Model | Failure type | Count |",
            "|---|---|---:|",
        ]
    )
    for item in summary["failure_type_summaries"]:
        lines.append(
            f"| `{item['model']}` | `{item['failure_type']}` | {item['count']} |"
        )
    lines.extend(
        [
            "",
            "## Difficulty Breakdown",
            "",
            "| Model | Difficulty | Passes | Tasks | Pass rate |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for item in summary["difficulty_summaries"]:
        lines.append(
            f"| `{item['model']}` | `{item['difficulty_band']}` | {item['passes']} | {item['tasks']} | {item['pass_rate']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## Source Breakdown",
            "",
            "| Model | Source | Passes | Tasks | Pass rate |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for item in summary["source_summaries"]:
        lines.append(
            f"| `{item['model']}` | `{item['source_surface']}` | {item['passes']} | {item['tasks']} | {item['pass_rate']:.1%} |"
        )
    write_text(path, "\n".join(lines) + "\n")


def _build_run_summary(*, records: list[RunRecord], models: list[str]) -> dict[str, Any]:
    def group_by(keys: tuple[str, ...]) -> list[dict[str, Any]]:
        grouped: dict[tuple[Any, ...], list[RunRecord]] = {}
        for record in records:
            key = tuple(getattr(record, name) for name in keys)
            grouped.setdefault(key, []).append(record)
        rows = []
        for key, items in sorted(grouped.items()):
            passes = sum(1 for item in items if item.passed)
            explanation_values = [
                item.explanation_overall for item in items if item.explanation_overall is not None
            ]
            rows.append(
                {
                    **{name: value for name, value in zip(keys, key, strict=True)},
                    "tasks": len(items),
                    "passes": passes,
                    "pass_rate": passes / len(items),
                    "avg_steps": sum(item.step_count for item in items) / len(items),
                    "invalid_action_count": sum(item.invalid_action_count for item in items),
                    "prompt_token_count": sum(item.prompt_token_count for item in items),
                    "billed_output_token_count": sum(item.billed_output_token_count for item in items),
                    "estimated_cost_usd": round(sum(item.estimated_cost_usd for item in items), 6),
                    "avg_explanation_overall": 0.0
                    if not explanation_values
                    else sum(explanation_values) / len(explanation_values),
                }
            )
        return rows

    failure_type_rows = []
    for model in models:
        counts: dict[str, int] = {}
        for record in records:
            if record.model != model or record.passed:
                continue
            if record.error:
                label = f"runtime_error:{record.error.splitlines()[0][:80]}"
            elif record.first_invalid_message:
                label = f"invalid_action:{record.first_invalid_message[:80]}"
            elif not record.task_success:
                label = f"task_failure:{record.termination_reason or record.run_status or 'unknown'}"
            else:
                label = "other"
            counts[label] = counts.get(label, 0) + 1
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            failure_type_rows.append({"model": model, "failure_type": label, "count": count})

    return {
        "generated_at": _utc_now(),
        "models": models,
        "task_count": len({record.task_id for record in records}),
        "model_summaries": group_by(("model",)),
        "failure_type_summaries": failure_type_rows,
        "difficulty_summaries": group_by(("model", "difficulty_band")),
        "source_summaries": group_by(("model", "source_surface")),
        "records": [record.__dict__ for record in records],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Estimate or run OpenAI reasoning baselines on a NExUI split.",
    )
    parser.add_argument(
        "--split",
        default="validation",
        choices=["production", "dev", "validation", "test", "challenge"],
        help="Split manifest to evaluate",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=["o3", "o4-mini", "gpt-5-mini"],
        help="OpenAI models to estimate or run",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional cap on the number of tasks from the chosen split",
    )
    parser.add_argument(
        "--tasks-root",
        default=str(default_tasks_root()),
        help="Task root directory",
    )
    parser.add_argument(
        "--splits-root",
        default=str(default_splits_root()),
        help="Split manifests directory",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/baselines",
        help="Directory for JSON and Markdown outputs",
    )
    parser.add_argument(
        "--estimate-only",
        action="store_true",
        help="Only estimate cost from the packaged oracle path; do not call the OpenAI API",
    )
    parser.add_argument(
        "--save-traces",
        action="store_true",
        help="Persist per-task traces under the output directory when running live evaluations",
    )
    parser.add_argument(
        "--reseed-required-tasks",
        action="store_true",
        help="Run source reseed hooks before tasks marked requires_source_reset",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    models = _select_models(args.models)
    tasks_root = Path(args.tasks_root).resolve()
    splits_root = Path(args.splits_root).resolve()
    task_ids = _load_task_ids(args.split, tasks_root, splits_root)
    if args.limit is not None:
        task_ids = task_ids[: args.limit]
    if not task_ids:
        raise NexUIError(f"No task ids selected from split {args.split!r}.")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = Path(args.output_dir).resolve() / f"openai-{args.split}-{timestamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    trace_dir = output_root / "traces" if args.save_traces else None
    score_dir = output_root / "scores" if args.save_traces else None
    repo_root = _repo_root()
    manifest = {
        "generated_at": _utc_now(),
        "repo_root": str(repo_root),
        "git_commit": _git_commit(repo_root),
        "split": args.split,
        "task_count": len(task_ids),
        "task_ids": task_ids,
        "models": models,
        "model_presets": {model: dict(OPENAI_PRESETS[model]) for model in models},
        "save_traces": bool(args.save_traces),
        "reseed_required_tasks": bool(args.reseed_required_tasks),
        "tasks_root": str(tasks_root),
        "splits_root": str(splits_root),
    }
    write_json(output_root / "run_manifest.json", manifest)

    estimates: list[EstimateRecord] = []
    for model in models:
        options = dict(OPENAI_PRESETS[model])
        for task_id in task_ids:
            estimates.append(
                _oracle_prompt_cost(tasks_root / task_id, args.split, options)
            )
    write_json(output_root / "estimate.json", {"generated_at": _utc_now(), "records": [row.__dict__ for row in estimates]})
    _write_estimate_summary(output_root / "estimate.md", estimates, models)
    print(f"Wrote estimate JSON to {output_root / 'estimate.json'}")
    print(f"Wrote estimate Markdown to {output_root / 'estimate.md'}")

    if args.estimate_only:
        return 0

    if not os.environ.get("OPENAI_API_KEY"):
        raise NexUIError(
            "OPENAI_API_KEY is not set. Re-run with --estimate-only or export a key first."
        )

    records: list[RunRecord] = []
    results_jsonl = output_root / "results.jsonl"
    total_runs = len(models) * len(task_ids)
    run_index = 0
    for model in models:
        options = dict(OPENAI_PRESETS[model])
        for task_id in task_ids:
            run_index += 1
            print(f"[{run_index}/{total_runs}] {model} :: {task_id}", flush=True)
            record = _run_one(
                task_dir=tasks_root / task_id,
                split=args.split,
                options=options,
                reseed_required_tasks=args.reseed_required_tasks,
                trace_dir=trace_dir,
                score_dir=score_dir,
            )
            records.append(record)
            _append_jsonl(results_jsonl, record.__dict__)
            status = "PASS" if record.passed else "FAIL"
            print(
                f"  -> {status} | steps={record.step_count} | "
                f"cost~${record.estimated_cost_usd:.4f}",
                flush=True,
            )
            if record.error:
                print(f"     error: {record.error}", flush=True)

    summary = _build_run_summary(records=records, models=models)
    write_json(output_root / "results.json", summary)
    write_json(output_root / "failure_summary.json", {"generated_at": _utc_now(), "failure_type_summaries": summary["failure_type_summaries"]})
    _write_run_summary(output_root / "summary.md", records, models)
    write_text(output_root / "README.txt", "\n".join([
        f"OpenAI baseline run bundle: {output_root.name}",
        f"Generated at: {manifest['generated_at']}",
        f"Git commit: {manifest['git_commit'] or 'unknown'}",
        f"Split: {args.split}",
        f"Models: {', '.join(models)}",
        "",
        "Artifacts:",
        "- run_manifest.json: run configuration and task list",
        "- estimate.json / estimate.md: offline cost estimate",
        "- results.jsonl: append-only per-run records in completion order",
        "- results.json: aggregated final report with all records",
        "- failure_summary.json: grouped failure taxonomy",
        "- summary.md: human-readable summary tables",
        "- traces/: per-task traces when --save-traces is enabled",
        "- scores/: per-task score reports when --save-traces is enabled",
        "",
    ]) + "\n")
    print(f"Wrote run JSON to {output_root / 'results.json'}")
    print(f"Wrote incremental run log to {results_jsonl}")
    print(f"Wrote run Markdown to {output_root / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
