from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nexui.io import NexUIError, RuntimeAgentError, read_text, read_yaml_like
from nexui.justification import ensure_submission_justification, justification_response_schema
from nexui.task import TaskPackage, load_source_registry_index


PROMPT_LEAGUES = frozenset({"bronze", "silver", "gold", "platinum"})


def _clip_text(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}…"


def _skip_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _extract_balanced_json_object(text: str, start_index: int) -> str | None:
    if start_index >= len(text) or text[start_index] != "{":
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start_index, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return text[start_index : index + 1]
    return None


def _extract_json_string_literal(text: str, start_index: int) -> str | None:
    if start_index >= len(text) or text[start_index] != '"':
        return None
    escaped = False
    for index in range(start_index + 1, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            return text[start_index : index + 1]
    return None


def _parse_partial_submission(text: str) -> dict[str, Any] | None:
    action_match = re.search(r'"action"\s*:\s*', text)
    explanation_match = re.search(r'"explanation"\s*:\s*', text)
    if action_match is None or explanation_match is None:
        return None

    action_start = _skip_whitespace(text, action_match.end())
    action_literal = _extract_balanced_json_object(text, action_start)
    if action_literal is None:
        return None
    explanation_start = _skip_whitespace(text, explanation_match.end())
    explanation_literal = _extract_json_string_literal(text, explanation_start)
    if explanation_literal is None:
        return None

    try:
        action = json.loads(action_literal)
        explanation = json.loads(explanation_literal)
    except json.JSONDecodeError:
        return None
    if not isinstance(action, dict) or not isinstance(explanation, str):
        return None
    return {"action": action, "explanation": explanation}


def _json_load_tolerant(raw: str) -> dict[str, Any]:
    stripped = raw.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        parsed = _parse_partial_submission(stripped)
        if parsed is not None:
            return parsed
        raise RuntimeAgentError(
            f"Gemini returned non-JSON output: {raw[:400]!r}",
            provider="gemini",
            category="malformed_response",
            retryable=True,
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeAgentError(
            f"Gemini returned a non-object submission: {type(parsed).__name__}",
            provider="gemini",
            category="malformed_response",
            retryable=True,
        )
    return parsed


def _load_api_key() -> str:
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    raise NexUIError(
        "Gemini baseline requires GOOGLE_API_KEY or GEMINI_API_KEY in the environment."
    )


def _stable_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True)


@dataclass(frozen=True)
class GeminiAgentConfig:
    model: str = "gemini-2.5-flash-lite"
    temperature: float = 0.0
    max_output_tokens: int = 512
    thinking_budget: int | None = 0
    prompt_profile: str = "candidates_only"
    prompt_league: str = "bronze"
    max_candidates: int = 80
    history_window: int = 4
    seed: int | None = 0
    request_timeout_s: float = 60.0
    retry_count: int = 2
    reader_view_char_limit: int = 1800
    aria_char_limit: int = 2500

    @classmethod
    def from_options(cls, options: dict[str, Any]) -> "GeminiAgentConfig":
        thinking_budget = options.get("thinking_budget", cls.thinking_budget)
        seed = options.get("seed", cls.seed)
        return cls(
            model=str(options.get("model") or cls.model),
            temperature=float(options.get("temperature", cls.temperature)),
            max_output_tokens=int(options.get("max_output_tokens", cls.max_output_tokens)),
            thinking_budget=None if thinking_budget is None else int(thinking_budget),
            prompt_profile=str(options.get("prompt_profile") or cls.prompt_profile),
            prompt_league=str(options.get("prompt_league") or cls.prompt_league),
            max_candidates=int(options.get("max_candidates", cls.max_candidates)),
            history_window=int(options.get("history_window", cls.history_window)),
            seed=None if seed is None else int(seed),
            request_timeout_s=float(options.get("request_timeout_s", cls.request_timeout_s)),
            retry_count=int(options.get("retry_count", cls.retry_count)),
            reader_view_char_limit=int(
                options.get("reader_view_char_limit", cls.reader_view_char_limit)
            ),
            aria_char_limit=int(options.get("aria_char_limit", cls.aria_char_limit)),
        )


class GeminiAgent:
    def __init__(self, task: TaskPackage, config: GeminiAgentConfig) -> None:
        if config.prompt_league not in PROMPT_LEAGUES:
            raise NexUIError(f"Unsupported Gemini prompt league: {config.prompt_league!r}")
        self.task = task
        self.config = config
        self.history: list[dict[str, Any]] = []
        self.last_step_metadata: dict[str, Any] | None = None
        self._source_context: dict[str, Any] | None = None

    @property
    def agent_id(self) -> str:
        return "gemini"

    @property
    def agent_type(self) -> str:
        return "external_llm"

    @property
    def version(self) -> str:
        return "gemini-api-generatecontent-v1beta"

    def describe(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "version": self.version,
            "config": {
                "model": self.config.model,
                "temperature": self.config.temperature,
                "max_output_tokens": self.config.max_output_tokens,
                "thinking_budget": self.config.thinking_budget,
                "prompt_profile": self.config.prompt_profile,
                "prompt_league": self.config.prompt_league,
                "max_candidates": self.config.max_candidates,
                "history_window": self.config.history_window,
                "seed": self.config.seed,
            },
        }

    def _candidate_priority(self, candidate: dict[str, Any]) -> tuple[int, int, int, str]:
        interactive_roles = {
            "button",
            "link",
            "textbox",
            "combobox",
            "option",
            "checkbox",
            "radio",
            "tab",
            "menuitem",
            "switch",
            "spinbutton",
            "slider",
        }
        role = str(candidate.get("role") or "")
        name = str(candidate.get("name") or "")
        return (
            0 if candidate.get("keyboard_reachable") else 1,
            0 if role in interactive_roles else 1,
            0 if name else 1,
            str(candidate.get("ref") or ""),
        )

    def _format_candidates(self, observation: dict[str, Any]) -> str:
        sorted_candidates = sorted(
            observation.get("candidates", []),
            key=self._candidate_priority,
        )
        lines: list[str] = []
        for candidate in sorted_candidates[: self.config.max_candidates]:
            parts = [
                f"ref={candidate.get('ref', '')}",
                f"role={candidate.get('role', '') or '-'}",
            ]
            if candidate.get("name"):
                parts.append(f"name={json.dumps(_clip_text(str(candidate['name']), 160))}")
            if candidate.get("value") not in {None, ""}:
                parts.append(f"value={json.dumps(_clip_text(str(candidate['value']), 120))}")
            if candidate.get("description"):
                parts.append(
                    f"description={json.dumps(_clip_text(str(candidate['description']), 180))}"
                )
            if candidate.get("text"):
                parts.append(f"text={json.dumps(_clip_text(str(candidate['text']), 180))}")
            states = candidate.get("states") or []
            if states:
                parts.append(f"states={json.dumps(states)}")
            if candidate.get("keyboard_reachable") is not None:
                parts.append(f"keyboard_reachable={bool(candidate['keyboard_reachable'])}")
            lines.append("- " + " | ".join(parts))
        return "\n".join(lines)

    def _artifact_path(self, observation: dict[str, Any], key: str) -> Path:
        return self.task.root / observation["artifacts"][key]

    def _format_history(self) -> str:
        if not self.history:
            return "None."
        lines = []
        for item in self.history[-self.config.history_window :]:
            lines.append(
                "- "
                + _stable_json(
                    {
                        "before_snapshot": item["before_snapshot"],
                        "after_snapshot": item["after_snapshot"],
                        "action": item["action"],
                    }
                )
            )
        return "\n".join(lines)

    def _league_rank(self) -> int:
        return {
            "bronze": 0,
            "silver": 1,
            "gold": 2,
            "platinum": 3,
        }[self.config.prompt_league]

    def _summarize_assertion(self, assertion: dict[str, Any]) -> str:
        assertion_type = str(assertion.get("type") or "")
        value = assertion.get("value")
        if assertion_type == "url_contains":
            return f"Final URL should contain {value!r}."
        if assertion_type == "text_present":
            return f"The final page should show text {value!r}."
        if assertion_type == "text_absent":
            return f"The final page should not show text {value!r}."
        if assertion_type == "field_value_equals":
            match = assertion.get("match") or {}
            field_name = match.get("name") or match.get("role") or "field"
            return f"The field {field_name!r} should equal {value!r}."
        if assertion_type == "trace_status_is":
            return f"The trace should end with status {value!r}."
        if assertion_type == "last_action_type_is":
            return f"The last action type should be {value!r}."
        if assertion_type == "candidate_exists":
            match = assertion.get("match") or {}
            field_name = match.get("name") or match.get("role") or match.get("ref") or "candidate"
            return f"A visible candidate matching {field_name!r} should exist."
        return _stable_json(assertion)

    def _format_success_hints(self) -> str:
        lines: list[str] = []
        for assertion in self.task.success_assertions:
            lines.append(f"- {self._summarize_assertion(assertion)}")
        for branch_index, branch in enumerate(self.task.success_any_of, start=1):
            branch_lines = [self._summarize_assertion(assertion) for assertion in branch]
            lines.append(f"- Any-of branch {branch_index}: " + " ".join(branch_lines))
        return "\n".join(lines) or "None."

    def _collect_exact_values(self) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()

        def add(candidate: Any) -> None:
            if not isinstance(candidate, str):
                return
            text = candidate.strip()
            if not text or len(text) > 160:
                return
            if text in seen:
                return
            seen.add(text)
            values.append(text)

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for nested in value.values():
                    walk(nested)
                return
            if isinstance(value, list):
                for nested in value:
                    walk(nested)
                return
            add(value)

        for assertion in self.task.success_assertions:
            walk(assertion.get("value"))
            walk((assertion.get("match") or {}).get("name"))
        for branch in self.task.success_any_of:
            for assertion in branch:
                walk(assertion.get("value"))
                walk((assertion.get("match") or {}).get("name"))
        for match in re.findall(r"`([^`]+)`", self.task.instruction):
            add(match)
        return values[:16]

    def _load_source_context(self) -> dict[str, Any]:
        if self._source_context is not None:
            return self._source_context

        registry = load_source_registry_index()
        entry = registry.get(self.task.source_surface)
        if not entry:
            self._source_context = {}
            return self._source_context

        manifest_path = self.task.root.parents[2] / str(entry["manifest_path"])
        if not manifest_path.exists():
            self._source_context = {}
            return self._source_context

        manifest = read_yaml_like(manifest_path)
        auth_notes = str((manifest.get("auth") or {}).get("notes") or "").strip()
        runtime_notes = str((manifest.get("runtime") or {}).get("notes") or "").strip()
        seed_doc_name = str((manifest.get("onboarding") or {}).get("seed_notes_doc") or "").strip()
        seed_lines: list[str] = []
        if seed_doc_name:
            seed_doc_path = manifest_path.parent / seed_doc_name
            if seed_doc_path.exists():
                for raw_line in read_text(seed_doc_path).splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    lowered = line.lower()
                    if any(
                        keyword in lowered
                        for keyword in (
                            "username",
                            "password",
                            "account",
                            "display name",
                            "employee",
                            "customer",
                            "supplier",
                            "item",
                            "project",
                            "leave type",
                            "organization",
                        )
                    ):
                        seed_lines.append(line)
                    if len(seed_lines) >= 10:
                        break
        self._source_context = {
            "site_name": str(manifest.get("site_name") or self.task.source_surface),
            "auth_notes": auth_notes,
            "runtime_notes": runtime_notes,
            "seed_lines": seed_lines,
        }
        return self._source_context

    def _format_source_hints(self) -> str:
        context = self._load_source_context()
        if not context:
            return "None."
        lines: list[str] = []
        if context.get("auth_notes"):
            lines.append(f"- Auth notes: {context['auth_notes']}")
        for seed_line in context.get("seed_lines") or []:
            lines.append(f"- {seed_line}")
        return "\n".join(lines) or "None."

    def _build_prompt(self, observation: dict[str, Any]) -> str:
        reader_view = ""
        aria_snapshot = ""
        if self.config.prompt_profile == "candidates_ax":
            reader_view = _clip_text(
                read_text(self._artifact_path(observation, "reader_view")),
                self.config.reader_view_char_limit,
            )
            aria_snapshot = _clip_text(
                read_text(self._artifact_path(observation, "aria_snapshot")),
                self.config.aria_char_limit,
            )
        elif self.config.prompt_profile != "candidates_only":
            raise NexUIError(
                f"Unsupported Gemini prompt profile: {self.config.prompt_profile!r}"
            )

        user_profile = self.task.user_profile
        prompt_sections = [
            "You are an action-selection agent for the NExUI benchmark.",
            "Return exactly one JSON object with keys action, explanation, and justification.",
            "Do not wrap the JSON in markdown.",
            "Base your decision on the current snapshot and recent action history, not only the original instruction.",
            "Only use candidate refs listed in CURRENT SNAPSHOT CANDIDATES.",
            "Use ask_user at explicit confirmation boundaries instead of taking the risky action.",
            "Use finish only if the task is already complete in the current state.",
            "If the requested UI changes have already been completed, do not repeat the same action. Use finish.",
            "Do not restart the task from the beginning after the goal has been achieved.",
            "",
            "TASK",
                f"task_id: {self.task.task_id}",
                f"title: {self.task.manifest['title']}",
                f"goal: {self.task.manifest['goal']}",
                f"difficulty_band: {self.task.manifest.get('difficulty_band', '')}",
                f"prompt_league: {self.config.prompt_league}",
                "",
                "USER INSTRUCTION",
                self.task.instruction.strip(),
                "",
                "USER PROFILE",
            _stable_json(user_profile),
            "",
            "ALLOWED ACTION TYPES",
            ", ".join(sorted(self.task.allowed_actions)),
            "",
            "SUBMISSION SHAPE",
            _stable_json(
                {
                    "action": {
                        "type": "click|type|press|select|scroll|focus|back|wait|ask_user|finish|click_xy",
                        "target": "candidate ref when needed",
                        "text": "for type",
                        "option": "for select",
                        "key": "for press",
                        "direction": "for scroll",
                        "question": "for ask_user",
                        "summary": "for finish",
                        "x": 0,
                        "y": 0,
                    },
                    "explanation": "brief reason for this single next step",
                    "justification": {
                        "basis": [{"kind": "candidate_name|visible_text|title_contains", "value": "visible evidence now"}],
                        "intent": "short purpose of this action",
                        "expected_effect": [{"kind": "text_present|url_contains|candidate_exists", "value": "expected next-state evidence"}],
                        "risk": {"type": "none|confirmation_required|boundary|mutating", "note": "optional short risk note"},
                    },
                }
            ),
            "",
            "JUSTIFICATION RULES",
            "- basis should cite concrete evidence visible in the current snapshot.",
            "- intent should be one short sentence about why this is the next action.",
            "- expected_effect should name the observable state you expect after the action when you can.",
            "- risk.type should be none unless the step is a confirmation boundary or otherwise risky.",
            "",
            "CURRENT SNAPSHOT",
            _stable_json(
                {
                    "snapshot_id": observation["snapshot_id"],
                    "url": observation["url"],
                    "title": observation["title"],
                    "modal_state": observation["modal_state"],
                    "focus_target": observation.get("focus_target"),
                    "viewport": observation["viewport"],
                }
            ),
            "",
            "RECENT ACTION HISTORY",
            self._format_history(),
            "",
            "CURRENT SNAPSHOT CANDIDATES",
            self._format_candidates(observation) or "None.",
        ]
        if self._league_rank() >= 1:
            prompt_sections.extend(["", "SUCCESS STATE CHECKLIST", self._format_success_hints()])
            prompt_sections.extend(
                [
                    "",
                    "SUCCESS DISCIPLINE",
                    "- Compare the CURRENT SNAPSHOT against the success checklist before acting.",
                    "- If the current state already satisfies the task, use finish immediately.",
                    "- If the task is a confirmation boundary and the final risky button is ready, use ask_user instead of clicking it.",
                    "- If a validation or error state is already visible, correct the failing field instead of restarting the task.",
                ]
            )
        if self._league_rank() >= 2:
            prompt_sections.extend(
                [
                    "",
                    "EXACT LITERALS TO USE",
                    "\n".join(f"- {value!r}" for value in self._collect_exact_values()) or "None.",
                    "",
                    "EXACT VALUE POLICY",
                    "- Do not invent placeholders or generic defaults such as 'John Doe', 'Admin', or guessed passwords.",
                    "- When a person name, amount, email, project slug, or route fragment is specified, use that exact literal.",
                    "- Prefer matching visible fields to the required exact value rather than typing a plausible substitute.",
                ]
            )
        if self._league_rank() >= 3:
            prompt_sections.extend(
                [
                    "",
                    "SOURCE AUTH AND SEEDED ENTITY HINTS",
                    self._format_source_hints(),
                    "",
                    "DECISION CHECKLIST",
                    "1. Read the exact target entity, credential, amount, or route from the instruction, success checklist, and source hints.",
                    "2. If the current page is a login or recovery form and exact credentials are available, type them exactly instead of guessing.",
                    "3. If a validation error is already showing, correct only the failing field using the exact target value.",
                    "4. If the success checklist already holds in the current snapshot, use finish.",
                    "5. Otherwise choose the single candidate that advances toward the next unmet success item.",
                ]
            )
        if reader_view:
            prompt_sections.extend(["", "READER VIEW (TRUNCATED)", reader_view])
        if aria_snapshot:
            prompt_sections.extend(["", "ARIA SNAPSHOT (TRUNCATED)", aria_snapshot])
        prompt_sections.extend(
            [
                "",
                "Decide the single best next action from the current snapshot only.",
            ]
        )
        return "\n".join(prompt_sections)

    def _response_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "type": {"type": "string", "enum": sorted(self.task.allowed_actions)},
                        "target": {"type": "string"},
                        "text": {"type": "string"},
                        "option": {"type": "string"},
                        "key": {"type": "string"},
                        "direction": {"type": "string"},
                        "question": {"type": "string"},
                        "summary": {"type": "string"},
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                    },
                    "required": ["type"],
                },
                "explanation": {"type": "string"},
                "justification": justification_response_schema(nullable=False),
            },
            "required": ["action", "explanation", "justification"],
        }

    def _repair_submission(self, submission: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
        action = submission.get("action")
        explanation = submission.get("explanation")
        if not isinstance(action, dict) or not isinstance(explanation, str):
            return submission

        explanation_text = explanation.strip()
        action_type = action.get("type")
        if explanation_text:
            if action_type == "finish":
                summary = action.get("summary")
                if not isinstance(summary, str) or not summary.strip():
                    action["summary"] = explanation_text
            elif action_type == "ask_user":
                question = action.get("question")
                if not isinstance(question, str) or not question.strip():
                    action["question"] = explanation_text
        return ensure_submission_justification(
            submission,
            observation,
            task=self.task,
        )

    def _build_payload(self, prompt: str) -> dict[str, Any]:
        generation_config: dict[str, Any] = {
            "temperature": self.config.temperature,
            "maxOutputTokens": self.config.max_output_tokens,
            "responseMimeType": "application/json",
            # The current Gemini REST API accepts full JSON Schema via
            # responseJsonSchema. responseSchema is a narrower OpenAPI subset.
            "responseJsonSchema": self._response_schema(),
        }
        if self.config.seed is not None:
            generation_config["seed"] = self.config.seed
        if self.config.thinking_budget is not None:
            generation_config["thinkingConfig"] = {
                "thinkingBudget": self.config.thinking_budget,
            }
        return {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt,
                        }
                    ]
                }
            ],
            "generationConfig": generation_config,
        }

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        api_key = _load_api_key()
        model = urllib.parse.quote(self.config.model, safe="")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        body = json.dumps(payload).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(self.config.retry_count + 1):
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
                with urllib.request.urlopen(
                    request,
                    timeout=self.config.request_timeout_s,
                ) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                last_error = RuntimeAgentError(
                    f"Gemini API request failed with HTTP {exc.code}: {error_body[:800]}",
                    provider="gemini",
                    category="http_error",
                    retryable=exc.code in {429, 500, 502, 503, 504},
                    details={"http_status": exc.code},
                )
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= self.config.retry_count:
                    raise last_error
            except urllib.error.URLError as exc:
                last_error = RuntimeAgentError(
                    f"Gemini API request failed: {exc.reason}",
                    provider="gemini",
                    category="transport_error",
                    retryable=True,
                )
                if attempt >= self.config.retry_count:
                    raise last_error
            time.sleep(1.0 * (2 ** attempt))
        assert last_error is not None
        raise last_error

    def _extract_text(self, response: dict[str, Any]) -> str:
        candidates = response.get("candidates") or []
        if not candidates:
            raise RuntimeAgentError(
                f"Gemini returned no candidates: {_stable_json(response)[:800]}",
                provider="gemini",
                category="malformed_response",
                retryable=True,
            )
        candidate = candidates[0]
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        texts = [part.get("text", "") for part in parts if isinstance(part, dict) and part.get("text")]
        text = "\n".join(texts).strip()
        if not text:
            raise RuntimeAgentError(
                f"Gemini returned no text content. finish_reason={candidate.get('finishReason')!r}",
                provider="gemini",
                category="malformed_response",
                retryable=True,
            )
        return text

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        self.last_step_metadata = None
        prompt = self._build_prompt(observation)
        payload = self._build_payload(prompt)
        started_at = time.perf_counter()
        response = self._request(payload)
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        usage = response.get("usageMetadata") or {}
        self.last_step_metadata = {
            "provider": "gemini",
            "model": self.config.model,
            "prompt_profile": self.config.prompt_profile,
            "prompt_league": self.config.prompt_league,
            "latency_ms": latency_ms,
            "usage": {
                "prompt_token_count": usage.get("promptTokenCount"),
                "candidates_token_count": usage.get("candidatesTokenCount"),
                "thoughts_token_count": usage.get("thoughtsTokenCount"),
                "total_token_count": usage.get("totalTokenCount"),
            },
        }
        submission = self._repair_submission(
            _json_load_tolerant(self._extract_text(response)),
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

    def record_outcome(self, after_snapshot: str) -> None:
        if self.history:
            self.history[-1]["after_snapshot"] = after_snapshot
