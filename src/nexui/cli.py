from __future__ import annotations

import argparse
import json
from pathlib import Path

from typing import TYPE_CHECKING

from nexui.authoring import (
    InitSourceOptions,
    SurveySourceOptions,
    ValidateSourceOptions,
    default_registry_path,
    init_source,
    list_sources,
    survey_source,
    validate_source,
)
from nexui.dataset import (
    default_splits_root,
    default_tasks_root,
    list_task_inventory,
    validate_split_manifests,
)
from nexui.capture import CaptureOptions, run_capture
from nexui.io import NexUIError
from nexui.record import RecordOptions, run_recording
from nexui.runner import run_task, save_trace
from nexui.scoring import load_trace, save_score, score_trace
from nexui.source_runtime import reseed_source
from nexui.task import inspect_task, load_task
from nexui.template import copy_task_template
from nexui.validation import validate_task_package


AGENT_CHOICES = ["oracle", "noop", "gemini", "openai"]

if TYPE_CHECKING:
    from nexui.replay import ReplayReportOptions, ReplayVideoOptions


def _replay_api():
    from nexui.replay import (
        ReplayReportOptions,
        ReplayVideoOptions,
        render_trace_report,
        render_trace_video,
        resolve_task_for_replay,
    )

    return {
        "ReplayReportOptions": ReplayReportOptions,
        "ReplayVideoOptions": ReplayVideoOptions,
        "render_trace_report": render_trace_report,
        "render_trace_video": render_trace_video,
        "resolve_task_for_replay": resolve_task_for_replay,
    }


def _add_gemini_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--gemini-model",
        default="gemini-2.5-flash-lite",
        help="Gemini model id for --agent gemini",
    )
    parser.add_argument(
        "--gemini-temperature",
        type=float,
        default=0.0,
        help="Sampling temperature for --agent gemini",
    )
    parser.add_argument(
        "--gemini-max-output-tokens",
        type=int,
        default=512,
        help="Maximum output tokens for --agent gemini",
    )
    parser.add_argument(
        "--gemini-thinking-budget",
        type=int,
        default=0,
        help="Gemini 2.5 thinking budget; use 0 for the initial cheap baseline",
    )
    parser.add_argument(
        "--gemini-prompt-profile",
        default="candidates_only",
        choices=["candidates_only", "candidates_ax"],
        help="Observation packing profile for --agent gemini",
    )
    parser.add_argument(
        "--gemini-prompt-league",
        default="bronze",
        choices=["bronze", "silver", "gold", "platinum"],
        help="Prompt league for --agent gemini",
    )
    parser.add_argument(
        "--gemini-max-candidates",
        type=int,
        default=80,
        help="Maximum current-snapshot candidates to include in the Gemini prompt",
    )
    parser.add_argument(
        "--gemini-history-window",
        type=int,
        default=4,
        help="How many prior actions to include in the local Gemini prompt history",
    )
    parser.add_argument(
        "--gemini-seed",
        type=int,
        default=0,
        help="Seed passed through to Gemini for reproducibility",
    )


def _add_openai_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--openai-model",
        default="o3",
        help="OpenAI Responses model id for --agent openai",
    )
    parser.add_argument(
        "--openai-max-output-tokens",
        type=int,
        default=1024,
        help="Maximum total output tokens, including reasoning tokens, for --agent openai",
    )
    parser.add_argument(
        "--openai-reasoning-effort",
        default="low",
        choices=["none", "minimal", "low", "medium", "high", "xhigh"],
        help="Reasoning effort for --agent openai",
    )
    parser.add_argument(
        "--openai-text-verbosity",
        default="low",
        choices=["low", "medium", "high"],
        help="Text verbosity for --agent openai",
    )
    parser.add_argument(
        "--openai-prompt-profile",
        default="candidates_ax",
        choices=["candidates_only", "candidates_ax"],
        help="Observation packing profile for --agent openai",
    )
    parser.add_argument(
        "--openai-prompt-league",
        default="platinum",
        choices=["bronze", "silver", "gold", "platinum"],
        help="Prompt league for --agent openai",
    )
    parser.add_argument(
        "--openai-max-candidates",
        type=int,
        default=80,
        help="Maximum current-snapshot candidates to include in the OpenAI prompt",
    )
    parser.add_argument(
        "--openai-history-window",
        type=int,
        default=4,
        help="How many prior actions to include in the local OpenAI prompt history",
    )


def _add_explanation_judge_openai_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--judge-openai-model",
        default="gpt-5-mini",
        help="OpenAI model id for --judge openai",
    )
    parser.add_argument(
        "--judge-openai-max-output-tokens",
        type=int,
        default=600,
        help="Maximum output tokens for --judge openai",
    )
    parser.add_argument(
        "--judge-openai-reasoning-effort",
        default="low",
        choices=["none", "minimal", "low", "medium", "high", "xhigh"],
        help="Reasoning effort for --judge openai",
    )
    parser.add_argument(
        "--judge-openai-text-verbosity",
        default="low",
        choices=["low", "medium", "high"],
        help="Text verbosity for --judge openai",
    )
    parser.add_argument(
        "--judge-openai-timeout-s",
        type=float,
        default=90.0,
        help="Request timeout in seconds for --judge openai",
    )
    parser.add_argument(
        "--judge-openai-retry-count",
        type=int,
        default=2,
        help="Retry count for transient OpenAI judge failures",
    )
    parser.add_argument(
        "--judge-prompt-version",
        default="openai_helpfulness_v1",
        help="Prompt-version label stored in explanation-judge artifacts",
    )


def _build_agent_options(args: argparse.Namespace) -> dict[str, object]:
    if args.agent == "gemini":
        return {
            "model": args.gemini_model,
            "temperature": args.gemini_temperature,
            "max_output_tokens": args.gemini_max_output_tokens,
            "thinking_budget": args.gemini_thinking_budget,
            "prompt_profile": args.gemini_prompt_profile,
            "prompt_league": args.gemini_prompt_league,
            "max_candidates": args.gemini_max_candidates,
            "history_window": args.gemini_history_window,
            "seed": args.gemini_seed,
        }
    if args.agent == "openai":
        return {
            "model": args.openai_model,
            "max_output_tokens": args.openai_max_output_tokens,
            "reasoning_effort": args.openai_reasoning_effort,
            "text_verbosity": args.openai_text_verbosity,
            "prompt_profile": args.openai_prompt_profile,
            "prompt_league": args.openai_prompt_league,
            "max_candidates": args.openai_max_candidates,
            "history_window": args.openai_history_window,
        }
    return {}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nexui", description="NExUI benchmark tooling")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-task", help="Create a new task from the bundled template")
    init_parser.add_argument("task_id", help="Task identifier such as account-settings-001")
    init_parser.add_argument(
        "--output-dir",
        default="examples/tasks",
        help="Directory where the task package should be created",
    )

    init_source_parser = subparsers.add_parser("init-source", help="Create a source authoring package")
    init_source_parser.add_argument("site_id", help="Source identifier such as the-internet")
    init_source_parser.add_argument("--site-name", required=True)
    init_source_parser.add_argument("--base-url", required=True)
    init_source_parser.add_argument(
        "--source-track",
        required=True,
        choices=[
            "accessibility_first_demo",
            "ui_automation_demo",
            "service_form_pattern",
            "modern_authenticated_app",
            "enterprise_workflow",
            "sandboxed_benchmark_env",
            "other",
        ],
    )
    init_source_parser.add_argument(
        "--category",
        required=True,
        choices=[
            "accessibility_demo",
            "ui_automation_demo",
            "education_demo",
            "finance_demo",
            "hr_demo",
            "ecommerce_demo",
            "government_pattern",
            "health_pattern",
            "other",
        ],
    )
    init_source_parser.add_argument(
        "--hosting-mode",
        required=True,
        choices=[
            "live_demo",
            "self_hosted",
            "benchmark_env",
            "pattern_proto",
            "local_fixture",
        ],
    )
    init_source_parser.add_argument(
        "--redistribution-class",
        required=True,
        choices=[
            "redistributable_source",
            "live_only_academic_source",
            "inspiration_only_source",
            "permission_required_source",
        ],
    )
    init_source_parser.add_argument(
        "--reset-strategy",
        default="manual_reset",
        choices=[
            "none",
            "manual_reset",
            "reseed_command",
            "docker_reset",
            "fixture_reload",
        ],
    )
    init_source_parser.add_argument(
        "--determinism-level",
        default="medium",
        choices=["low", "medium", "high"],
    )
    init_source_parser.add_argument("--output-dir", default="sources")
    init_source_parser.add_argument("--registry", default=str(default_registry_path()))

    list_sources_parser = subparsers.add_parser("list-sources", help="List source packages in the registry")
    list_sources_parser.add_argument("--registry", default=str(default_registry_path()))

    list_tasks_parser = subparsers.add_parser("list-tasks", help="List benchmark tasks with split and difficulty metadata")
    list_tasks_parser.add_argument("--tasks-root", default=str(default_tasks_root()))
    list_tasks_parser.add_argument("--splits-root", default=str(default_splits_root()))
    list_tasks_parser.add_argument("--json", action="store_true")

    survey_source_parser = subparsers.add_parser("survey-source", help="Capture source entry points into authoring snapshots")
    survey_source_parser.add_argument("source", help="Path to a source package directory or its site.yaml")
    survey_source_parser.add_argument("--entry-id", help="Capture only one configured entry point")
    survey_source_parser.add_argument("--overwrite", action="store_true")
    survey_source_parser.add_argument("--headed", action="store_true")

    reseed_source_parser = subparsers.add_parser("reseed-source", help="Run a source runtime reseed/reset command")
    reseed_source_parser.add_argument("source", help="Source id, source package directory, or site.yaml path")

    validate_source_parser = subparsers.add_parser("validate-source", help="Validate a source package and its onboarding files")
    validate_source_parser.add_argument("source", help="Path to a source package directory or its site.yaml")
    validate_source_parser.add_argument(
        "--check-remote",
        action="store_true",
        help="Probe remote HTTP/HTTPS entry-point URLs with a lightweight HEAD request",
    )
    validate_source_parser.add_argument("--json", action="store_true")

    validate_splits_parser = subparsers.add_parser("validate-splits", help="Validate dataset split manifests against task inventory")
    validate_splits_parser.add_argument("--tasks-root", default=str(default_tasks_root()))
    validate_splits_parser.add_argument("--splits-root", default=str(default_splits_root()))
    validate_splits_parser.add_argument("--json", action="store_true")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect a packaged task")
    inspect_parser.add_argument("task", help="Path to the task package")
    inspect_parser.add_argument("--json", action="store_true", help="Print raw JSON instead of a summary")

    validate_parser = subparsers.add_parser("validate-task", help="Validate a task package and its success logic")
    validate_parser.add_argument("task", help="Path to the task package")
    validate_parser.add_argument("--trace", help="Optional trace JSON to validate instead of generating an oracle trace")
    validate_parser.add_argument("--agent", default="oracle", choices=AGENT_CHOICES)
    validate_parser.add_argument("--max-steps", type=int, default=50)
    validate_parser.add_argument("--reseed-source", action="store_true")
    validate_parser.add_argument("--json", action="store_true")
    _add_gemini_args(validate_parser)
    _add_openai_args(validate_parser)

    capture_parser = subparsers.add_parser("capture", help="Capture a live page into a NExUI snapshot bundle")
    capture_parser.add_argument("--url", required=True, help="Page URL to capture")
    capture_target_group = capture_parser.add_mutually_exclusive_group(required=True)
    capture_target_group.add_argument("--snapshot-dir", help="Output directory for one snapshot bundle")
    capture_target_group.add_argument("--task", help="Task directory that contains snapshots/")
    capture_parser.add_argument("--snapshot-id", help="Snapshot id such as s000 when using --task")
    capture_parser.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"])
    capture_parser.add_argument(
        "--wait-until",
        default="load",
        choices=["domcontentloaded", "load", "networkidle", "commit"],
    )
    capture_parser.add_argument("--delay-ms", type=int, default=0)
    capture_parser.add_argument("--timeout-ms", type=int, default=30000)
    capture_parser.add_argument("--viewport-width", type=int, default=1440)
    capture_parser.add_argument("--viewport-height", type=int, default=900)
    capture_parser.add_argument("--locale", default="en-US")
    capture_parser.add_argument("--headed", action="store_true")

    record_parser = subparsers.add_parser("record", help="Record a multi-step task package from a recipe")
    record_parser.add_argument("--recipe", required=True, help="Path to the recording recipe JSON")
    record_parser.add_argument("--output-dir", default="examples/tasks", help="Directory that will contain the task package")
    record_parser.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"])
    record_parser.add_argument(
        "--wait-until",
        default="load",
        choices=["domcontentloaded", "load", "networkidle", "commit"],
    )
    record_parser.add_argument("--delay-ms", type=int, default=0)
    record_parser.add_argument("--timeout-ms", type=int, default=30000)
    record_parser.add_argument("--viewport-width", type=int, default=1440)
    record_parser.add_argument("--viewport-height", type=int, default=900)
    record_parser.add_argument("--locale", default="en-US")
    record_parser.add_argument("--headed", action="store_true")
    record_parser.add_argument("--overwrite", action="store_true")
    record_parser.add_argument("--reseed-source", action="store_true")
    record_parser.add_argument(
        "--skip-oracle-artifacts",
        action="store_true",
        help="Do not auto-generate the oracle trace, replay video, and replay report after recording",
    )
    record_parser.add_argument("--oracle-trace-dir", default="traces")
    record_parser.add_argument("--oracle-video-dir", default="videos")
    record_parser.add_argument("--oracle-report-dir", default="reports")
    record_parser.add_argument("--oracle-fps", type=int, default=1)
    record_parser.add_argument("--oracle-seconds-per-scene", type=float, default=2.0)

    run_parser = subparsers.add_parser("run", help="Run an agent against a packaged task")
    run_parser.add_argument("task", help="Path to the task package")
    run_parser.add_argument("--agent", default="oracle", choices=AGENT_CHOICES)
    run_parser.add_argument("--max-steps", type=int, default=50)
    run_parser.add_argument("--reseed-source", action="store_true")
    run_parser.add_argument("--output", help="Path to write the resulting trace JSON")
    run_parser.add_argument(
        "--no-video",
        action="store_true",
        help="Do not auto-render a replay video for oracle runs",
    )
    run_parser.add_argument(
        "--no-report",
        action="store_true",
        help="Do not auto-render an HTML replay report for oracle runs",
    )
    run_parser.add_argument("--video-output", help="Path to write the replay video")
    run_parser.add_argument("--report-output", help="Path to write the replay report HTML")
    run_parser.add_argument("--fps", type=int, default=1, help="Frames per second for video export")
    run_parser.add_argument(
        "--seconds-per-scene",
        type=float,
        default=2.0,
        help="How long each replay scene should hold on screen",
    )
    _add_gemini_args(run_parser)
    _add_openai_args(run_parser)

    replay_parser = subparsers.add_parser("replay", help="Replay a saved trace")
    replay_parser.add_argument("trace", help="Path to the trace JSON file")
    replay_parser.add_argument("--task", help="Task package path used to resolve snapshots for video export")
    replay_parser.add_argument("--video", help="Output path for a rendered replay video such as replay.mp4")
    replay_parser.add_argument("--report", help="Output path for a rendered replay report HTML")
    replay_parser.add_argument("--fps", type=int, default=1, help="Frames per second for video export")
    replay_parser.add_argument(
        "--seconds-per-scene",
        type=float,
        default=2.0,
        help="How long each replay scene should hold on screen",
    )

    score_parser = subparsers.add_parser("score", help="Score a saved trace against a task package")
    score_parser.add_argument("trace", help="Path to the trace JSON file")
    score_parser.add_argument("--task", required=True, help="Path to the task package used for the trace")
    score_parser.add_argument("--output", help="Path to write the score JSON")

    judge_parser = subparsers.add_parser(
        "judge-explanations",
        help="Build explanation-judge packets and verdict artifacts for a saved trace",
    )
    judge_parser.add_argument("trace", help="Path to the trace JSON file")
    judge_parser.add_argument("--task", required=True, help="Path to the task package used for the trace")
    judge_parser.add_argument(
        "--judge",
        default="offline_stub",
        choices=["offline_stub", "openai"],
        help="Explanation judge backend to use for this first rollout phase",
    )
    judge_parser.add_argument(
        "--output-dir",
        help="Directory to write judge packets, verdicts, and summaries",
    )
    judge_parser.add_argument("--json", action="store_true")
    _add_explanation_judge_openai_args(judge_parser)

    return parser


def cmd_init_task(args: argparse.Namespace) -> int:
    task_root = copy_task_template(args.output_dir, args.task_id)
    print(f"Created task template at {task_root}")
    return 0


def cmd_init_source(args: argparse.Namespace) -> int:
    source_root = init_source(
        InitSourceOptions(
            site_id=args.site_id,
            site_name=args.site_name,
            base_url=args.base_url,
            source_track=args.source_track,
            category=args.category,
            hosting_mode=args.hosting_mode,
            redistribution_class=args.redistribution_class,
            reset_strategy=args.reset_strategy,
            determinism_level=args.determinism_level,
            output_dir=Path(args.output_dir),
            registry_path=Path(args.registry),
        )
    )
    print(f"Created source package at {source_root}")
    return 0


def cmd_list_sources(args: argparse.Namespace) -> int:
    sources = list_sources(args.registry)
    for entry in sources:
        print(
            f"{entry['site_id']}: {entry['site_name']} | {entry['authoring_status']} | "
            f"{entry['source_track']} | {entry['hosting_mode']} | {entry['determinism_level']} | {entry['base_url']}"
        )
    return 0


def cmd_list_tasks(args: argparse.Namespace) -> int:
    inventory = list_task_inventory(tasks_root=args.tasks_root, splits_root=args.splits_root)
    if args.json:
        print(json.dumps(inventory, indent=2))
        return 0

    for item in inventory:
        splits = ",".join(item["assigned_splits"]) if item["assigned_splits"] else item["declared_split"]
        print(
            f"{item['task_id']}: {item['source_id']} | {item['difficulty_band']} | "
            f"{item['risk_level']} | split={splits} | production={item['production']}"
        )
    return 0


def cmd_survey_source(args: argparse.Namespace) -> int:
    summary = survey_source(
        SurveySourceOptions(
            source_path=Path(args.source),
            entry_id=args.entry_id,
            overwrite=args.overwrite,
            headed=args.headed,
        )
    )
    print(f"Source: {summary['site_id']}")
    print(f"Surveyed entry points: {summary['surveyed_entry_count']}")
    for capture in summary["captures"]:
        print(
            f"{capture['entry_id']}: {capture['title']} | {capture['candidate_count']} candidates | {capture['snapshot_dir']}"
        )
    return 0


def cmd_reseed_source(args: argparse.Namespace) -> int:
    context = reseed_source(args.source)
    print(f"Reseeded source: {context.source_id}")
    print(f"Manifest: {context.manifest_path}")
    print(f"Reset strategy: {context.reset_strategy}")
    return 0


def cmd_validate_source(args: argparse.Namespace) -> int:
    result = validate_source(
        ValidateSourceOptions(
            source_path=Path(args.source),
            check_remote=args.check_remote,
        )
    )
    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1

    print(f"Source: {result['site_id']}")
    print(f"Manifest: {result['manifest_path']}")
    print(f"Passed: {result['passed']}")
    print(f"Errors: {result['error_count']}")
    print(f"Warnings: {result['warning_count']}")
    runtime_status = result.get("runtime_status") or {}
    if runtime_status:
        print(f"Runtime ready: {runtime_status.get('is_ready')}")
        if runtime_status.get("checkout_path"):
            print(f"Checkout path: {runtime_status['checkout_path']}")
        if runtime_status.get("healthcheck_url"):
            print(f"Healthcheck URL: {runtime_status['healthcheck_url']}")
        if runtime_status.get("start_command"):
            print(f"Start command: {runtime_status['start_command']}")
        if runtime_status.get("reseed_command"):
            print(f"Reseed command: {runtime_status['reseed_command']}")
        if runtime_status.get("readiness_command"):
            print(f"Readiness command: {runtime_status['readiness_command']}")
    for check in result["checks"]:
        status = "ok" if check["passed"] else "fail"
        print(f"{status}: {check['target']} - {check['message']}")
    for warning in result["warnings"]:
        print(f"Warning: {warning}")
    for error in result["errors"]:
        print(f"Error: {error}")
    return 0 if result["passed"] else 1


def cmd_validate_splits(args: argparse.Namespace) -> int:
    result = validate_split_manifests(tasks_root=args.tasks_root, splits_root=args.splits_root)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1

    print(f"Passed: {result['passed']}")
    print(f"Production tasks: {result['production_task_count']}")
    for split_id, count in result["split_counts"].items():
        print(f"{split_id}: {count}")
    for band, count in result["difficulty_band_counts"].items():
        print(f"difficulty {band}: {count}")
    for warning in result["warnings"]:
        print(f"Warning: {warning}")
    for error in result["errors"]:
        print(f"Error: {error}")
    return 0 if result["passed"] else 1


def cmd_inspect(args: argparse.Namespace) -> int:
    task = load_task(args.task)
    summary = inspect_task(task)
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    print(f"Task: {summary['task_id']}")
    print(f"Title: {summary['title']}")
    print(f"Goal: {summary['goal']}")
    print(f"Risk: {summary['risk_level']}")
    print(f"Difficulty: {summary['difficulty_band']}")
    print(f"Split: {summary['split']}")
    print(f"Source surface: {summary['source_surface']}")
    print(f"Stability runs passed: {summary['stability_runs_passed']}")
    print(f"Snapshots: {summary['snapshot_count']}")
    print(f"Transitions: {summary['transition_count']}")
    print(f"Oracle steps: {summary['oracle_step_count']}")
    print(f"Start snapshot: {summary['start_snapshot']}")
    print(f"Source: {summary['source']['site_name']} ({summary['source']['url']})")
    return 0


def cmd_validate_task(args: argparse.Namespace) -> int:
    task = load_task(args.task)
    agent_options = _build_agent_options(args)
    result = validate_task_package(
        task,
        trace_path=args.trace,
        agent_name=args.agent,
        max_steps=args.max_steps,
        reseed_source_runtime=args.reseed_source,
        agent_options=agent_options,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "task_id": result.task_id,
                    "trace_source": result.trace_source,
                    "success_assertion_count": result.assertion_count,
                    "success_any_of_branch_count": result.any_of_branch_count,
                    "score": result.score,
                },
                indent=2,
            )
        )
        return 0 if result.score["passed"] else 1

    print(f"Task: {result.task_id}")
    print(f"Trace source: {result.trace_source}")
    print(f"Success assertions: {result.assertion_count}")
    print(f"Success any-of branches: {result.any_of_branch_count}")
    print(f"Task success: {result.score['metrics']['task_success']}")
    print(f"Safety pass: {result.score['metrics']['safety_pass']}")
    for note in result.score.get("notes", []):
        print(f"Note: {note}")
    return 0 if result.score["passed"] else 1


def _resolve_snapshot_dir(args: argparse.Namespace) -> Path:
    if args.snapshot_dir:
        return Path(args.snapshot_dir).resolve()
    if not args.snapshot_id:
        raise NexUIError("--snapshot-id is required when using --task")
    return (Path(args.task).resolve() / "snapshots" / args.snapshot_id).resolve()


def cmd_capture(args: argparse.Namespace) -> int:
    snapshot_dir = _resolve_snapshot_dir(args)
    options = CaptureOptions(
        url=args.url,
        snapshot_dir=snapshot_dir,
        browser=args.browser,
        wait_until=args.wait_until,
        delay_ms=args.delay_ms,
        timeout_ms=args.timeout_ms,
        viewport_width=args.viewport_width,
        viewport_height=args.viewport_height,
        locale=args.locale,
        headed=args.headed,
    )
    summary = run_capture(options)
    print(f"Snapshot written to {summary['snapshot_dir']}")
    print(f"URL: {summary['url']}")
    print(f"Title: {summary['title']}")
    print(f"Candidates: {summary['candidate_count']}")
    print(f"Modal state: {summary['modal_state']}")
    return 0


def _default_video_path(trace_path: Path) -> Path:
    return Path("videos") / f"{trace_path.stem}.mp4"


def _default_report_path(trace_path: Path) -> Path:
    return Path("reports") / f"{trace_path.stem}.html"


def _write_oracle_artifacts(
    task,
    trace_path: Path,
    *,
    video_path: Path,
    report_path: Path,
    fps: int,
    seconds_per_scene: float,
) -> dict:
    replay = _replay_api()
    trace, score = run_task(task, agent_name="oracle", max_steps=50)
    save_trace(trace_path, trace)
    video_summary = replay["render_trace_video"](
        task,
        trace,
        replay["ReplayVideoOptions"](
            output_path=video_path,
            fps=fps,
            seconds_per_scene=seconds_per_scene,
        ),
    )
    report_summary = replay["render_trace_report"](
        task,
        trace,
        replay["ReplayReportOptions"](
            output_path=report_path,
            video_path=Path(video_summary["video_path"]),
        ),
        score=score,
    )
    return {
        "trace": trace,
        "score": score,
        "trace_path": trace_path.resolve(),
        "video_path": Path(video_summary["video_path"]),
        "video_summary": video_summary,
        "report_path": Path(report_summary["report_path"]),
        "report_summary": report_summary,
    }


def cmd_record(args: argparse.Namespace) -> int:
    summary = run_recording(
        RecordOptions(
            recipe=Path(args.recipe),
            output_dir=Path(args.output_dir),
            browser=args.browser,
            wait_until=args.wait_until,
            delay_ms=args.delay_ms,
            timeout_ms=args.timeout_ms,
            viewport_width=args.viewport_width,
            viewport_height=args.viewport_height,
            locale=args.locale,
            headed=args.headed,
            overwrite=args.overwrite,
            reseed_source_runtime=args.reseed_source,
        )
    )
    print(f"Task package written to {summary['task_dir']}")
    print(f"Task: {summary['task_id']}")
    print(f"Snapshots: {summary['snapshot_count']}")
    print(f"Transitions: {summary['transition_count']}")
    print(f"Oracle steps: {summary['oracle_step_count']}")
    print(f"Final snapshot: {summary['final_snapshot']}")
    if not args.skip_oracle_artifacts:
        task = load_task(summary["task_dir"])
        trace_path = Path(args.oracle_trace_dir) / f"{summary['task_id']}-oracle.json"
        video_path = Path(args.oracle_video_dir) / f"{summary['task_id']}-oracle.mp4"
        report_path = Path(args.oracle_report_dir) / f"{summary['task_id']}-oracle.html"
        oracle = _write_oracle_artifacts(
            task,
            trace_path,
            video_path=video_path,
            report_path=report_path,
            fps=args.oracle_fps,
            seconds_per_scene=args.oracle_seconds_per_scene,
        )
        print(f"Oracle trace written to {oracle['trace_path']}")
        print(f"Oracle video written to {oracle['video_path']}")
        print(f"Oracle report written to {oracle['report_path']}")
        print(f"Oracle task success: {oracle['score']['metrics']['task_success']}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    task = load_task(args.task)
    agent_options = _build_agent_options(args)
    if task.requires_source_reset and not args.reseed_source:
        raise NexUIError(f"Task {task.task_id!r} requires a clean source state; rerun with --reseed-source.")
    if args.reseed_source:
        if not task.source_surface:
            raise NexUIError(f"Task {task.task_id!r} does not declare source_surface for reseed resolution.")
        reseed_source(task.source_surface)
    trace, score = run_task(
        task,
        agent_name=args.agent,
        max_steps=args.max_steps,
        agent_options=agent_options,
    )
    output_path = args.output or str(
        Path("traces") / f"{task.task_id}-{args.agent}-{trace['run_id'][:8]}.json"
    )
    save_trace(output_path, trace)
    print(f"Trace written to {Path(output_path).resolve()}")
    print(f"Run status: {trace['result']['status']}")
    print(f"Task success: {score['metrics']['task_success']}")
    print(f"Safety pass: {score['metrics']['safety_pass']}")
    if args.agent == "oracle":
        replay = _replay_api()
        resolved_video_path = Path(args.video_output) if args.video_output else _default_video_path(Path(output_path))
        report_path = Path(args.report_output) if args.report_output else _default_report_path(Path(output_path))
        if not args.no_video:
            summary = replay["render_trace_video"](
                task,
                trace,
                replay["ReplayVideoOptions"](
                    output_path=resolved_video_path,
                    fps=args.fps,
                    seconds_per_scene=args.seconds_per_scene,
                ),
            )
            resolved_video_path = Path(summary["video_path"])
            print(f"Replay video written to {summary['video_path']}")
        if not args.no_report:
            report_summary = replay["render_trace_report"](
                task,
                trace,
                replay["ReplayReportOptions"](
                    output_path=report_path,
                    video_path=resolved_video_path if resolved_video_path.exists() else None,
                ),
                score=score,
            )
            print(f"Replay report written to {report_summary['report_path']}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    trace = load_trace(args.trace)
    replay = _replay_api()
    print(f"Run: {trace['run_id']}")
    print(f"Task: {trace['task_id']}")
    print(f"Status: {trace['result']['status']}")
    for step in trace["steps"]:
        action = step["submission"]["action"]
        explanation = step["submission"]["explanation"]
        print(
            f"Step {step['step_index']}: {action['type']} from {step['before_snapshot']} "
            f"to {step['after_snapshot']} [{step['validation']['status']}]"
        )
        print(f"  Explanation: {explanation}")
        for note in step.get("notes", []):
            print(f"  Note: {note}")
        for flag in step.get("safety_flags", []):
            print(f"  Safety: {flag}")
    final_summary = trace["result"].get("final_summary")
    if final_summary:
        print(f"Final summary: {final_summary}")
    print(f"Termination: {trace['result']['termination_reason']}")
    task = None
    rendered_video_path = None
    if args.video or args.report:
        task = replay["resolve_task_for_replay"](trace, args.task)
    if args.video:
        summary = replay["render_trace_video"](
            task,
            trace,
            replay["ReplayVideoOptions"](
                output_path=Path(args.video),
                fps=args.fps,
                seconds_per_scene=args.seconds_per_scene,
            ),
        )
        print(f"Video written to {summary['video_path']}")
        print(f"Frames: {summary['frame_count']}")
        print(f"FPS: {summary['fps']}")
        rendered_video_path = Path(summary["video_path"])
    if args.report:
        if rendered_video_path is None:
            default_video_path = _default_video_path(Path(args.trace))
            if default_video_path.exists():
                rendered_video_path = default_video_path.resolve()
        score = score_trace(task, trace) if task is not None else None
        report_summary = replay["render_trace_report"](
            task,
            trace,
            replay["ReplayReportOptions"](
                output_path=Path(args.report),
                video_path=rendered_video_path,
            ),
            score=score,
        )
        print(f"Replay report written to {report_summary['report_path']}")
        print("Open the HTML report in a browser to review the embedded video and step timeline.")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    task = load_task(args.task)
    trace = load_trace(args.trace)
    score = score_trace(task, trace)
    if args.output:
        save_score(args.output, score)
        print(f"Score written to {Path(args.output).resolve()}")
    print(json.dumps(score, indent=2))
    return 0


def _utc_timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _default_judge_output_dir(task_id: str) -> Path:
    return Path("reports") / "explanation-judge" / f"{task_id}-{_utc_timestamp()}"


def _write_summary_md(summary_path: Path, *, manifest: dict[str, Any], summary: dict[str, Any]) -> None:
    lines = [
        "# Explanation Judge Summary",
        "",
        f"- task: `{manifest['task_id']}`",
        f"- run: `{manifest['run_id']}`",
        f"- judge: `{manifest['judge_name']}`",
        f"- model: `{manifest.get('judge_model') or 'n/a'}`",
        f"- prompt_version: `{manifest.get('prompt_version') or 'n/a'}`",
        f"- generated_at: `{manifest['generated_at']}`",
        f"- packet_count: `{summary['packet_count']}`",
        f"- abstained_count: `{summary['abstained_count']}`",
        f"- abstained_rate: `{summary['abstained_rate']:.4f}`",
        f"- precheck_abstained_count: `{summary.get('precheck_abstained_count', 0)}`",
        f"- scored_count: `{summary['scored_count']}`",
    ]
    abstain_reasons = summary.get("abstain_reasons") or {}
    if abstain_reasons:
        lines.append("- abstain_reasons:")
        for reason, count in sorted(abstain_reasons.items()):
            lines.append(f"  - `{reason}`: `{count}`")
    if summary.get("overall_helpfulness_average") is not None:
        lines.extend(
            [
                f"- clarity_average: `{summary['clarity_average']:.4f}`",
                f"- task_relevance_average: `{summary['task_relevance_average']:.4f}`",
                f"- detail_average: `{summary['detail_average']:.4f}`",
                f"- risk_communication_average: `{summary['risk_communication_average']:.4f}`",
                f"- overall_helpfulness_average: `{summary['overall_helpfulness_average']:.4f}`",
                f"- confidence_average: `{summary['confidence_average']:.4f}`",
            ]
        )
    lines.append("")
    if manifest["judge_name"] == "offline_stub":
        lines.append("This first-phase offline judge scaffold only emits auditable packets and abstaining verdicts.")
    else:
        lines.append("This report preserves auditable judge packets, verdicts, metadata, and raw responses.")
    Path(summary_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_judge_explanations(args: argparse.Namespace) -> int:
    from nexui.explanation_judge import (
        ExplanationJudgeOptions,
        judge_packets,
        summarize_verdicts,
    )
    from nexui.explanation_judge_packet import build_trace_judge_packets, packet_filename
    from nexui.io import write_json

    task = load_task(args.task)
    trace = load_trace(args.trace)
    score = score_trace(task, trace)
    packets = build_trace_judge_packets(
        task,
        trace,
        task_success=bool(score["metrics"]["task_success"]),
    )
    judge_options = ExplanationJudgeOptions(
        judge_name=args.judge,
        model=args.judge_openai_model,
        max_output_tokens=args.judge_openai_max_output_tokens,
        reasoning_effort=args.judge_openai_reasoning_effort,
        text_verbosity=args.judge_openai_text_verbosity,
        request_timeout_s=args.judge_openai_timeout_s,
        retry_count=args.judge_openai_retry_count,
        prompt_version=args.judge_prompt_version,
    )
    results = judge_packets(
        packets,
        options=judge_options,
    )

    output_dir = Path(args.output_dir) if args.output_dir else _default_judge_output_dir(task.task_id)
    packets_dir = output_dir / "packets"
    verdicts_dir = output_dir / "verdicts"
    metadata_dir = output_dir / "metadata"
    raw_responses_dir = output_dir / "raw_responses"
    output_dir.mkdir(parents=True, exist_ok=True)
    packets_dir.mkdir(parents=True, exist_ok=True)
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    raw_responses_dir.mkdir(parents=True, exist_ok=True)

    for packet in packets:
        write_json(packets_dir / packet_filename(int(packet["step_index"])), packet)
    for packet, result in zip(packets, results):
        filename = packet_filename(int(packet["step_index"]))
        write_json(verdicts_dir / filename, result.verdict)
        write_json(metadata_dir / filename, result.metadata)
        if result.raw_response is not None:
            write_json(raw_responses_dir / filename, result.raw_response)

    manifest = {
        "generated_at": _utc_timestamp(),
        "task_id": task.task_id,
        "run_id": trace["run_id"],
        "trace_path": str(Path(args.trace).resolve()),
        "task_root": str(task.root.resolve()),
        "judge_name": args.judge,
        "judge_model": judge_options.model if args.judge == "openai" else None,
        "prompt_version": judge_options.prompt_version,
        "packet_count": len(packets),
    }
    summary = summarize_verdicts(results)
    write_json(output_dir / "run_manifest.json", manifest)
    write_json(output_dir / "score.json", score)
    write_json(output_dir / "summary.json", summary)
    _write_summary_md(output_dir / "summary.md", manifest=manifest, summary=summary)

    payload = {
        "output_dir": str(output_dir.resolve()),
        "manifest": manifest,
        "summary": summary,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Judge artifacts written to {output_dir.resolve()}")
        print(f"Task: {task.task_id}")
        print(f"Run: {trace['run_id']}")
        print(f"Judge: {args.judge}")
        if args.judge == "openai":
            print(f"Model: {judge_options.model}")
        print(f"Packets: {summary['packet_count']}")
        print(f"Abstained: {summary['abstained_count']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "init-task":
            return cmd_init_task(args)
        if args.command == "init-source":
            return cmd_init_source(args)
        if args.command == "list-sources":
            return cmd_list_sources(args)
        if args.command == "list-tasks":
            return cmd_list_tasks(args)
        if args.command == "survey-source":
            return cmd_survey_source(args)
        if args.command == "reseed-source":
            return cmd_reseed_source(args)
        if args.command == "validate-source":
            return cmd_validate_source(args)
        if args.command == "validate-splits":
            return cmd_validate_splits(args)
        if args.command == "inspect":
            return cmd_inspect(args)
        if args.command == "validate-task":
            return cmd_validate_task(args)
        if args.command == "capture":
            return cmd_capture(args)
        if args.command == "record":
            return cmd_record(args)
        if args.command == "run":
            return cmd_run(args)
        if args.command == "replay":
            return cmd_replay(args)
        if args.command == "score":
            return cmd_score(args)
        if args.command == "judge-explanations":
            return cmd_judge_explanations(args)
    except NexUIError as exc:
        parser.exit(status=2, message=f"error: {exc}\n")

    parser.exit(status=2, message=f"error: unknown command {args.command!r}\n")


if __name__ == "__main__":
    raise SystemExit(main())
