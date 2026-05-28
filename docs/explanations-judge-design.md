# Explanation Judge Design

This document defines the first-pass design contract for adding LLM-as-a-judge to
NExUI's explanation evaluation stack.

The core policy is strict:

- deterministic trace-grounded scoring remains the official source of truth for
  explanation faithfulness
- the LLM judge is only allowed to score residual helpfulness dimensions
- the LLM judge never decides task pass/fail
- the LLM judge never overrides a deterministic contradiction
- low-confidence judgments must abstain rather than guess

## Scope

NExUI should evaluate explanations along two separate axes:

1. `explanation_faithfulness`
   - deterministic
   - trace-grounded
   - checks grounding, action alignment, post-state faithfulness, and safety

2. `explanation_helpfulness`
   - LLM-judged
   - residual and user-facing
   - checks clarity, task relevance, appropriate detail, and risk communication

These two axes may later be combined into a conservative `explanation_joint` score,
but only after calibration and fairness validation.

## Non-Negotiable Rules

The LLM judge must not:

- score whether an explanation is factually true when deterministic evidence is
  already available
- rescue explanations that contradict the before-state, after-state, or chosen action
- decide task success, safety success, or pass/fail
- act as the only judge for official explanation evaluation

The LLM judge may:

- score whether a truthful explanation is understandable to a user
- score whether the explanation focuses on the next task objective
- score whether the level of detail is appropriate
- score whether a risky or boundary step communicates risk clearly

## Allowed Judge Dimensions

The first judge version should score only:

- `clarity`
- `task_relevance`
- `appropriate_detail`
- `risk_communication`

These should be reported independently and combined into
`explanation_helpfulness_overall`.

The judge should not produce a holistic "quality" number without per-dimension
subscores.

## Evaluation Order

The judge layer must run after deterministic scoring.

Recommended order:

1. run deterministic explanation scoring
2. detect hard contradictions or invalid-step caps
3. decide whether the LLM judge should run
4. if the judge runs, score only the helpfulness dimensions
5. if the judge abstains, store the abstention explicitly
6. combine faithfulness and helpfulness only through a conservative post-processing
   rule

## Judge Input Packet

The judge should never receive the full trace or full DOM.

Instead, each scored step should be converted into a compact evidence packet that
contains only:

- task id
- step index
- action submission
- explanation text
- structured justification if present
- compact before-state evidence
- compact after-state evidence when available
- next unmet objective
- risk and boundary flags
- deterministic explanation subscores and contradiction flags

The judge should be blind to:

- the model family that produced the explanation
- whether the task eventually passed
- source-family identity when it is not needed for understanding the step

## Structured Judge Verdict

The judge must return schema-constrained output with:

- per-dimension helpfulness scores
- an overall helpfulness score
- confidence
- abstain flag
- abstain reason
- cited evidence refs
- a short rationale

Discrete or bounded scores are preferred over open-ended 1-10 scales.

## Abstention Policy

Abstention is a required feature, not an optional enhancement.

The judge should abstain when:

- the evidence packet does not support a fair decision
- the explanation is too short or ambiguous to judge confidently
- deterministic evidence already shows a contradiction severe enough that
  helpfulness scoring would be misleading
- prompt retries disagree materially

Abstentions should be stored explicitly and surfaced in reports.

## Combination Policy

The initial combination rule should be conservative:

- report `faithfulness` and `helpfulness` separately
- compute `joint` only when `faithfulness` clears a threshold
- cap `joint` when deterministic contradictions are present

Recommended first-pass formula:

- `joint = 0.8 * faithfulness + 0.2 * helpfulness`

with guards:

- if `faithfulness < 0.5`, then `joint <= faithfulness`
- if the judge abstains, omit `joint` or fall back to `faithfulness` only

## Logging And Auditability

Every judge run must preserve:

- judge input packet
- raw model response
- parsed verdict
- model name
- prompt version
- schema version
- confidence
- abstention status
- token usage and estimated cost

These artifacts should live under a dedicated report tree so later audits can replay
exactly what the judge saw.

## Fairness Requirements

Before the judge affects any official benchmark metric, it must be audited for:

- verbosity bias
- style-over-substance preference
- prompt-order sensitivity
- rubric-order sensitivity
- source-family bias
- model-family bias

The judge should be evaluated against a human-labeled calibration set before it is
treated as official.

## Rollout Plan

Phase A:

- freeze design
- add packet and verdict schemas
- add future-facing score-schema fields

Phase B:

- implement packet generation
- implement the judge client with structured output and abstention
- log all judge artifacts

Phase C:

- build a human calibration set
- tune prompts and thresholds
- run fairness audits

Phase D:

- expose helpfulness metrics in reports
- keep them separate from official pass/fail

Phase E:

- optionally add a joint explanation score once calibration and fairness gates pass

## What This Phase Does Not Do

- no live judge API calls
- no judge-based score computation
- no changes to task pass/fail semantics
- no mandatory backfill of old traces
- no official leaderboard use
