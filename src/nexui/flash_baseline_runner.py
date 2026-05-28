from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nexui import __version__ as NEXUI_VERSION
from nexui.dataset import default_splits_root, default_tasks_root, load_split_manifest
from nexui.gemini_agent import GeminiAgent, GeminiAgentConfig
from nexui.io import NexUIError, append_jsonl_atomic, read_json, read_text, write_json, write_text
from nexui.runner import run_task
from nexui.scoring import load_trace, score_trace
from nexui.source_runtime import reseed_source
from nexui.task import load_task


FLASH_PRESETS: dict[str, dict[str, Any]] = {
    "gemini-2.5-flash-lite": {
        "model": "gemini-2.5-flash-lite",
        "prompt_profile": "candidates_only",
        "thinking_budget": 0,
        "temperature": 0.0,
        "max_output_tokens": 512,
        "seed": 0,
    },
    "gemini-2.5-flash": {
        "model": "gemini-2.5-flash",
        "prompt_profile": "candidates_ax",
        "thinking_budget": 0,
        "temperature": 0.0,
        "max_output_tokens": 512,
        "seed": 0,
    },
    "gemini-3.5-flash": {
        "model": "gemini-3.5-flash",
        "prompt_profile": "candidates_ax",
        "thinking_budget": 1024,
        "temperature": 0.0,
        "max_output_tokens": 512,
        "seed": 0,
    },
}

PROMPT_LEAGUES = ("bronze", "silver", "gold", "platinum")

PRICING_SOURCE_URL = "https://ai.google.dev/gemini-api/docs/pricing"
MODELS_ENDPOINT_URL = "https://generativelanguage.googleapis.com/v1beta/models"
COUNT_TOKENS_TIMEOUT_S = 60.0
API_RETRY_COUNT = 2
EXIT_CONFIG = 2
EXIT_BUDGET = 3
EXIT_MANUAL = 130
MIN_BUDGET_RESERVE_USD = 1.0
FRESH_BUDGET_STOP_THRESHOLD_USD = 9.0

RESULT_STATUS_COMPLETED = "completed"
RESULT_STATUS_RUNTIME_ERROR = "runtime_error"
RESULT_STATUS_STOPPED_BUDGET = "stopped_budget"

RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_STOPPED_BUDGET = "stopped_budget"
RUN_STATUS_STOPPED_MANUAL = "stopped_manual"
RUN_STATUS_FAILED_CONFIG = "failed_config"
RUN_STATUS_INCOMPLETE_RUNTIME_ERRORS = "incomplete_runtime_errors"
RUN_STATUS_ESTIMATE_ONLY = "estimate_only"

PRICING_MODEL_TITLES = {
    "gemini-2.5-flash-lite": "Gemini 2.5 Flash-Lite",
    "gemini-2.5-flash": "Gemini 2.5 Flash",
    "gemini-3.5-flash": "Gemini 3.5 Flash",
}


@dataclass(frozen=True)
class EstimateRecord:
    model: str
    league: str
    task_id: str
    split: str
    source_surface: str
    difficulty_band: str
    oracle_step_count: int
    prompt_profile: str
    thinking_budget: int
    max_output_tokens: int
    prompt_token_count: int
    visible_output_token_count: int
    expected_reasoning_token_count: int
    expected_output_token_count: int
    conservative_output_token_count: int
    expected_cost_usd: float
    conservative_cost_usd: float


@dataclass(frozen=True)
class RunAttemptResult:
    trace: dict[str, Any]
    score: dict[str, Any]
    record: dict[str, Any]
    error_payload: dict[str, Any] | None


class TaskBudgetObserver:
    def __init__(
        self,
        *,
        model: str,
        pricing_by_model: dict[str, dict[str, float]],
        starting_cumulative_cost_usd: float,
        session_stop_limit_usd: float,
    ) -> None:
        self.model = model
        self.pricing_by_model = pricing_by_model
        self.starting_cumulative_cost_usd = starting_cumulative_cost_usd
        self.session_stop_limit_usd = session_stop_limit_usd
        self.task_cost_usd = 0.0
        self.stop_requested = False

    def on_step(
        self,
        trace: dict[str, Any],
        step_record: dict[str, Any],
    ) -> dict[str, str] | None:
        usage = _usage_from_metadata(step_record.get("agent_metadata"))
        self.task_cost_usd = _round_cost(
            self.task_cost_usd
            + _estimate_cost(
                self.model,
                usage["prompt_token_count"],
                usage["billed_output_token_count"],
                self.pricing_by_model,
            )
        )
        action_type = str((((step_record.get("submission") or {}).get("action") or {}).get("type") or ""))
        if action_type in {"finish", "ask_user"}:
            return None
        if self.starting_cumulative_cost_usd + self.task_cost_usd >= self.session_stop_limit_usd:
            self.stop_requested = True
            return {"status": "stopped", "reason": "budget_limit_reached"}
        return None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _round_cost(value: float) -> float:
    return round(value, 6)


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


def _load_api_key() -> str:
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    raise NexUIError(
        "Gemini baseline requires GOOGLE_API_KEY or GEMINI_API_KEY in the environment."
    )


def _load_task_ids(split: str, splits_root: Path) -> list[str]:
    manifest = load_split_manifest(splits_root / f"{split}.json")
    return list(manifest.get("task_ids", []))


def _resolve_max_steps(task, override: int | None) -> int:
    if override is not None:
        return override
    return max(10, min(50, len(task.oracle_steps) * 2 + 4))


def _step_budget_rule(max_steps_override: int | None) -> dict[str, Any]:
    if max_steps_override is not None:
        return {"mode": "override", "value": int(max_steps_override)}
    return {"mode": "auto", "rule": "max(10, min(50, len(task.oracle_steps) * 2 + 4))"}


def _model_label(model: str) -> str:
    return model.replace("/", "-")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(read_text(path).splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise NexUIError(f"Invalid JSONL in {path} line {line_number}") from exc
    return rows


def _first_invalid_step(trace: dict[str, Any]) -> dict[str, Any] | None:
    for step in trace.get("steps", []):
        validation = step.get("validation") or {}
        if validation.get("status") != "ok":
            return step
    return None


def _final_snapshot(trace: dict[str, Any], start_snapshot: str) -> str:
    final_snapshot = start_snapshot
    for step in trace.get("steps", []):
        after_snapshot = step.get("after_snapshot")
        if after_snapshot is not None:
            final_snapshot = after_snapshot
    return final_snapshot


def _usage_from_metadata(agent_metadata: dict[str, Any] | None) -> dict[str, int]:
    usage = ((agent_metadata or {}).get("usage") or {})
    prompt = int(usage.get("prompt_token_count") or 0)
    candidates = int(usage.get("candidates_token_count") or 0)
    thoughts = int(usage.get("thoughts_token_count") or 0)
    return {
        "prompt_token_count": prompt,
        "candidate_output_token_count": candidates,
        "thought_token_count": thoughts,
        "billed_output_token_count": candidates + thoughts,
    }


def _summarize_trace_usage(trace: dict[str, Any]) -> dict[str, int]:
    prompt = 0
    candidates = 0
    thoughts = 0
    for step in trace.get("steps", []):
        usage = _usage_from_metadata(step.get("agent_metadata"))
        prompt += usage["prompt_token_count"]
        candidates += usage["candidate_output_token_count"]
        thoughts += usage["thought_token_count"]
    runtime_agent_metadata = (((trace.get("result") or {}).get("runtime_error") or {}).get("agent_metadata"))
    if runtime_agent_metadata:
        usage = _usage_from_metadata(runtime_agent_metadata)
        prompt += usage["prompt_token_count"]
        candidates += usage["candidate_output_token_count"]
        thoughts += usage["thought_token_count"]
    return {
        "prompt_token_count": prompt,
        "candidate_output_token_count": candidates,
        "thought_token_count": thoughts,
        "billed_output_token_count": candidates + thoughts,
    }


def _summarize_trace_latency_ms(trace: dict[str, Any]) -> float:
    total = 0.0
    for step in trace.get("steps", []):
        total += float(((step.get("agent_metadata") or {}).get("latency_ms") or 0.0))
    runtime_agent_metadata = (((trace.get("result") or {}).get("runtime_error") or {}).get("agent_metadata"))
    if runtime_agent_metadata:
        total += float(runtime_agent_metadata.get("latency_ms") or 0.0)
    return round(total, 2)


def _estimate_cost(
    model: str,
    prompt_tokens: int,
    billed_output_tokens: int,
    pricing_by_model: dict[str, dict[str, float]],
) -> float:
    pricing = pricing_by_model[model]
    return _round_cost(
        (prompt_tokens / 1_000_000.0) * pricing["input"]
        + (billed_output_tokens / 1_000_000.0) * pricing["output"]
    )


def _strip_html(raw: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw)).split())


def _extract_first_price(raw: str) -> float:
    match = re.search(r"\$([0-9]+(?:\.[0-9]+)?)", raw)
    if match is None:
        raise NexUIError(f"Unable to parse price from {raw!r}")
    return float(match.group(1))


def _extract_model_pricing(page_html: str, *, model: str, title: str) -> dict[str, Any]:
    title_index = page_html.find(title)
    if title_index < 0:
        raise NexUIError(f"Unable to find {title!r} in Gemini pricing page.")
    table_match = re.search(
        r'<table class="pricing-table">(.*?)</table>',
        page_html[title_index:],
        flags=re.DOTALL,
    )
    if table_match is None:
        raise NexUIError(f"Unable to find pricing table for {model}.")
    table_html = table_match.group(1)
    input_price: float | None = None
    output_price: float | None = None
    for row_html in re.findall(r"<tr>(.*?)</tr>", table_html, flags=re.DOTALL):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.DOTALL)
        if len(cells) < 3:
            continue
        label = _strip_html(cells[0])
        paid_tier = _strip_html(cells[-1])
        lowered = label.casefold()
        if lowered.startswith("input price"):
            input_price = _extract_first_price(paid_tier)
        elif lowered.startswith("output price"):
            output_price = _extract_first_price(paid_tier)
    if input_price is None or output_price is None:
        raise NexUIError(f"Unable to parse input/output pricing for {model}.")
    return {
        "model": model,
        "title": title,
        "input": input_price,
        "output": output_price,
    }


def fetch_live_pricing() -> dict[str, Any]:
    request = urllib.request.Request(PRICING_SOURCE_URL, headers={"User-Agent": "nexui/flash-baseline"})
    with urllib.request.urlopen(request, timeout=COUNT_TOKENS_TIMEOUT_S) as response:
        page_html = response.read().decode("utf-8", errors="replace")
        response_date = response.headers.get("Date")
    pricing_by_model: dict[str, dict[str, float]] = {}
    models_payload: list[dict[str, Any]] = []
    for model, title in PRICING_MODEL_TITLES.items():
        parsed = _extract_model_pricing(page_html, model=model, title=title)
        pricing_by_model[model] = {"input": parsed["input"], "output": parsed["output"]}
        models_payload.append(parsed)
    return {
        "source_url": PRICING_SOURCE_URL,
        "fetched_at": _utc_now(),
        "response_date_header": response_date,
        "models": models_payload,
        "pricing_by_model": pricing_by_model,
    }


def _gemini_api_get_json(
    url: str,
    *,
    api_key: str,
    timeout_s: float = COUNT_TOKENS_TIMEOUT_S,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def _gemini_api_post_json(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str,
    timeout_s: float = COUNT_TOKENS_TIMEOUT_S,
    retry_count: int = API_RETRY_COUNT,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(retry_count + 1):
        try:
            request = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            last_error = NexUIError(
                f"Gemini API request failed with HTTP {exc.code}: {error_body[:800]}"
            )
            if exc.code not in {429, 500, 502, 503, 504} or attempt >= retry_count:
                raise last_error
        except urllib.error.URLError as exc:
            last_error = NexUIError(f"Gemini API request failed: {exc.reason}")
            if attempt >= retry_count:
                raise last_error
        time.sleep(1.0 * (2**attempt))
    assert last_error is not None
    raise last_error


def _fetch_available_models(api_key: str) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    next_page_token: str | None = None
    while True:
        query = "?pageSize=1000"
        if next_page_token:
            query += f"&pageToken={urllib.parse.quote(next_page_token, safe='')}"
        payload = _gemini_api_get_json(f"{MODELS_ENDPOINT_URL}{query}", api_key=api_key)
        models.extend(payload.get("models", []))
        next_page_token = payload.get("nextPageToken")
        if not next_page_token:
            return models


def verify_requested_models(models: list[str], *, api_key: str) -> dict[str, dict[str, Any]]:
    available = _fetch_available_models(api_key)
    by_name = {str(item.get("name") or ""): item for item in available}
    verified: dict[str, dict[str, Any]] = {}
    for model in models:
        full_name = f"models/{model}"
        metadata = by_name.get(full_name)
        if metadata is None:
            raise NexUIError(
                f"Gemini model {model!r} is not accepted by the current API. "
                "Do not replace it without explicit approval."
            )
        methods = set(metadata.get("supportedGenerationMethods") or [])
        if "generateContent" not in methods:
            raise NexUIError(
                f"Gemini model {model!r} does not advertise generateContent support."
            )
        verified[model] = metadata
    return verified


def _count_tokens(
    model: str,
    *,
    api_key: str,
    generate_content_request: dict[str, Any] | None = None,
    contents: list[dict[str, Any]] | None = None,
) -> int:
    if generate_content_request is None and contents is None:
        raise NexUIError("countTokens requires generate_content_request or contents.")
    payload: dict[str, Any] = {}
    if generate_content_request is not None:
        payload["generateContentRequest"] = generate_content_request
    if contents is not None:
        payload["contents"] = contents
    response = _gemini_api_post_json(
        f"{MODELS_ENDPOINT_URL}/{urllib.parse.quote(model, safe='')}:countTokens",
        payload,
        api_key=api_key,
    )
    total_tokens = response.get("totalTokens")
    if not isinstance(total_tokens, int):
        raise NexUIError(
            f"Gemini countTokens for {model!r} returned no totalTokens field: {response!r}"
        )
    return total_tokens


def _oracle_prompt_cost(
    task_dir: Path,
    *,
    split: str,
    model: str,
    league: str,
    model_options: dict[str, Any],
    api_key: str,
    pricing_by_model: dict[str, dict[str, float]],
) -> EstimateRecord:
    task = load_task(task_dir)
    options = dict(model_options)
    options["prompt_league"] = league
    config = GeminiAgentConfig.from_options(options)
    agent = GeminiAgent(task, config)
    current_snapshot = task.start_snapshot
    prompt_token_count = 0
    visible_output_token_count = 0
    oracle_step_count = 0
    thinking_budget = max(int(config.thinking_budget or 0), 0)

    for step in task.oracle_steps:
        observation = task.build_observation(current_snapshot)
        prompt = agent._build_prompt(observation)
        prompt_token_count += _count_tokens(
            model,
            api_key=api_key,
            contents=[{"parts": [{"text": prompt}]}],
        )
        response_text = json.dumps(step, ensure_ascii=True, sort_keys=True)
        visible_output_token_count += _count_tokens(
            model,
            api_key=api_key,
            contents=[{"parts": [{"text": response_text}]}],
        )
        oracle_step_count += 1

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

    expected_reasoning = thinking_budget * oracle_step_count
    expected_output = visible_output_token_count + expected_reasoning
    conservative_output = oracle_step_count * (config.max_output_tokens + thinking_budget)
    return EstimateRecord(
        model=model,
        league=league,
        task_id=task.task_id,
        split=split,
        source_surface=task.source_surface,
        difficulty_band=str(task.manifest.get("difficulty_band", "unknown")),
        oracle_step_count=oracle_step_count,
        prompt_profile=config.prompt_profile,
        thinking_budget=thinking_budget,
        max_output_tokens=config.max_output_tokens,
        prompt_token_count=prompt_token_count,
        visible_output_token_count=visible_output_token_count,
        expected_reasoning_token_count=expected_reasoning,
        expected_output_token_count=expected_output,
        conservative_output_token_count=conservative_output,
        expected_cost_usd=_estimate_cost(
            model,
            prompt_token_count,
            expected_output,
            pricing_by_model,
        ),
        conservative_cost_usd=_estimate_cost(
            model,
            prompt_token_count,
            conservative_output,
            pricing_by_model,
        ),
    )


def _estimate_summary(estimates: list[EstimateRecord], models: list[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    expected_total = 0.0
    conservative_total = 0.0
    for model in models:
        model_rows = [row for row in estimates if row.model == model]
        expected_cost = _round_cost(sum(row.expected_cost_usd for row in model_rows))
        conservative_cost = _round_cost(sum(row.conservative_cost_usd for row in model_rows))
        expected_total += expected_cost
        conservative_total += conservative_cost
        rows.append(
            {
                "model": model,
                "tasks": len(model_rows),
                "oracle_steps": sum(row.oracle_step_count for row in model_rows),
                "prompt_token_count": sum(row.prompt_token_count for row in model_rows),
                "visible_output_token_count": sum(
                    row.visible_output_token_count for row in model_rows
                ),
                "expected_reasoning_token_count": sum(
                    row.expected_reasoning_token_count for row in model_rows
                ),
                "expected_output_token_count": sum(
                    row.expected_output_token_count for row in model_rows
                ),
                "conservative_output_token_count": sum(
                    row.conservative_output_token_count for row in model_rows
                ),
                "expected_cost_usd": expected_cost,
                "conservative_cost_usd": conservative_cost,
            }
        )
    return {
        "generated_at": _utc_now(),
        "models": models,
        "rows": rows,
        "expected_total_usd": _round_cost(expected_total),
        "conservative_total_usd": _round_cost(conservative_total),
    }


def _write_cost_estimate_md(
    path: Path,
    *,
    split: str,
    league: str,
    summary: dict[str, Any],
    pricing: dict[str, Any],
    session_stop_limit_usd: float,
    max_budget_usd: float,
) -> None:
    lines = [
        "# Gemini Flash Baseline Cost Estimate",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Split: `{split}`",
        f"- League: `{league}`",
        f"- Pricing source: `{pricing['source_url']}`",
        f"- Pricing fetched at: `{pricing['fetched_at']}`",
        f"- Budget stop threshold: `${session_stop_limit_usd:.2f}`",
        f"- Absolute max budget: `${max_budget_usd:.2f}`",
        "",
        "| Model | Tasks | Oracle steps | Prompt tokens | Visible output tokens | Reasoning tokens | Expected output tokens | Conservative output tokens | Expected cost | Conservative cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["rows"]:
        lines.append(
            f"| `{row['model']}` | {row['tasks']} | {row['oracle_steps']} | "
            f"{row['prompt_token_count']} | {row['visible_output_token_count']} | "
            f"{row['expected_reasoning_token_count']} | {row['expected_output_token_count']} | "
            f"{row['conservative_output_token_count']} | ${row['expected_cost_usd']:.4f} | "
            f"${row['conservative_cost_usd']:.4f} |"
        )
    lines.extend(
        [
            "",
            f"- Expected total cost: `${summary['expected_total_usd']:.4f}`",
            f"- Conservative total cost: `${summary['conservative_total_usd']:.4f}`",
        ]
    )
    if summary["conservative_total_usd"] > session_stop_limit_usd:
        lines.append(
            f"- Status: conservative estimate exceeds the `${session_stop_limit_usd:.2f}` start threshold."
        )
    else:
        lines.append("- Status: conservative estimate is within the configured start threshold.")
    write_text(path, "\n".join(lines) + "\n")


def _build_model_options(model: str, league: str) -> dict[str, Any]:
    options = dict(FLASH_PRESETS[model])
    options["prompt_league"] = league
    return options


def _artifact_paths(
    output_root: Path,
    *,
    kind: str,
    model: str,
    task_id: str,
    attempt_index: int,
) -> tuple[Path, Path]:
    base_dir = output_root / kind / _model_label(model)
    canonical_path = base_dir / f"{task_id}.json"
    attempt_path = base_dir / f"{task_id}.attempt-{attempt_index:02d}.json"
    return canonical_path, attempt_path


def _write_artifact(
    output_root: Path,
    *,
    kind: str,
    model: str,
    task_id: str,
    attempt_index: int,
    payload: dict[str, Any],
) -> tuple[str, str]:
    canonical_path, attempt_path = _artifact_paths(
        output_root,
        kind=kind,
        model=model,
        task_id=task_id,
        attempt_index=attempt_index,
    )
    write_json(attempt_path, payload)
    write_json(canonical_path, payload)
    return str(canonical_path), str(attempt_path)


def _run_one(
    *,
    task_dir: Path,
    split: str,
    model: str,
    league: str,
    model_options: dict[str, Any],
    pricing_by_model: dict[str, dict[str, float]],
    max_steps_override: int | None,
    reseed_required_tasks: bool,
    attempt_index: int,
    starting_cumulative_cost_usd: float,
    session_stop_limit_usd: float,
) -> RunAttemptResult:
    task = load_task(task_dir)
    if reseed_required_tasks and task.requires_source_reset and task.source_surface:
        reseed_source(task.source_surface)

    max_steps = _resolve_max_steps(task, max_steps_override)
    observer = TaskBudgetObserver(
        model=model,
        pricing_by_model=pricing_by_model,
        starting_cumulative_cost_usd=starting_cumulative_cost_usd,
        session_stop_limit_usd=session_stop_limit_usd,
    )
    started = time.perf_counter()
    trace, score = run_task(
        task,
        agent_name="gemini",
        max_steps=max_steps,
        agent_options=model_options,
        step_callback=observer.on_step,
    )
    elapsed_s = round(time.perf_counter() - started, 3)
    usage = _summarize_trace_usage(trace)
    measured_cost = _estimate_cost(
        model,
        usage["prompt_token_count"],
        usage["billed_output_token_count"],
        pricing_by_model,
    )
    invalid_step = _first_invalid_step(trace)
    runtime_error = (trace.get("result") or {}).get("runtime_error") or {}
    trace_status = str((trace.get("result") or {}).get("status") or "")
    if trace_status == "runtime_error":
        status = RESULT_STATUS_RUNTIME_ERROR
        error_payload = {
            "generated_at": _utc_now(),
            "status": RESULT_STATUS_RUNTIME_ERROR,
            "model": model,
            "league": league,
            "task_id": task.task_id,
            "attempt_index": attempt_index,
            "provider": runtime_error.get("provider"),
            "category": runtime_error.get("category"),
            "retryable": bool(runtime_error.get("retryable")),
            "message": runtime_error.get("message") or trace["result"].get("termination_reason"),
            "details": runtime_error.get("details") or {},
            "measured_cost_usd": measured_cost,
            "elapsed_s": elapsed_s,
        }
    else:
        status = (
            RESULT_STATUS_STOPPED_BUDGET
            if observer.stop_requested
            and trace["result"].get("termination_reason") == "budget_limit_reached"
            else RESULT_STATUS_COMPLETED
        )
        error_payload = None

    metrics = score.get("metrics", {})
    record = {
        "attempt_index": attempt_index,
        "status": status,
        "will_retry": False,
        "retryable_runtime_error": bool(runtime_error.get("retryable"))
        if status == RESULT_STATUS_RUNTIME_ERROR
        else False,
        "model": model,
        "league": league,
        "prompt_profile": str(model_options.get("prompt_profile") or ""),
        "task_id": task.task_id,
        "split": split,
        "source_surface": task.source_surface,
        "difficulty_band": str(task.manifest.get("difficulty_band", "unknown")),
        "risk_level": str(task.manifest.get("risk_level", "unknown")),
        "oracle_step_count": len(task.oracle_steps),
        "max_steps": max_steps,
        "model_config": dict(model_options),
        "benchmark_pass": bool(score["passed"]),
        "task_success": bool(metrics.get("task_success", False)),
        "safety_pass": bool(metrics.get("safety_pass", False)),
        "critical_safety_violation": bool(
            metrics.get("critical_safety_violation", False)
        ),
        "step_efficiency": float(metrics.get("step_efficiency", 0.0)),
        "invalid_action_count": int(metrics.get("invalid_action_count", 0)),
        "explanation_action_alignment": float(
            metrics.get("explanation_action_alignment", 0.0)
        ),
        "explanation_current_state_grounding": float(
            metrics.get("explanation_pre_state_grounding", 0.0)
        ),
        "explanation_goal_linkage": float(metrics.get("explanation_goal_linkage", 0.0)),
        "explanation_resulting_state_faithfulness": float(
            metrics.get("explanation_post_state_faithfulness", 0.0)
        ),
        "safety_communication": float(
            metrics.get("explanation_safety_calibration", 0.0)
        ),
        "explanation_conciseness": float(metrics.get("explanation_conciseness", 0.0)),
        "overall_explanation_score": float(metrics.get("explanation_overall", 0.0)),
        "final_summary_score_or_status": float(metrics.get("final_summary_quality", 0.0)),
        "step_count": len(trace.get("steps", [])),
        "elapsed_s": elapsed_s,
        "task_latency_ms": _summarize_trace_latency_ms(trace),
        "prompt_token_count": usage["prompt_token_count"],
        "candidate_output_token_count": usage["candidate_output_token_count"],
        "thought_token_count": usage["thought_token_count"],
        "billed_output_token_count": usage["billed_output_token_count"],
        "measured_cost_usd": measured_cost,
        "trace_path": None,
        "trace_attempt_path": None,
        "score_path": None,
        "score_attempt_path": None,
        "error_path": None,
        "error_attempt_path": None,
        "error": runtime_error.get("message") if status == RESULT_STATUS_RUNTIME_ERROR else None,
        "notes": list(score.get("notes", [])),
        "termination_reason": trace.get("result", {}).get("termination_reason"),
        "run_status": trace.get("result", {}).get("status"),
        "final_snapshot": _final_snapshot(trace, task.start_snapshot),
        "explanation_mode": score.get("explanation_mode"),
        "first_invalid_step_index": None
        if invalid_step is None
        else int(invalid_step["step_index"]),
        "first_invalid_message": None
        if invalid_step is None
        else str((invalid_step.get("validation") or {}).get("message") or ""),
        "first_invalid_action_type": None
        if invalid_step is None
        else str((((invalid_step.get("submission") or {}).get("action") or {}).get("type") or "")),
        "first_invalid_target": None
        if invalid_step is None
        else str((((invalid_step.get("submission") or {}).get("action") or {}).get("target") or "")),
        "first_invalid_before_snapshot": None
        if invalid_step is None
        else str(invalid_step.get("before_snapshot") or ""),
        "action_sequence": [
            str((((step.get("submission") or {}).get("action") or {}).get("type") or ""))
            for step in trace.get("steps", [])
        ],
        "created_at": _utc_now(),
    }
    return RunAttemptResult(
        trace=trace,
        score=score,
        record=record,
        error_payload=error_payload,
    )


def _combo_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record["model"]),
        str(record["task_id"]),
        str(record["league"]),
    )


def _latest_records_by_combo(records: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in records:
        latest[_combo_key(record)] = record
    return latest


def _next_attempt_index(
    records: list[dict[str, Any]],
    *,
    model: str,
    task_id: str,
    league: str,
) -> int:
    max_attempt = 0
    for record in records:
        if (
            record.get("model") == model
            and record.get("task_id") == task_id
            and record.get("league") == league
        ):
            max_attempt = max(max_attempt, int(record.get("attempt_index") or 0))
    return max_attempt + 1


def _expected_combinations(
    *,
    models: list[str],
    task_ids: list[str],
    league: str,
) -> list[tuple[str, str, str]]:
    return [(model, task_id, league) for model in models for task_id in task_ids]


def _next_unfinished_combination(
    *,
    models: list[str],
    task_ids: list[str],
    league: str,
    latest_records: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, str] | None:
    for model, task_id, league_name in _expected_combinations(
        models=models,
        task_ids=task_ids,
        league=league,
    ):
        latest = latest_records.get((model, task_id, league_name))
        if latest is None or latest.get("status") != RESULT_STATUS_COMPLETED:
            return {"model": model, "task_id": task_id, "league": league_name}
    return None


def _failure_type(record: dict[str, Any]) -> str:
    status = str(record.get("status") or "")
    if status == RESULT_STATUS_RUNTIME_ERROR:
        return (
            f"runtime_error:{record.get('error') or record.get('termination_reason') or 'unknown'}"
        )[:120]
    if status == RESULT_STATUS_STOPPED_BUDGET:
        return "stopped_budget"
    if record.get("first_invalid_message"):
        return f"invalid_action:{str(record['first_invalid_message'])[:80]}"
    if not record.get("task_success"):
        return f"task_failure:{record.get('termination_reason') or record.get('run_status') or 'unknown'}"
    if not record.get("safety_pass"):
        return "safety_failure"
    return "other"


def _safe_average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _build_results_bundle(
    *,
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    deep_validate: bool,
) -> dict[str, Any]:
    models = list(manifest["models"])
    task_ids = list(manifest["task_ids"])
    league = str(manifest["league"])
    latest_records = _latest_records_by_combo(records)
    latest_rows = [
        latest_records[key]
        for key in _expected_combinations(models=models, task_ids=task_ids, league=league)
        if key in latest_records
    ]
    completed_latest = [row for row in latest_rows if row["status"] == RESULT_STATUS_COMPLETED]
    paper_summary: list[dict[str, Any]] = []
    explanation_components: list[dict[str, Any]] = []
    failure_summary: list[dict[str, Any]] = []
    for model in models:
        model_attempts = [row for row in records if row["model"] == model]
        model_latest = [row for row in latest_rows if row["model"] == model]
        model_completed = [row for row in model_latest if row["status"] == RESULT_STATUS_COMPLETED]
        metrics_source = model_completed
        paper_summary.append(
            {
                "model": model,
                "tasks_attempted": len(
                    {
                        (row["model"], row["task_id"], row["league"])
                        for row in model_attempts
                    }
                ),
                "tasks_completed": len(model_completed),
                "task_success_rate": round(
                    _safe_average([1.0 if row["task_success"] else 0.0 for row in metrics_source]),
                    4,
                ),
                "benchmark_pass_rate": round(
                    _safe_average([1.0 if row["benchmark_pass"] else 0.0 for row in metrics_source]),
                    4,
                ),
                "safety_pass_rate": round(
                    _safe_average([1.0 if row["safety_pass"] else 0.0 for row in metrics_source]),
                    4,
                ),
                "mean_step_efficiency": round(
                    _safe_average([float(row["step_efficiency"]) for row in metrics_source]),
                    4,
                ),
                "mean_explanation_score": round(
                    _safe_average([float(row["overall_explanation_score"]) for row in metrics_source]),
                    4,
                ),
                "invalid_action_count": sum(
                    int(row["invalid_action_count"]) for row in metrics_source
                ),
                "runtime_error_count": sum(
                    1 for row in model_attempts if row["status"] == RESULT_STATUS_RUNTIME_ERROR
                ),
                "input_tokens": sum(int(row["prompt_token_count"]) for row in model_attempts),
                "output_tokens": sum(
                    int(row["candidate_output_token_count"]) for row in model_attempts
                ),
                "reasoning_tokens": sum(
                    int(row["thought_token_count"]) for row in model_attempts
                ),
                "total_api_cost_usd": _round_cost(
                    sum(float(row["measured_cost_usd"]) for row in model_attempts)
                ),
                "mean_latency_s": round(
                    _safe_average([float(row["elapsed_s"]) for row in metrics_source]),
                    4,
                ),
            }
        )
        explanation_components.append(
            {
                "model": model,
                "action_alignment": round(
                    _safe_average(
                        [float(row["explanation_action_alignment"]) for row in metrics_source]
                    ),
                    4,
                ),
                "current_state_grounding": round(
                    _safe_average(
                        [
                            float(row["explanation_current_state_grounding"])
                            for row in metrics_source
                        ]
                    ),
                    4,
                ),
                "goal_linkage": round(
                    _safe_average(
                        [float(row["explanation_goal_linkage"]) for row in metrics_source]
                    ),
                    4,
                ),
                "resulting_state_faithfulness": round(
                    _safe_average(
                        [
                            float(row["explanation_resulting_state_faithfulness"])
                            for row in metrics_source
                        ]
                    ),
                    4,
                ),
                "safety_communication": round(
                    _safe_average([float(row["safety_communication"]) for row in metrics_source]),
                    4,
                ),
                "conciseness": round(
                    _safe_average([float(row["explanation_conciseness"]) for row in metrics_source]),
                    4,
                ),
            }
        )
        failure_counts: dict[str, int] = {}
        for row in model_latest:
            if row["status"] == RESULT_STATUS_COMPLETED and row["benchmark_pass"]:
                continue
            label = _failure_type(row)
            failure_counts[label] = failure_counts.get(label, 0) + 1
        for label, count in sorted(failure_counts.items(), key=lambda item: (-item[1], item[0])):
            failure_summary.append({"model": model, "failure_type": label, "count": count})
    validation = _validate_results(
        manifest=manifest,
        records=records,
        latest_rows=latest_rows,
        completed_latest=completed_latest,
        deep_validate=deep_validate,
    )
    return {
        "generated_at": _utc_now(),
        "run_status": manifest["run_status"],
        "stop_reason": manifest.get("stop_reason"),
        "split": manifest["split"],
        "league": manifest["league"],
        "models": models,
        "task_ids": task_ids,
        "paper_summary": paper_summary,
        "explanation_components": explanation_components,
        "failure_type_summaries": failure_summary,
        "attempt_records": records,
        "latest_records": latest_rows,
        "validation": validation,
        "cumulative_cost_usd": manifest["cumulative_cost_usd"],
    }


def _validate_results(
    *,
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    latest_rows: list[dict[str, Any]],
    completed_latest: list[dict[str, Any]],
    deep_validate: bool,
) -> dict[str, Any]:
    models = list(manifest["models"])
    task_ids = list(manifest["task_ids"])
    league = str(manifest["league"])
    expected_keys = set(_expected_combinations(models=models, task_ids=task_ids, league=league))
    completed_keys = {_combo_key(row) for row in completed_latest}
    missing = [
        {"model": model, "task_id": task_id, "league": league_name}
        for model, task_id, league_name in _expected_combinations(
            models=models,
            task_ids=task_ids,
            league=league,
        )
        if (model, task_id, league_name) not in completed_keys
    ]
    duplicate_completed: list[dict[str, Any]] = []
    completed_counts: dict[tuple[str, str, str], int] = {}
    for record in records:
        if record.get("status") != RESULT_STATUS_COMPLETED:
            continue
        key = _combo_key(record)
        completed_counts[key] = completed_counts.get(key, 0) + 1
    for key, count in sorted(completed_counts.items()):
        if count > 1:
            duplicate_completed.append(
                {"model": key[0], "task_id": key[1], "league": key[2], "count": count}
            )
    validation: dict[str, Any] = {
        "expected_record_count": len(expected_keys),
        "completed_record_count": len(completed_latest),
        "per_model_completed_counts": {
            model: sum(1 for row in completed_latest if row["model"] == model) for model in models
        },
        "missing_combinations": missing,
        "duplicate_completed_combinations": duplicate_completed,
        "within_budget": float(manifest["cumulative_cost_usd"]) < float(manifest["max_budget_usd"]),
        "complete": len(completed_latest) == len(expected_keys) and not duplicate_completed,
        "trace_score_mismatches": [],
        "score_regeneration_mismatches": [],
    }
    if not deep_validate:
        return validation

    for record in completed_latest:
        trace_path = record.get("trace_attempt_path") or record.get("trace_path")
        score_path = record.get("score_attempt_path") or record.get("score_path")
        if not trace_path or not score_path:
            validation["trace_score_mismatches"].append(
                {"model": record["model"], "task_id": record["task_id"], "reason": "missing_paths"}
            )
            continue
        if not Path(trace_path).exists() or not Path(score_path).exists():
            validation["trace_score_mismatches"].append(
                {
                    "model": record["model"],
                    "task_id": record["task_id"],
                    "reason": "missing_files",
                }
            )
            continue
        task = load_task(Path(manifest["tasks_root"]) / str(record["task_id"]))
        trace = load_trace(trace_path)
        saved_score = read_json(Path(score_path))
        regenerated_score = score_trace(task, trace)
        if saved_score != regenerated_score:
            validation["score_regeneration_mismatches"].append(
                {"model": record["model"], "task_id": record["task_id"]}
            )
    return validation


def _write_summary_md(path: Path, *, manifest: dict[str, Any], bundle: dict[str, Any]) -> None:
    lines = [
        "# Gemini Flash Baseline Evaluation",
        "",
        f"- Run: `{manifest['run_name']}`",
        f"- Generated at: `{bundle['generated_at']}`",
        f"- Status: `{manifest['run_status']}`",
        f"- Stop reason: `{manifest.get('stop_reason') or 'n/a'}`",
        f"- Split: `{manifest['split']}`",
        f"- League: `{manifest['league']}`",
        f"- Models: `{', '.join(manifest['models'])}`",
        f"- Cumulative API cost: `${manifest['cumulative_cost_usd']:.4f}`",
        f"- Session budget limit: `${manifest['current_budget_limit_usd']:.2f}`",
        f"- Absolute max budget: `${manifest['max_budget_usd']:.2f}`",
        "",
        "## Paper Summary",
        "",
        "| Model | Tasks attempted | Tasks completed | Task success rate | Benchmark pass rate | Safety pass rate | Mean step efficiency | Mean explanation score | Invalid actions | Runtime errors | Input tokens | Output tokens | Reasoning tokens | Total API cost | Mean latency (s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in bundle["paper_summary"]:
        lines.append(
            f"| `{row['model']}` | {row['tasks_attempted']} | {row['tasks_completed']} | "
            f"{row['task_success_rate']:.1%} | {row['benchmark_pass_rate']:.1%} | "
            f"{row['safety_pass_rate']:.1%} | {row['mean_step_efficiency']:.4f} | "
            f"{row['mean_explanation_score']:.4f} | {row['invalid_action_count']} | "
            f"{row['runtime_error_count']} | {row['input_tokens']} | {row['output_tokens']} | "
            f"{row['reasoning_tokens']} | ${row['total_api_cost_usd']:.4f} | {row['mean_latency_s']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Explanation Components",
            "",
            "| Model | Action alignment | Current-state grounding | Goal linkage | Resulting-state faithfulness | Safety communication | Conciseness |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in bundle["explanation_components"]:
        lines.append(
            f"| `{row['model']}` | {row['action_alignment']:.4f} | "
            f"{row['current_state_grounding']:.4f} | {row['goal_linkage']:.4f} | "
            f"{row['resulting_state_faithfulness']:.4f} | {row['safety_communication']:.4f} | "
            f"{row['conciseness']:.4f} |"
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
    for row in bundle["failure_type_summaries"]:
        lines.append(f"| `{row['model']}` | `{row['failure_type']}` | {row['count']} |")
    validation = bundle["validation"]
    lines.extend(
        [
            "",
            "## Validation",
            "",
            f"- Completed records: `{validation['completed_record_count']}` / `{validation['expected_record_count']}`",
            f"- Within budget: `{validation['within_budget']}`",
            f"- Complete: `{validation['complete']}`",
            f"- Missing combinations: `{len(validation['missing_combinations'])}`",
            f"- Duplicate completed combinations: `{len(validation['duplicate_completed_combinations'])}`",
            f"- Trace/score mismatches: `{len(validation['trace_score_mismatches'])}`",
            f"- Score regeneration mismatches: `{len(validation['score_regeneration_mismatches'])}`",
        ]
    )
    write_text(path, "\n".join(lines) + "\n")


def _write_results_outputs(
    output_root: Path,
    *,
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    deep_validate: bool,
) -> dict[str, Any]:
    bundle = _build_results_bundle(manifest=manifest, records=records, deep_validate=deep_validate)
    write_json(output_root / "results.json", bundle)
    write_json(
        output_root / "failure_summary.json",
        {
            "generated_at": bundle["generated_at"],
            "failure_type_summaries": bundle["failure_type_summaries"],
        },
    )
    _write_summary_md(output_root / "summary.md", manifest=manifest, bundle=bundle)
    return bundle


def _write_checkpoint(
    output_root: Path,
    *,
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
) -> None:
    latest = _latest_records_by_combo(records)
    completed = [
        {"model": key[0], "task_id": key[1], "league": key[2]}
        for key, record in sorted(latest.items())
        if record.get("status") == RESULT_STATUS_COMPLETED
    ]
    checkpoint = {
        "completed_run_count": len(completed),
        "completed_combinations": completed,
        "next_unfinished_combination": manifest.get("next_unfinished_combination"),
        "cumulative_cost_usd": manifest["cumulative_cost_usd"],
        "last_successful_write_time": _utc_now(),
        "current_run_status": manifest["run_status"],
    }
    write_json(output_root / "checkpoint.json", checkpoint)


def _session_budget_limit(
    *,
    max_budget_usd: float,
    resume: bool,
    prior_run_status: str | None,
) -> float:
    if resume and prior_run_status == RUN_STATUS_STOPPED_BUDGET:
        return float(max_budget_usd)
    return min(float(max_budget_usd) - MIN_BUDGET_RESERVE_USD, FRESH_BUDGET_STOP_THRESHOLD_USD)


def _ensure_budget_configuration(max_budget_usd: float) -> None:
    if max_budget_usd <= MIN_BUDGET_RESERVE_USD:
        raise NexUIError("--max-budget-usd must be greater than 1.00.")


def _new_run_name(split: str, league: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"flash-{split}-{league}-{timestamp}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Estimate or run Gemini Flash baselines on a NExUI split.",
    )
    parser.add_argument(
        "--resume",
        help="Resume an existing run directory under reports/baselines/<run-name>",
    )
    parser.add_argument(
        "--split",
        choices=["dev", "validation", "test", "challenge"],
        help="Split manifest to evaluate",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        help="Flash baseline model ids to evaluate",
    )
    parser.add_argument(
        "--leagues",
        nargs="+",
        choices=list(PROMPT_LEAGUES),
        help="Prompt league to evaluate; this runner currently supports one league per run",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional cap on the number of tasks from the chosen split",
    )
    parser.add_argument(
        "--tasks-root",
        help="Task root directory",
    )
    parser.add_argument(
        "--splits-root",
        help="Split manifests directory",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory that will contain the run directory",
    )
    parser.add_argument(
        "--run-name",
        help="Optional run directory name for a new run",
    )
    parser.add_argument(
        "--estimate-only",
        action="store_true",
        help="Build exact prompts and token estimates without running live generateContent calls",
    )
    parser.add_argument(
        "--save-traces",
        action="store_true",
        default=None,
        help="Persist per-task traces under the output directory",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        help="Override the automatic step budget rule",
    )
    parser.add_argument(
        "--reseed-required-tasks",
        action="store_true",
        default=None,
        help="Run source reseed hooks before tasks marked requires_source_reset",
    )
    parser.add_argument(
        "--max-budget-usd",
        type=float,
        default=10.0,
        help="Maximum approved total budget in USD",
    )
    return parser


def _build_frozen_config(
    *,
    split: str,
    models: list[str],
    league: str,
    task_ids: list[str],
    tasks_root: Path,
    splits_root: Path,
    save_traces: bool,
    max_steps_override: int | None,
    reseed_required_tasks: bool,
    max_budget_usd: float,
) -> dict[str, Any]:
    return {
        "split": split,
        "models": models,
        "league": league,
        "task_ids": task_ids,
        "tasks_root": str(tasks_root),
        "splits_root": str(splits_root),
        "save_traces": save_traces,
        "max_steps": max_steps_override,
        "reseed_required_tasks": reseed_required_tasks,
        "max_budget_usd": float(max_budget_usd),
        "step_budget_rule": _step_budget_rule(max_steps_override),
        "model_options_by_model": {
            model: _build_model_options(model, league) for model in models
        },
    }


def _assert_resume_configuration_matches(
    args: argparse.Namespace,
    *,
    manifest: dict[str, Any],
) -> None:
    frozen = manifest["frozen_config"]
    checks = {
        "split": args.split,
        "tasks_root": args.tasks_root,
        "splits_root": args.splits_root,
        "run_name": args.run_name,
    }
    for field_name, requested in checks.items():
        if requested is None:
            continue
        if field_name == "run_name":
            raise NexUIError("--run-name cannot be used with --resume.")
        expected = frozen[field_name]
        if str(requested) != str(expected):
            raise NexUIError(
                f"Resume configuration mismatch for {field_name}: expected {expected!r}, got {requested!r}"
            )
    if args.limit is not None:
        raise NexUIError("--limit cannot be changed on resume.")
    if args.max_steps is not None and args.max_steps != frozen["max_steps"]:
        raise NexUIError(
            f"Resume configuration mismatch for max_steps: expected {frozen['max_steps']!r}, got {args.max_steps!r}"
        )
    if args.models is not None and list(args.models) != list(frozen["models"]):
        raise NexUIError("Resume configuration mismatch for model list.")
    if args.leagues is not None and list(args.leagues) != [frozen["league"]]:
        raise NexUIError("Resume configuration mismatch for prompt league.")
    if args.save_traces is not None and bool(args.save_traces) != bool(frozen["save_traces"]):
        raise NexUIError("Resume configuration mismatch for save_traces.")
    if (
        args.reseed_required_tasks is not None
        and bool(args.reseed_required_tasks) != bool(frozen["reseed_required_tasks"])
    ):
        raise NexUIError("Resume configuration mismatch for reseed_required_tasks.")
    if round(float(args.max_budget_usd), 2) != round(float(frozen["max_budget_usd"]), 2):
        raise NexUIError("Resume configuration mismatch for max_budget_usd.")


def _create_manifest(
    *,
    run_name: str,
    output_root: Path,
    split: str,
    league: str,
    models: list[str],
    task_ids: list[str],
    tasks_root: Path,
    splits_root: Path,
    save_traces: bool,
    max_steps_override: int | None,
    reseed_required_tasks: bool,
    max_budget_usd: float,
    current_budget_limit_usd: float,
    pricing: dict[str, Any],
    verified_models: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    repo_root = _repo_root()
    return {
        "run_name": run_name,
        "created_at": _utc_now(),
        "repo_root": str(repo_root),
        "output_root": str(output_root),
        "git_commit": _git_commit(repo_root),
        "archive_identifier": _git_commit(repo_root) or "workspace",
        "split": split,
        "task_ids": task_ids,
        "models": models,
        "league": league,
        "prompt_profiles": {
            model: _build_model_options(model, league)["prompt_profile"] for model in models
        },
        "model_parameters": {
            model: _build_model_options(model, league) for model in models
        },
        "step_budget_rule": _step_budget_rule(max_steps_override),
        "pricing_assumptions": pricing,
        "max_budget_usd": float(max_budget_usd),
        "budget_stop_threshold_usd": float(FRESH_BUDGET_STOP_THRESHOLD_USD),
        "current_budget_limit_usd": float(current_budget_limit_usd),
        "cumulative_cost_usd": 0.0,
        "run_status": RUN_STATUS_RUNNING,
        "stop_reason": None,
        "next_unfinished_combination": {
            "model": models[0],
            "task_id": task_ids[0],
            "league": league,
        },
        "save_traces": save_traces,
        "tasks_root": str(tasks_root),
        "splits_root": str(splits_root),
        "software_versions": {
            "python": sys.version,
            "nexui": NEXUI_VERSION,
        },
        "api_client_version": "gemini-api-generatecontent-v1beta via urllib",
        "verified_models": {
            model: {
                "name": metadata.get("name"),
                "displayName": metadata.get("displayName"),
                "supportedGenerationMethods": metadata.get("supportedGenerationMethods"),
                "thinking": metadata.get("thinking"),
            }
            for model, metadata in verified_models.items()
        },
        "frozen_config": _build_frozen_config(
            split=split,
            models=models,
            league=league,
            task_ids=task_ids,
            tasks_root=tasks_root,
            splits_root=splits_root,
            save_traces=save_traces,
            max_steps_override=max_steps_override,
            reseed_required_tasks=reseed_required_tasks,
            max_budget_usd=max_budget_usd,
        ),
    }


def _update_manifest_state(
    manifest: dict[str, Any],
    *,
    records: list[dict[str, Any]],
    run_status: str,
    stop_reason: str | None,
) -> None:
    latest = _latest_records_by_combo(records)
    manifest["run_status"] = run_status
    manifest["stop_reason"] = stop_reason
    manifest["cumulative_cost_usd"] = _round_cost(
        sum(float(record.get("measured_cost_usd") or 0.0) for record in records)
    )
    manifest["next_unfinished_combination"] = _next_unfinished_combination(
        models=list(manifest["models"]),
        task_ids=list(manifest["task_ids"]),
        league=str(manifest["league"]),
        latest_records=latest,
    )


def _final_run_status(
    *,
    records: list[dict[str, Any]],
    manifest: dict[str, Any],
    stop_reason: str | None,
) -> str:
    if stop_reason == "budget_limit_reached":
        return RUN_STATUS_STOPPED_BUDGET
    latest = _latest_records_by_combo(records)
    next_unfinished = _next_unfinished_combination(
        models=list(manifest["models"]),
        task_ids=list(manifest["task_ids"]),
        league=str(manifest["league"]),
        latest_records=latest,
    )
    if next_unfinished is None:
        return RUN_STATUS_COMPLETED
    return RUN_STATUS_INCOMPLETE_RUNTIME_ERRORS


def _prepare_new_run(args: argparse.Namespace) -> tuple[dict[str, Any], Path, list[dict[str, Any]]]:
    _ensure_budget_configuration(float(args.max_budget_usd))
    split = args.split or "validation"
    models = list(args.models or FLASH_PRESETS.keys())
    unknown = [model for model in models if model not in FLASH_PRESETS]
    if unknown:
        raise NexUIError(f"Unknown flash baseline model(s): {', '.join(unknown)}")
    leagues = list(args.leagues or ["platinum"])
    if len(leagues) != 1:
        raise NexUIError("This runner currently supports exactly one prompt league per run.")
    league = leagues[0]
    tasks_root = Path(args.tasks_root or default_tasks_root()).resolve()
    splits_root = Path(args.splits_root or default_splits_root()).resolve()
    task_ids = _load_task_ids(split, splits_root)
    if args.limit is not None:
        task_ids = task_ids[: args.limit]
    if not task_ids:
        raise NexUIError(f"No task ids selected from split {split!r}.")
    save_traces = True if args.save_traces is None else bool(args.save_traces)
    reseed_required_tasks = (
        False if args.reseed_required_tasks is None else bool(args.reseed_required_tasks)
    )
    run_name = args.run_name or _new_run_name(split, league)
    output_root = Path(args.output_dir or "reports/baselines").resolve() / run_name
    output_root.mkdir(parents=True, exist_ok=True)
    api_key = _load_api_key()
    verified_models = verify_requested_models(models, api_key=api_key)
    pricing = fetch_live_pricing()
    current_budget_limit_usd = _session_budget_limit(
        max_budget_usd=float(args.max_budget_usd),
        resume=False,
        prior_run_status=None,
    )
    manifest = _create_manifest(
        run_name=run_name,
        output_root=output_root,
        split=split,
        league=league,
        models=models,
        task_ids=task_ids,
        tasks_root=tasks_root,
        splits_root=splits_root,
        save_traces=save_traces,
        max_steps_override=args.max_steps,
        reseed_required_tasks=reseed_required_tasks,
        max_budget_usd=float(args.max_budget_usd),
        current_budget_limit_usd=current_budget_limit_usd,
        pricing=pricing,
        verified_models=verified_models,
    )
    write_json(output_root / "run_manifest.json", manifest)
    write_json(
        output_root / "checkpoint.json",
        {
            "completed_run_count": 0,
            "completed_combinations": [],
            "next_unfinished_combination": manifest["next_unfinished_combination"],
            "cumulative_cost_usd": 0.0,
            "last_successful_write_time": _utc_now(),
            "current_run_status": manifest["run_status"],
        },
    )
    return manifest, output_root, []


def _prepare_resume_run(args: argparse.Namespace) -> tuple[dict[str, Any], Path, list[dict[str, Any]]]:
    if args.estimate_only:
        raise NexUIError("--estimate-only cannot be combined with --resume.")
    output_root = Path(args.resume).resolve()
    manifest_path = output_root / "run_manifest.json"
    if not manifest_path.exists():
        raise NexUIError(f"Resume manifest not found: {manifest_path}")
    manifest = read_json(manifest_path)
    _assert_resume_configuration_matches(args, manifest=manifest)
    manifest["max_budget_usd"] = float(args.max_budget_usd)
    manifest["frozen_config"]["max_budget_usd"] = float(args.max_budget_usd)
    manifest["current_budget_limit_usd"] = _session_budget_limit(
        max_budget_usd=float(args.max_budget_usd),
        resume=True,
        prior_run_status=manifest.get("run_status"),
    )
    records = _load_jsonl(output_root / "results.jsonl")
    manifest["cumulative_cost_usd"] = _round_cost(
        sum(float(record.get("measured_cost_usd") or 0.0) for record in records)
    )
    manifest["run_status"] = RUN_STATUS_RUNNING
    manifest["stop_reason"] = None
    manifest["next_unfinished_combination"] = _next_unfinished_combination(
        models=list(manifest["models"]),
        task_ids=list(manifest["task_ids"]),
        league=str(manifest["league"]),
        latest_records=_latest_records_by_combo(records),
    )
    write_json(output_root / "run_manifest.json", manifest)
    _write_checkpoint(output_root, manifest=manifest, records=records)
    return manifest, output_root, records


def _write_estimate_files(
    output_root: Path,
    *,
    manifest: dict[str, Any],
    estimates: list[EstimateRecord],
) -> dict[str, Any]:
    summary = _estimate_summary(estimates, list(manifest["models"]))
    estimate_payload = {
        "generated_at": summary["generated_at"],
        "split": manifest["split"],
        "league": manifest["league"],
        "models": manifest["models"],
        "pricing_assumptions": manifest["pricing_assumptions"],
        "expected_total_usd": summary["expected_total_usd"],
        "conservative_total_usd": summary["conservative_total_usd"],
        "records": [asdict(row) for row in estimates],
        "rows": summary["rows"],
        "within_start_threshold": summary["conservative_total_usd"]
        <= manifest["budget_stop_threshold_usd"],
    }
    write_json(output_root / "cost_estimate.json", estimate_payload)
    _write_cost_estimate_md(
        output_root / "cost_estimate.md",
        split=manifest["split"],
        league=manifest["league"],
        summary=summary,
        pricing=manifest["pricing_assumptions"],
        session_stop_limit_usd=manifest["budget_stop_threshold_usd"],
        max_budget_usd=manifest["max_budget_usd"],
    )
    return estimate_payload


def _compute_estimates(manifest: dict[str, Any]) -> list[EstimateRecord]:
    api_key = _load_api_key()
    estimates: list[EstimateRecord] = []
    pricing_by_model = manifest["pricing_assumptions"]["pricing_by_model"]
    tasks_root = Path(manifest["tasks_root"])
    for model in manifest["models"]:
        model_options = dict(manifest["model_parameters"][model])
        for task_id in manifest["task_ids"]:
            estimates.append(
                _oracle_prompt_cost(
                    tasks_root / task_id,
                    split=manifest["split"],
                    model=model,
                    league=manifest["league"],
                    model_options=model_options,
                    api_key=api_key,
                    pricing_by_model=pricing_by_model,
                )
            )
    return estimates


def _persist_attempt(
    output_root: Path,
    *,
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    attempt: RunAttemptResult,
    save_traces: bool,
) -> None:
    record = attempt.record
    attempt_index = int(record["attempt_index"])
    if save_traces:
        trace_path, trace_attempt_path = _write_artifact(
            output_root,
            kind="traces",
            model=record["model"],
            task_id=record["task_id"],
            attempt_index=attempt_index,
            payload=attempt.trace,
        )
        record["trace_path"] = trace_path
        record["trace_attempt_path"] = trace_attempt_path
    score_path, score_attempt_path = _write_artifact(
        output_root,
        kind="scores",
        model=record["model"],
        task_id=record["task_id"],
        attempt_index=attempt_index,
        payload=attempt.score,
    )
    record["score_path"] = score_path
    record["score_attempt_path"] = score_attempt_path
    if attempt.error_payload is not None:
        error_path, error_attempt_path = _write_artifact(
            output_root,
            kind="errors",
            model=record["model"],
            task_id=record["task_id"],
            attempt_index=attempt_index,
            payload=attempt.error_payload,
        )
        record["error_path"] = error_path
        record["error_attempt_path"] = error_attempt_path
    append_jsonl_atomic(output_root / "results.jsonl", record)
    records.append(record)
    _update_manifest_state(
        manifest,
        records=records,
        run_status=manifest["run_status"],
        stop_reason=manifest.get("stop_reason"),
    )
    write_json(output_root / "run_manifest.json", manifest)
    _write_checkpoint(output_root, manifest=manifest, records=records)
    _write_results_outputs(output_root, manifest=manifest, records=records, deep_validate=False)


def _should_retry_immediately(
    record: dict[str, Any],
    *,
    immediate_retry_count: int,
    cumulative_cost_usd: float,
    max_budget_usd: float,
) -> bool:
    return (
        record["status"] == RESULT_STATUS_RUNTIME_ERROR
        and bool(record["retryable_runtime_error"])
        and immediate_retry_count < 1
        and (cumulative_cost_usd + float(record["measured_cost_usd"])) < max_budget_usd
    )


def _run_live(manifest: dict[str, Any], output_root: Path, records: list[dict[str, Any]]) -> int:
    pricing_by_model = manifest["pricing_assumptions"]["pricing_by_model"]
    tasks_root = Path(manifest["tasks_root"])
    current_budget_limit_usd = float(manifest["current_budget_limit_usd"])
    max_budget_usd = float(manifest["max_budget_usd"])
    latest = _latest_records_by_combo(records)

    for model in manifest["models"]:
        model_options = dict(manifest["model_parameters"][model])
        for task_id in manifest["task_ids"]:
            key = (model, task_id, manifest["league"])
            latest_record = latest.get(key)
            if latest_record is not None and latest_record.get("status") == RESULT_STATUS_COMPLETED:
                continue
            cumulative_cost_usd = _round_cost(
                sum(float(record.get("measured_cost_usd") or 0.0) for record in records)
            )
            if cumulative_cost_usd >= current_budget_limit_usd:
                manifest["run_status"] = RUN_STATUS_STOPPED_BUDGET
                manifest["stop_reason"] = "budget_limit_reached"
                _update_manifest_state(
                    manifest,
                    records=records,
                    run_status=RUN_STATUS_STOPPED_BUDGET,
                    stop_reason="budget_limit_reached",
                )
                write_json(output_root / "run_manifest.json", manifest)
                _write_checkpoint(output_root, manifest=manifest, records=records)
                _write_results_outputs(
                    output_root,
                    manifest=manifest,
                    records=records,
                    deep_validate=True,
                )
                return EXIT_BUDGET
            immediate_retry_count = 0
            while True:
                attempt_index = _next_attempt_index(
                    records,
                    model=model,
                    task_id=task_id,
                    league=manifest["league"],
                )
                attempt = _run_one(
                    task_dir=tasks_root / task_id,
                    split=manifest["split"],
                    model=model,
                    league=manifest["league"],
                    model_options=model_options,
                    pricing_by_model=pricing_by_model,
                    max_steps_override=manifest["frozen_config"]["max_steps"],
                    reseed_required_tasks=bool(
                        manifest["frozen_config"]["reseed_required_tasks"]
                    ),
                    attempt_index=attempt_index,
                    starting_cumulative_cost_usd=cumulative_cost_usd,
                    session_stop_limit_usd=current_budget_limit_usd,
                )
                runtime_retry = _should_retry_immediately(
                    attempt.record,
                    immediate_retry_count=immediate_retry_count,
                    cumulative_cost_usd=cumulative_cost_usd,
                    max_budget_usd=max_budget_usd,
                )
                attempt.record["will_retry"] = runtime_retry
                print(
                    f"[{model}] {task_id} :: attempt {attempt_index} :: "
                    f"{attempt.record['status']} :: cost~${attempt.record['measured_cost_usd']:.4f}",
                    flush=True,
                )
                if attempt.record["error"]:
                    print(f"  error: {attempt.record['error']}", flush=True)
                _persist_attempt(
                    output_root,
                    manifest=manifest,
                    records=records,
                    attempt=attempt,
                    save_traces=bool(manifest["save_traces"]),
                )
                cumulative_cost_usd = manifest["cumulative_cost_usd"]
                latest[key] = records[-1]
                if runtime_retry:
                    immediate_retry_count += 1
                    continue
                break
            if records[-1]["status"] == RESULT_STATUS_STOPPED_BUDGET:
                manifest["run_status"] = RUN_STATUS_STOPPED_BUDGET
                manifest["stop_reason"] = "budget_limit_reached"
                _update_manifest_state(
                    manifest,
                    records=records,
                    run_status=RUN_STATUS_STOPPED_BUDGET,
                    stop_reason="budget_limit_reached",
                )
                write_json(output_root / "run_manifest.json", manifest)
                _write_checkpoint(output_root, manifest=manifest, records=records)
                _write_results_outputs(
                    output_root,
                    manifest=manifest,
                    records=records,
                    deep_validate=True,
                )
                return EXIT_BUDGET

    final_status = _final_run_status(records=records, manifest=manifest, stop_reason=None)
    _update_manifest_state(
        manifest,
        records=records,
        run_status=final_status,
        stop_reason=None,
    )
    write_json(output_root / "run_manifest.json", manifest)
    _write_checkpoint(output_root, manifest=manifest, records=records)
    _write_results_outputs(output_root, manifest=manifest, records=records, deep_validate=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.resume:
            manifest, output_root, records = _prepare_resume_run(args)
        else:
            manifest, output_root, records = _prepare_new_run(args)

        estimates = _compute_estimates(manifest)
        estimate_payload = _write_estimate_files(output_root, manifest=manifest, estimates=estimates)
        if args.estimate_only:
            manifest["run_status"] = RUN_STATUS_ESTIMATE_ONLY
            write_json(output_root / "run_manifest.json", manifest)
            return 0

        if (
            not args.resume
            and estimate_payload["conservative_total_usd"] > manifest["budget_stop_threshold_usd"]
        ):
            manifest["run_status"] = RUN_STATUS_FAILED_CONFIG
            manifest["stop_reason"] = "conservative_estimate_exceeds_start_threshold"
            write_json(output_root / "run_manifest.json", manifest)
            _write_results_outputs(output_root, manifest=manifest, records=records, deep_validate=False)
            raise NexUIError(
                "Conservative estimate exceeds the $9.00 start threshold. "
                "Do not start the paid run."
            )

        return _run_live(manifest, output_root, records)
    except KeyboardInterrupt:
        if "manifest" in locals() and "output_root" in locals():
            manifest["run_status"] = RUN_STATUS_STOPPED_MANUAL
            manifest["stop_reason"] = "manual_interrupt"
            _update_manifest_state(
                manifest,
                records=records,
                run_status=RUN_STATUS_STOPPED_MANUAL,
                stop_reason="manual_interrupt",
            )
            write_json(output_root / "run_manifest.json", manifest)
            _write_checkpoint(output_root, manifest=manifest, records=records)
            _write_results_outputs(output_root, manifest=manifest, records=records, deep_validate=True)
        return EXIT_MANUAL
