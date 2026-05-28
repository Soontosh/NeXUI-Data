from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from nexui.io import NexUIError, RuntimeAgentError
from nexui.justification import justification_response_schema
from nexui.task import TaskPackage

from .gemini_agent import GeminiAgent, PROMPT_LEAGUES, _json_load_tolerant


def _load_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    raise NexUIError("OpenAI baseline requires OPENAI_API_KEY in the environment.")


@dataclass(frozen=True)
class OpenAIAgentConfig:
    model: str = "o3"
    max_output_tokens: int = 1024
    reasoning_effort: str = "low"
    text_verbosity: str = "low"
    prompt_profile: str = "candidates_ax"
    prompt_league: str = "platinum"
    max_candidates: int = 80
    history_window: int = 4
    request_timeout_s: float = 90.0
    retry_count: int = 2
    reader_view_char_limit: int = 1800
    aria_char_limit: int = 2500
    store: bool = False

    @classmethod
    def from_options(cls, options: dict[str, Any]) -> "OpenAIAgentConfig":
        return cls(
            model=str(options.get("model") or cls.model),
            max_output_tokens=int(options.get("max_output_tokens", cls.max_output_tokens)),
            reasoning_effort=str(options.get("reasoning_effort") or cls.reasoning_effort),
            text_verbosity=str(options.get("text_verbosity") or cls.text_verbosity),
            prompt_profile=str(options.get("prompt_profile") or cls.prompt_profile),
            prompt_league=str(options.get("prompt_league") or cls.prompt_league),
            max_candidates=int(options.get("max_candidates", cls.max_candidates)),
            history_window=int(options.get("history_window", cls.history_window)),
            request_timeout_s=float(options.get("request_timeout_s", cls.request_timeout_s)),
            retry_count=int(options.get("retry_count", cls.retry_count)),
            reader_view_char_limit=int(
                options.get("reader_view_char_limit", cls.reader_view_char_limit)
            ),
            aria_char_limit=int(options.get("aria_char_limit", cls.aria_char_limit)),
            store=bool(options.get("store", cls.store)),
        )


class OpenAIAgent(GeminiAgent):
    def __init__(self, task: TaskPackage, config: OpenAIAgentConfig) -> None:
        if config.prompt_league not in PROMPT_LEAGUES:
            raise NexUIError(f"Unsupported OpenAI prompt league: {config.prompt_league!r}")
        if config.reasoning_effort not in {"none", "minimal", "low", "medium", "high", "xhigh"}:
            raise NexUIError(
                f"Unsupported OpenAI reasoning effort: {config.reasoning_effort!r}"
            )
        if config.text_verbosity not in {"low", "medium", "high"}:
            raise NexUIError(f"Unsupported OpenAI text verbosity: {config.text_verbosity!r}")
        super().__init__(task, config)

    @property
    def agent_id(self) -> str:
        return "openai"

    @property
    def version(self) -> str:
        return "openai-responses-v1"

    def describe(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "version": self.version,
            "config": {
                "model": self.config.model,
                "max_output_tokens": self.config.max_output_tokens,
                "reasoning_effort": self.config.reasoning_effort,
                "text_verbosity": self.config.text_verbosity,
                "prompt_profile": self.config.prompt_profile,
                "prompt_league": self.config.prompt_league,
                "max_candidates": self.config.max_candidates,
                "history_window": self.config.history_window,
                "store": self.config.store,
            },
        }

    def _build_payload(self, prompt: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "store": self.config.store,
            "input": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "max_output_tokens": self.config.max_output_tokens,
            "reasoning": {
                "effort": self.config.reasoning_effort,
            },
            "text": {
                "verbosity": self.config.text_verbosity,
                "format": {
                    "type": "json_schema",
                    "name": "nexui_action_submission",
                    "strict": True,
                    "schema": self._response_schema(),
                },
            },
        }
        return payload

    def _response_schema(self) -> dict[str, Any]:
        nullable_string = {"type": ["string", "null"]}
        nullable_integer = {"type": ["integer", "null"]}
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "type": {"type": "string", "enum": sorted(self.task.allowed_actions)},
                        "target": nullable_string,
                        "text": nullable_string,
                        "option": nullable_string,
                        "key": nullable_string,
                        "direction": nullable_string,
                        "question": nullable_string,
                        "summary": nullable_string,
                        "x": nullable_integer,
                        "y": nullable_integer,
                    },
                    "required": [
                        "type",
                        "target",
                        "text",
                        "option",
                        "key",
                        "direction",
                        "question",
                        "summary",
                        "x",
                        "y",
                    ],
                },
                "explanation": {"type": "string"},
                "justification": justification_response_schema(nullable=True),
            },
            "required": ["action", "explanation", "justification"],
        }

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        api_key = _load_api_key()
        body = json.dumps(payload).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(self.config.retry_count + 1):
            try:
                request = urllib.request.Request(
                    "https://api.openai.com/v1/responses",
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(
                    request,
                    timeout=self.config.request_timeout_s,
                ) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                last_error = RuntimeAgentError(
                    f"OpenAI API request failed with HTTP {exc.code}: {error_body[:800]}",
                    provider="openai",
                    category="http_error",
                    retryable=exc.code in {408, 409, 429, 500, 502, 503, 504},
                    details={"http_status": exc.code},
                )
                if exc.code not in {408, 409, 429, 500, 502, 503, 504} or attempt >= self.config.retry_count:
                    raise last_error
            except urllib.error.URLError as exc:
                last_error = RuntimeAgentError(
                    f"OpenAI API request failed: {exc.reason}",
                    provider="openai",
                    category="transport_error",
                    retryable=True,
                )
                if attempt >= self.config.retry_count:
                    raise last_error
            time.sleep(1.0 * (2**attempt))
        assert last_error is not None
        raise last_error

    def _extract_text(self, response: dict[str, Any]) -> str:
        if response.get("status") == "incomplete":
            details = response.get("incomplete_details") or {}
            raise RuntimeAgentError(
                "OpenAI response was incomplete: "
                f"{details.get('reason') or response.get('status')}",
                provider="openai",
                category="malformed_response",
                retryable=True,
            )

        output_text = str(response.get("output_text") or "").strip()
        if output_text:
            return output_text

        for item in response.get("output") or []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue
                text = str(content.get("text") or "").strip()
                if text:
                    return text
                if content.get("type") == "refusal":
                    raise RuntimeAgentError(
                        f"OpenAI model refused the request: {content.get('refusal') or 'refusal'}",
                        provider="openai",
                        category="malformed_response",
                        retryable=False,
                    )
        raise RuntimeAgentError(
            f"OpenAI returned no text content: {json.dumps(response)[:800]}",
            provider="openai",
            category="malformed_response",
            retryable=True,
        )

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        self.last_step_metadata = None
        prompt = self._build_prompt(observation)
        payload = self._build_payload(prompt)
        started_at = time.perf_counter()
        response = self._request(payload)
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        usage = response.get("usage") or {}
        output_details = usage.get("output_tokens_details") or {}
        reasoning_tokens = int(output_details.get("reasoning_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        visible_tokens = max(0, output_tokens - reasoning_tokens)
        self.last_step_metadata = {
            "provider": "openai",
            "model": self.config.model,
            "prompt_profile": self.config.prompt_profile,
            "prompt_league": self.config.prompt_league,
            "latency_ms": latency_ms,
            "response_id": response.get("id"),
            "response_status": response.get("status"),
            "response_model": response.get("model"),
            "output_preview": response_text[:240],
            "usage": {
                "prompt_token_count": usage.get("input_tokens"),
                "candidates_token_count": visible_tokens,
                "thoughts_token_count": reasoning_tokens,
                "output_token_count": usage.get("output_tokens"),
                "total_token_count": usage.get("total_tokens"),
                "cached_prompt_token_count": (
                    (usage.get("input_tokens_details") or {}).get("cached_tokens")
                ),
            },
        }
        response_text = self._extract_text(response)
        submission = self._repair_submission(
            _json_load_tolerant(response_text),
            observation,
        )
        self.history.append(
            {
                "before_snapshot": observation["snapshot_id"],
                "after_snapshot": observation["snapshot_id"],
                "action": submission.get("action", {}),
            }
        )
        return submission
