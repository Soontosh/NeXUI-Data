# Gemini Baseline Quickstart

This is the first NExUI baseline integration for weaker Gemini API models.

Current scope:

- text-only action selection
- local per-step history
- strict JSON action output
- prompt profiles:
  - `candidates_only`
  - `candidates_ax`
- prompt leagues:
  - `bronze`
  - `silver`
  - `gold`
  - `platinum`

Not yet included:

- screenshot / multimodal input
- batch evaluation orchestration
- source-specific prompt adapters

## Credentials

Do not hardcode API keys into code or task files.

Use one of:

- `GOOGLE_API_KEY`
- `GEMINI_API_KEY`

The Gemini API client path in NExUI prefers `GOOGLE_API_KEY` if both are set.

Example:

```bash
export GEMINI_API_KEY='your-key-here'
```

## First recommended models

Start with:

- `gemini-2.5-flash-lite`
- `gemini-2.5-flash`

These are the intended initial weak/cheap baselines for NExUI.

## Prompt profiles

### `candidates_only`

Lowest-cost profile.

Inputs:

- task title and goal
- instruction text
- user profile JSON
- current snapshot metadata
- compact current-snapshot candidate list
- short local history

### `candidates_ax`

Slightly stronger text-only profile.

Includes everything in `candidates_only`, plus:

- truncated `reader_view.txt`
- truncated `aria_snapshot.yml`

Use this when `candidates_only` is clearly underpowered on accessibility-heavy tasks.

## Prompt leagues

The baseline now supports four prompt leagues that progressively expose more benchmark metadata to the model.

### `bronze`

Closest to the original baseline.

Includes:

- task title and goal
- instruction text
- user profile
- current snapshot metadata
- candidate list
- recent action history

### `silver`

Adds explicit success-state guidance.

Includes everything in `bronze`, plus:

- summarized success assertions
- stronger finish / ask-user / validation-recovery rules

### `gold`

Adds exact-literal discipline.

Includes everything in `silver`, plus:

- extracted exact target strings from task success assertions
- stronger anti-guessing rules for names, emails, amounts, URLs, and route fragments

### `platinum`

The strongest current text-only baseline prompt.

Includes everything in `gold`, plus:

- source-package auth hints
- seeded-entity hints from source seed notes
- a stronger per-step decision checklist for login, validation recovery, and finish behavior

## Example commands

Run a single task with the cheapest baseline:

```bash
nexui run examples/tasks/internet-add-remove-elements-001 \
  --agent gemini \
  --gemini-model gemini-2.5-flash-lite \
  --gemini-prompt-profile candidates_only \
  --gemini-thinking-budget 0 \
  --gemini-temperature 0
```

Run a stronger text-only baseline:

```bash
nexui run examples/tasks/govuk-service-validation-recovery-001 \
  --agent gemini \
  --gemini-model gemini-2.5-flash \
  --gemini-prompt-profile candidates_ax \
  --gemini-prompt-league gold \
  --gemini-thinking-budget 0 \
  --gemini-temperature 0
```

Validate a task by generating a Gemini trace:

```bash
nexui validate-task examples/tasks/govuk-service-validation-recovery-001 \
  --agent gemini \
  --gemini-model gemini-2.5-flash \
  --gemini-prompt-profile candidates_ax \
  --gemini-prompt-league platinum \
  --max-steps 50
```

## Recommended first evaluation ladder

1. Smoke test on 10-12 easy/medium tasks.
2. Freeze the prompt/config once JSON validity is stable.
3. Expand to a 40-task dev slice.
4. Only then run the full `validation` split.

## Flash-only evaluation runner

The repo now includes a first-pass evaluation harness for the three Flash baselines:

- `gemini-2.5-flash-lite`
- `gemini-2.5-flash`
- `gemini-3.5-flash`

Run it like this:

```bash
export GEMINI_API_KEY='your-key-here'
PYTHONPATH=src python3 scripts/run_flash_baselines.py --split validation
```

Useful flags:

- `--limit 10`
- `--leagues bronze silver gold platinum`
- `--save-traces`
- `--max-steps 20`
- `--reseed-required-tasks`

Outputs:

- `results.json`
- `summary.md`

under a timestamped directory in `reports/baselines/`.

## Trace metadata

Gemini runs now record per-step agent metadata in traces:

- provider
- model
- prompt profile
- latency
- Gemini usage metadata when available

This is meant to support later baseline reporting without changing the task format.
