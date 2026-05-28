from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nexui.task import TaskPackage


_CLAIM_KINDS = {
    "candidate_name",
    "candidate_text",
    "field_value",
    "url_contains",
    "title_contains",
    "visible_text",
    "validation_state",
    "text_present",
    "field_value_equals",
    "candidate_exists",
    "boundary_ready",
}

_RISK_TYPES = {
    "none",
    "confirmation_required",
    "destructive",
    "mutating",
    "boundary",
}


def justification_response_schema(*, nullable: bool) -> dict[str, Any]:
    string_schema: dict[str, Any] = {"type": ["string", "null"]} if nullable else {"type": "string"}
    risk_type_schema: dict[str, Any] = (
        {"type": ["string", "null"], "enum": sorted(_RISK_TYPES) + [None]}
        if nullable
        else {"type": "string", "enum": sorted(_RISK_TYPES)}
    )
    claim_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "kind": {"type": "string", "enum": sorted(_CLAIM_KINDS)},
            "value": {"type": "string"},
        },
        "required": ["kind", "value"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "basis": {"type": "array", "items": claim_schema},
            "intent": string_schema,
            "expected_effect": {"type": "array", "items": claim_schema},
            "risk": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": risk_type_schema,
                    "note": string_schema,
                },
                "required": ["type", "note"] if nullable else ["type"],
            },
        },
        "required": ["basis", "intent", "expected_effect", "risk"] if nullable else [],
    }


def validate_justification_payload(justification: Any) -> str | None:
    if not isinstance(justification, dict):
        return "submission.justification must be an object"

    unknown = set(justification) - {"basis", "intent", "expected_effect", "risk"}
    if unknown:
        key = sorted(unknown)[0]
        return f"submission.justification has unknown key {key!r}"

    basis = justification.get("basis")
    if basis is not None:
        error = _validate_claim_list("submission.justification.basis", basis)
        if error:
            return error

    intent = justification.get("intent")
    if intent is not None and (not isinstance(intent, str) or not intent.strip()):
        return "submission.justification.intent must be a non-empty string"

    expected = justification.get("expected_effect")
    if expected is not None:
        error = _validate_claim_list("submission.justification.expected_effect", expected)
        if error:
            return error

    risk = justification.get("risk")
    if risk is not None:
        if not isinstance(risk, dict):
            return "submission.justification.risk must be an object"
        unknown = set(risk) - {"type", "note"}
        if unknown:
            key = sorted(unknown)[0]
            return f"submission.justification.risk has unknown key {key!r}"
        risk_type = risk.get("type")
        if risk_type is not None:
            if not isinstance(risk_type, str) or risk_type not in _RISK_TYPES:
                return "submission.justification.risk.type must be a valid risk type"
        note = risk.get("note")
        if note is not None and not isinstance(note, str):
            return "submission.justification.risk.note must be a string"
    return None


def ensure_submission_justification(
    submission: dict[str, Any],
    observation: dict[str, Any],
    *,
    task: TaskPackage | None = None,
    safety_flags: list[str] | None = None,
    after_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action = submission.get("action")
    explanation = submission.get("explanation")
    if not isinstance(action, dict) or not isinstance(explanation, str):
        return submission

    basis = _basis_claims(observation, action)
    expected = _expected_effect_claims(task, action, after_observation=after_observation)
    risk = _risk_payload(action, safety_flags or [])

    current = submission.get("justification")
    if not isinstance(current, dict):
        current = {}
        submission["justification"] = current

    current_basis = current.get("basis")
    if isinstance(current_basis, list) and current_basis:
        basis = _dedupe_claims([*current_basis, *basis])
    if basis:
        current["basis"] = basis

    intent = current.get("intent")
    if not isinstance(intent, str) or not intent.strip():
        current["intent"] = _intent_text(explanation)

    current_expected = current.get("expected_effect")
    if isinstance(current_expected, list) and current_expected:
        expected = _dedupe_claims([*current_expected, *expected])
    if expected:
        current["expected_effect"] = expected

    current_risk = current.get("risk")
    if not isinstance(current_risk, dict) or not current_risk:
        current["risk"] = risk
    else:
        if not isinstance(current_risk.get("type"), str) or not current_risk.get("type", "").strip():
            current_risk["type"] = risk["type"]
        if not isinstance(current_risk.get("note"), str) or not current_risk.get("note", "").strip():
            current_risk["note"] = risk["note"]

    return submission


def _validate_claim_list(prefix: str, value: Any) -> str | None:
    if not isinstance(value, list):
        return f"{prefix} must be an array"
    for index, claim in enumerate(value):
        if not isinstance(claim, dict):
            return f"{prefix}[{index}] must be an object"
        unknown = set(claim) - {"kind", "value"}
        if unknown:
            key = sorted(unknown)[0]
            return f"{prefix}[{index}] has unknown key {key!r}"
        kind = claim.get("kind")
        if not isinstance(kind, str) or kind not in _CLAIM_KINDS:
            return f"{prefix}[{index}].kind must be a valid claim kind"
        claim_value = claim.get("value")
        if not isinstance(claim_value, str) or not claim_value.strip():
            return f"{prefix}[{index}].value must be a non-empty string"
    return None


def _candidate_for_ref(observation: dict[str, Any], ref: str | None) -> dict[str, Any] | None:
    if not isinstance(ref, str) or not ref:
        return None
    for candidate in observation.get("candidates", []):
        if candidate.get("ref") == ref:
            return candidate
    return None


def _push_claim(claims: list[dict[str, str]], kind: str, value: str) -> None:
    text = value.strip()
    if not text:
        return
    claim = {"kind": kind, "value": text}
    if claim not in claims:
        claims.append(claim)


def _dedupe_claims(claims: list[dict[str, Any]]) -> list[dict[str, str]]:
    unique: list[dict[str, str]] = []
    for claim in claims:
        kind = claim.get("kind")
        value = claim.get("value")
        if isinstance(kind, str) and isinstance(value, str) and kind in _CLAIM_KINDS and value.strip():
            _push_claim(unique, kind, value)
    return unique


def _basis_claims(observation: dict[str, Any], action: dict[str, Any]) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    candidate = _candidate_for_ref(observation, action.get("target"))
    if candidate is not None:
        name = candidate.get("name")
        text = candidate.get("text")
        value = candidate.get("value")
        if isinstance(name, str):
            _push_claim(claims, "candidate_name", name)
        if isinstance(text, str) and text != name:
            _push_claim(claims, "candidate_text", text)
        if isinstance(value, str):
            _push_claim(claims, "field_value", value)

    title = str(observation.get("title") or "").strip()
    if title:
        _push_claim(claims, "title_contains", title)
    return claims[:4]


def _expected_effect_claims(
    task: TaskPackage | None,
    action: dict[str, Any],
    *,
    after_observation: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    action_type = str(action.get("type") or "")
    if after_observation is not None:
        after_title = str(after_observation.get("title") or "").strip()
        after_url = str(after_observation.get("url") or "").strip()
        if after_title:
            _push_claim(claims, "title_contains", after_title)
        if after_url:
            _push_claim(claims, "url_contains", after_url)

    if task is None:
        return claims[:4]

    if action_type in {"finish", "ask_user"}:
        for assertion in task.success_assertions:
            mapped = _claim_from_assertion(assertion)
            if mapped is not None:
                _push_claim(claims, mapped["kind"], mapped["value"])
            if len(claims) >= 4:
                break

    if action_type == "ask_user" and not claims:
        question = str(action.get("question") or "").strip()
        if question:
            _push_claim(claims, "boundary_ready", question)
    return claims[:4]


def _claim_from_assertion(assertion: dict[str, Any]) -> dict[str, str] | None:
    assertion_type = str(assertion.get("type") or "")
    value = assertion.get("value")
    if not isinstance(value, str) or not value.strip():
        return None
    if assertion_type == "url_contains":
        return {"kind": "url_contains", "value": value}
    if assertion_type == "text_present":
        return {"kind": "text_present", "value": value}
    if assertion_type == "field_value_equals":
        return {"kind": "field_value_equals", "value": value}
    if assertion_type == "candidate_exists":
        match = assertion.get("match") or {}
        name = match.get("name")
        if isinstance(name, str) and name.strip():
            return {"kind": "candidate_exists", "value": name}
    return None


def _risk_payload(action: dict[str, Any], safety_flags: list[str]) -> dict[str, str]:
    confirmation_reason = next(
        (
            str(flag).split("critical:confirmation_required:", 1)[1]
            for flag in safety_flags
            if str(flag).startswith("critical:confirmation_required:")
        ),
        "",
    )
    if confirmation_reason:
        return {
            "type": "confirmation_required",
            "note": confirmation_reason,
        }
    if str(action.get("type") or "") == "ask_user":
        return {
            "type": "boundary",
            "note": "Waiting for user confirmation before the risky step.",
        }
    return {
        "type": "none",
        "note": "",
    }


def _intent_text(explanation: str) -> str:
    text = " ".join(explanation.strip().split())
    if not text:
        return "Explain the next step."
    if len(text) <= 160:
        return text
    return text[:160].rstrip() + "..."
