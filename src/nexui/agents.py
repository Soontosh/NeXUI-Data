from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nexui.io import NexUIError
from nexui.justification import ensure_submission_justification
from nexui.task import TaskPackage


@dataclass
class OracleAgent:
    task: TaskPackage
    steps: list[dict[str, Any]]
    cursor: int = 0
    last_step_metadata: dict[str, Any] | None = None

    @property
    def agent_id(self) -> str:
        return "oracle"

    @property
    def agent_type(self) -> str:
        return "builtin"

    @property
    def version(self) -> str:
        return "0.0.0"

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        if self.cursor >= len(self.steps):
            return ensure_submission_justification({
                "action": {
                    "type": "finish",
                    "summary": "Oracle trajectory exhausted without an explicit finish action."
                },
                "explanation": "There are no more oracle steps, so I am ending the task."
            }, observation, task=self.task)
        step = self.steps[self.cursor]
        self.cursor += 1
        after_observation = None
        transition = self.task.find_transition(observation["snapshot_id"], step.get("action", {}))
        if transition is not None:
            after_observation = self.task.build_observation(str(transition["to"]))
        return ensure_submission_justification(
            step,
            observation,
            task=self.task,
            after_observation=after_observation,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "version": self.version,
        }


@dataclass
class NoopAgent:
    task: TaskPackage
    last_step_metadata: dict[str, Any] | None = None

    @property
    def agent_id(self) -> str:
        return "noop"

    @property
    def agent_type(self) -> str:
        return "builtin"

    @property
    def version(self) -> str:
        return "0.0.0"

    def act(self, observation: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = observation["snapshot_id"]
        return ensure_submission_justification({
            "action": {
                "type": "finish",
                "summary": f"Stopped immediately from {snapshot_id} without taking any UI action."
            },
            "explanation": "I am ending the task without interacting with the page."
        }, observation, task=self.task)

    def describe(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "version": self.version,
        }

def make_agent(
    name: str,
    task: TaskPackage,
    options: dict[str, Any] | None = None,
) -> OracleAgent | NoopAgent | Any:
    normalized = name.strip().lower()
    if normalized == "oracle":
        return OracleAgent(task, task.oracle_steps)
    if normalized == "noop":
        return NoopAgent(task)
    if normalized == "gemini":
        from nexui.gemini_agent import GeminiAgent, GeminiAgentConfig

        return GeminiAgent(task, GeminiAgentConfig.from_options(options or {}))
    if normalized == "openai":
        from nexui.openai_agent import OpenAIAgent, OpenAIAgentConfig

        return OpenAIAgent(task, OpenAIAgentConfig.from_options(options or {}))
    raise NexUIError(f"Unknown built-in agent: {name}")
