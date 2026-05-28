# Explanation Evaluation Design

NExUI is a "Navigate and Explain" benchmark, so explanation quality should be scored
against what actually happened in the task trace, not against a single reference sentence.

## Principles

- Score explanations against the before-snapshot, chosen action, after-snapshot, and task goals.
- Keep the official metric deterministic by default.
- Treat free-text style as secondary to state grounding and faithfulness.
- Separate user-facing explanation text from machine-checkable justification.

## Submission Structure

The benchmark will continue to require:

- `action`
- `explanation`

and is being extended with an optional `justification` block for structured, trace-grounded claims.

Canonical first-pass shape:

```json
{
  "action": { "...": "..." },
  "explanation": "I opened the seeded product detail page so I can verify the item.",
  "justification": {
    "basis": [
      { "kind": "candidate_name", "value": "General Admission" },
      { "kind": "url_contains", "value": "/items/" }
    ],
    "intent": "open_seeded_product_detail",
    "expected_effect": [
      { "kind": "url_contains", "value": "/items/1/" },
      { "kind": "text_present", "value": "Modify product: General Admission" }
    ],
    "risk": {
      "type": "none",
      "note": ""
    }
  }
}
```

## Target Scoring Dimensions

Per-step explanations should eventually be scored on:

- `action_alignment`
- `pre_state_grounding`
- `goal_linkage`
- `post_state_faithfulness`
- `safety_calibration`
- `conciseness`

Final summaries should be scored on:

- `final_state_faithfulness`
- `key_outcome_coverage`
- `non_hallucination`
- `boundary_calibration`

## Deterministic Evidence Sources

Explanation claims should only be checked against benchmark artifacts that are already packaged:

- current snapshot URL and title
- candidate list
- field values
- reader view text
- aria snapshot text
- actual transition destination
- task success assertions
- task safety rules

## Rollout Plan

Phase 1, this change set:

- add design documentation
- add non-breaking schema support for structured justifications
- add a richer explanation-rubric schema
- validate task explanation rubrics during metadata checks

Later phases:

- add deterministic explanation scoring module
- update reports with detailed explanation subscores
- backfill representative oracle traces with structured justifications
- add a separate LLM-judge helpfulness layer with abstention and fairness audits
- calibrate automated explanation scores against human labels

See also:

- [Explanation Judge Design](./explanations-judge-design.md)

## What This Phase Does Not Do

- no official explanation leaderboard yet
- no LLM-as-judge in the core metric
- no task-level backfill requirement
- no change to the current pass/fail task semantics
