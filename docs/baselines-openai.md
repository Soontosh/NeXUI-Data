# OpenAI Baseline Quickstart

This adds an OpenAI Responses-based baseline path for NExUI.

Current scope:

- text-only action selection
- the same prompt profiles and prompt leagues used by the Gemini baseline
- structured JSON action output via Responses structured outputs
- reasoning-model support through `--agent openai`
- an offline cost-estimation runner based on the packaged oracle path

## Credentials

Do not hardcode API keys into code or task files.

Use:

- `OPENAI_API_KEY`

Example:

```bash
export OPENAI_API_KEY='your-key-here'
```

## Supported models

The initial OpenAI baseline runner includes presets for:

- `o3`
- `o4-mini`
- `gpt-5-mini`
- `gpt-5.4-mini`

These use the OpenAI Responses API with:

- `reasoning.effort=low`
- `text.verbosity=low`
- `prompt_profile=candidates_ax`
- `prompt_league=platinum`

## Example commands

Run a single task with `o3`:

```bash
nexui run examples/tasks/pretix-open-product-list-001 \
  --agent openai \
  --openai-model o3 \
  --openai-reasoning-effort low \
  --openai-text-verbosity low \
  --openai-prompt-profile candidates_ax \
  --openai-prompt-league platinum
```

Run a cheaper strong baseline:

```bash
nexui run examples/tasks/webarena-map-open-directions-001 \
  --agent openai \
  --openai-model o4-mini \
  --openai-reasoning-effort low \
  --openai-text-verbosity low \
  --openai-prompt-profile candidates_ax \
  --openai-prompt-league platinum
```

Validate a task with OpenAI:

```bash
nexui validate-task examples/tasks/gitlab-login-open-project-settings-001 \
  --agent openai \
  --openai-model gpt-5-mini \
  --openai-prompt-profile candidates_ax \
  --openai-prompt-league platinum
```

## Cost estimation and evaluation runner

The repo now includes:

- `scripts/run_openai_reasoning_baselines.py`

Estimate a split without making API calls:

```bash
PYTHONPATH=src python3 scripts/run_openai_reasoning_baselines.py \
  --split validation \
  --estimate-only
```

Run a live evaluation once `OPENAI_API_KEY` is set:

```bash
PYTHONPATH=src python3 scripts/run_openai_reasoning_baselines.py \
  --split validation \
  --models o4-mini gpt-5-mini \
  --save-traces
```

Outputs are written under a timestamped directory in `reports/baselines/`.

## Notes on cost

The offline estimate is intentionally a range, not a fake-precise number:

- input token estimates come from the actual NExUI prompt strings generated along the packaged oracle path
- visible output token estimates come from the packaged oracle action JSON
- reasoning-token costs are estimated heuristically from the configured effort
- the report also includes a hard upper bound based on `max_output_tokens`

Use the live run reports to replace the estimate once you have a key and real usage data.
