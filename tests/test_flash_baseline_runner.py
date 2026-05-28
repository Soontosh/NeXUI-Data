from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nexui.flash_baseline_runner import (
    RESULT_STATUS_COMPLETED,
    RESULT_STATUS_RUNTIME_ERROR,
    RUN_STATUS_STOPPED_BUDGET,
    TaskBudgetObserver,
    _assert_resume_configuration_matches,
    _extract_model_pricing,
    _next_unfinished_combination,
    _oracle_prompt_cost,
    _session_budget_limit,
    _should_retry_immediately,
    _summarize_trace_usage,
)
from nexui.gemini_agent import GeminiAgent, GeminiAgentConfig, _json_load_tolerant
from nexui.io import NexUIError, append_jsonl_atomic, read_text
from nexui.task import load_task


class FlashBaselineRunnerTests(unittest.TestCase):
    def test_extract_model_pricing_parses_html_fragment(self) -> None:
        page_html = """
        <h2>Gemini 2.5 Flash</h2>
        <table class="pricing-table">
          <tr><th></th><th>Free</th><th>Paid Tier, per 1M tokens in USD</th></tr>
          <tr><td>Input price</td><td>Free</td><td>$0.30 (text / image / video)<br>$1.00 (audio)</td></tr>
          <tr><td>Output price (including thinking tokens)</td><td>Free</td><td>$2.50</td></tr>
        </table>
        """
        parsed = _extract_model_pricing(
            page_html,
            model="gemini-2.5-flash",
            title="Gemini 2.5 Flash",
        )
        self.assertEqual(parsed["input"], 0.30)
        self.assertEqual(parsed["output"], 2.50)

    def test_session_budget_limit_unlocks_absolute_cap_after_budget_stop(self) -> None:
        self.assertEqual(
            _session_budget_limit(
                max_budget_usd=10.0,
                resume=False,
                prior_run_status=None,
            ),
            9.0,
        )
        self.assertEqual(
            _session_budget_limit(
                max_budget_usd=10.0,
                resume=True,
                prior_run_status=RUN_STATUS_STOPPED_BUDGET,
            ),
            10.0,
        )

    def test_next_unfinished_combination_skips_only_completed_records(self) -> None:
        latest_records = {
            ("m1", "task-a", "platinum"): {
                "model": "m1",
                "task_id": "task-a",
                "league": "platinum",
                "status": RESULT_STATUS_RUNTIME_ERROR,
            },
            ("m1", "task-b", "platinum"): {
                "model": "m1",
                "task_id": "task-b",
                "league": "platinum",
                "status": RESULT_STATUS_COMPLETED,
            },
        }
        next_combo = _next_unfinished_combination(
            models=["m1"],
            task_ids=["task-a", "task-b"],
            league="platinum",
            latest_records=latest_records,
        )
        self.assertEqual(
            next_combo,
            {"model": "m1", "task_id": "task-a", "league": "platinum"},
        )

    def test_resume_configuration_mismatch_is_rejected(self) -> None:
        manifest = {
            "frozen_config": {
                "split": "validation",
                "tasks_root": "/tmp/tasks",
                "splits_root": "/tmp/splits",
                "max_steps": None,
                "models": ["gemini-2.5-flash-lite"],
                "league": "platinum",
                "save_traces": True,
                "reseed_required_tasks": False,
                "max_budget_usd": 10.0,
            }
        }
        args = argparse.Namespace(
            split=None,
            tasks_root=None,
            splits_root=None,
            run_name=None,
            limit=None,
            max_steps=None,
            models=["gemini-3.5-flash"],
            leagues=None,
            save_traces=None,
            reseed_required_tasks=None,
            max_budget_usd=10.0,
        )
        with self.assertRaises(NexUIError):
            _assert_resume_configuration_matches(args, manifest=manifest)

    def test_should_retry_immediately_only_for_retryable_runtime_errors(self) -> None:
        retryable = {
            "status": RESULT_STATUS_RUNTIME_ERROR,
            "retryable_runtime_error": True,
            "measured_cost_usd": 0.5,
        }
        model_failure = {
            "status": RESULT_STATUS_COMPLETED,
            "retryable_runtime_error": False,
            "measured_cost_usd": 0.5,
        }
        self.assertTrue(
            _should_retry_immediately(
                retryable,
                immediate_retry_count=0,
                cumulative_cost_usd=1.0,
                max_budget_usd=10.0,
            )
        )
        self.assertFalse(
            _should_retry_immediately(
                retryable,
                immediate_retry_count=1,
                cumulative_cost_usd=1.0,
                max_budget_usd=10.0,
            )
        )
        self.assertFalse(
            _should_retry_immediately(
                model_failure,
                immediate_retry_count=0,
                cumulative_cost_usd=1.0,
                max_budget_usd=10.0,
            )
        )

    def test_summarize_trace_usage_includes_runtime_error_metadata(self) -> None:
        trace = {
            "steps": [
                {
                    "agent_metadata": {
                        "usage": {
                            "prompt_token_count": 11,
                            "candidates_token_count": 5,
                            "thoughts_token_count": 2,
                        }
                    }
                }
            ],
            "result": {
                "runtime_error": {
                    "agent_metadata": {
                        "usage": {
                            "prompt_token_count": 7,
                            "candidates_token_count": 3,
                            "thoughts_token_count": 1,
                        }
                    }
                }
            },
        }
        usage = _summarize_trace_usage(trace)
        self.assertEqual(usage["prompt_token_count"], 18)
        self.assertEqual(usage["candidate_output_token_count"], 8)
        self.assertEqual(usage["thought_token_count"], 3)
        self.assertEqual(usage["billed_output_token_count"], 11)

    def test_task_budget_observer_stops_nonterminal_step_at_limit(self) -> None:
        observer = TaskBudgetObserver(
            model="gemini-2.5-flash-lite",
            pricing_by_model={"gemini-2.5-flash-lite": {"input": 1.0, "output": 1.0}},
            starting_cumulative_cost_usd=8.8,
            session_stop_limit_usd=9.0,
        )
        stop_signal = observer.on_step(
            {},
            {
                "submission": {"action": {"type": "click"}},
                "agent_metadata": {
                    "usage": {
                        "prompt_token_count": 100_000,
                        "candidates_token_count": 100_000,
                        "thoughts_token_count": 0,
                    }
                },
            },
        )
        self.assertEqual(stop_signal, {"status": "stopped", "reason": "budget_limit_reached"})

    def test_append_jsonl_atomic_preserves_all_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "results.jsonl"
            append_jsonl_atomic(path, {"a": 1})
            append_jsonl_atomic(path, {"b": 2})
            rows = [json.loads(line) for line in read_text(path).splitlines() if line.strip()]
            self.assertEqual(rows, [{"a": 1}, {"b": 2}])

    def test_oracle_prompt_cost_counts_prompt_contents_not_generate_request(self) -> None:
        task_dir = (
            Path(__file__).resolve().parents[1]
            / "examples/tasks/internet-dynamic-controls-enable-type-001"
        )
        captured_calls: list[dict[str, object]] = []

        def fake_count_tokens(model: str, **kwargs: object) -> int:
            captured_calls.append({"model": model, **kwargs})
            if kwargs.get("contents") is None:
                raise AssertionError("Expected contents payload for token counting.")
            if kwargs.get("generate_content_request") is not None:
                raise AssertionError("Estimator should not send generate_content_request.")
            return 1

        with patch("nexui.flash_baseline_runner._count_tokens", side_effect=fake_count_tokens):
            estimate = _oracle_prompt_cost(
                task_dir,
                split="validation",
                model="gemini-2.5-flash-lite",
                league="platinum",
                model_options={
                    "model": "gemini-2.5-flash-lite",
                    "prompt_profile": "candidates_only",
                    "thinking_budget": 0,
                    "temperature": 0.0,
                    "max_output_tokens": 512,
                    "seed": 0,
                },
                api_key="test-key",
                pricing_by_model={"gemini-2.5-flash-lite": {"input": 0.1, "output": 0.4}},
            )

        self.assertGreater(len(captured_calls), 0)
        self.assertEqual(estimate.prompt_token_count, estimate.oracle_step_count)

    def test_gemini_payload_uses_response_json_schema(self) -> None:
        task_dir = (
            Path(__file__).resolve().parents[1]
            / "examples/tasks/internet-dynamic-controls-enable-type-001"
        )
        task = load_task(task_dir)
        agent = GeminiAgent(
            task,
            GeminiAgentConfig(
                model="gemini-2.5-flash-lite",
                prompt_profile="candidates_only",
                prompt_league="platinum",
            ),
        )
        payload = agent._build_payload("test prompt")
        generation_config = payload["generationConfig"]
        self.assertIn("responseJsonSchema", generation_config)
        self.assertNotIn("responseSchema", generation_config)

    def test_json_load_tolerant_recovers_truncated_finish_submission(self) -> None:
        raw = (
            '{"action": {"type": "finish", "summary": "The task is complete."}, '
            '"explanation": "The current page already satisfies the goal.", '
            '"justification": {"basis": [{"kind": "url_contains", "value": "/admin/"}], '
            '"intent": "Stop on the existing form."'
        )
        parsed = _json_load_tolerant(raw)
        self.assertEqual(parsed["action"]["type"], "finish")
        self.assertEqual(parsed["action"]["summary"], "The task is complete.")
        self.assertEqual(parsed["explanation"], "The current page already satisfies the goal.")

    def test_json_load_tolerant_recovers_truncated_type_submission(self) -> None:
        raw = (
            '{\n  "action": {\n    "type": "type",\n    "target": "e49",\n'
            '    "text": "nexui-admin+alt@example.test"\n  },\n'
            '  "explanation": "Type the alternative email address into the Other Email field.",\n'
            '  "justification": {\n    "basis": [\n      {\n        "kind": "candidate_exists",\n'
            '        "value": "e49"\n      }\n    ],\n    "intent": "Fill the Other Email field with the required email address.",'
        )
        parsed = _json_load_tolerant(raw)
        self.assertEqual(parsed["action"]["type"], "type")
        self.assertEqual(parsed["action"]["target"], "e49")
        self.assertEqual(parsed["action"]["text"], "nexui-admin+alt@example.test")
        self.assertEqual(
            parsed["explanation"],
            "Type the alternative email address into the Other Email field.",
        )


if __name__ == "__main__":
    unittest.main()
