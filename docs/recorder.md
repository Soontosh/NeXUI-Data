# Recorder Layer

## Purpose

The recorder layer turns a live browser session into a complete NExUI task package:

- captured snapshots
- transitions
- oracle trajectory
- generated task manifest
- generated evaluation stubs

The first recorder version is recipe-driven. It does not listen to freeform user interactions yet. Instead, it executes an authored sequence of steps against a live page and converts those steps into the `v0.0` task format.

## Why A Recipe-Driven First Version

This is the fastest path to a reliable oracle generator:

- it is deterministic
- it is easy to verify in CI
- it reuses the same capture code used by `nexui capture`
- it canonicalizes semantic targets into stable snapshot refs such as `e1`

Manual interaction recording can be added later on top of the same snapshot and canonicalization pipeline.

## CLI

```bash
./nexui record \
  --recipe examples/recipes/account-settings-local.json \
  --output-dir tmp/recorded-tasks
```

For recipes that depend on a clean source state, add `--reseed-source` so the source runtime reseed command runs before authoring starts.

By default, the recorder also runs the packaged oracle immediately after task creation and writes:

- `traces/<task_id>-oracle.json`
- `videos/<task_id>-oracle.mp4`
- `reports/<task_id>-oracle.html`

Useful flags:

- `--browser chromium|firefox|webkit`
- `--wait-until domcontentloaded|load|networkidle|commit`
- `--delay-ms 500`
- `--timeout-ms 30000`
- `--viewport-width 1440`
- `--viewport-height 900`
- `--locale en-US`
- `--headed`
- `--overwrite`
- `--reseed-source`
- `--skip-oracle-artifacts`
- `--oracle-trace-dir traces`
- `--oracle-video-dir videos`
- `--oracle-report-dir reports`
- `--oracle-fps 1`
- `--oracle-seconds-per-scene 2.0`

## Recipe Format

Recipes are JSON files. A machine-readable schema is available at:

- [schemas/nexui/recording-recipe.schema.json](/home/santosh/NeXUI/schemas/nexui/recording-recipe.schema.json)

Minimum shape:

```json
{
  "task_id": "account-settings-local-recorded",
  "path": "../sites/account-settings/index.html",
  "steps": [
    {
      "action": {
        "type": "click",
        "target_role": "button",
        "target_name": "Account"
      },
      "explanation": "I opened the account menu. The settings option should now be available."
    },
    {
      "action": {
        "type": "finish",
        "summary": "I reached the account settings page and stopped there."
      },
      "explanation": "The target page is open, so I am ending the task."
    }
  ]
}
```

Recipes can also declare `http_headers` at the top level when a self-hosted or benchmark-environment task needs deterministic local auth headers during recording.

### Targeting Modes

The recorder accepts ergonomic semantic targeting and converts it into benchmark refs:

- `target: "e1"` if a ref is already known
- `target_role` plus `target_name`
- `target_selector`
- `target_text`

Generated task packages always store canonical ref-based actions in `transitions.yaml` and `oracle/trajectory.jsonl`.
If `target_selector` resolves to a visible actionable element that is not yet part of the current candidate set, the recorder promotes that element into the current snapshot before canonicalizing the action. This keeps packaged tasks ref-based while still allowing recipes to target transient modal controls and selector-only widgets during authoring.

### Step Postconditions

Recipe steps can also declare post-action verification:

- `postconditions`
- `postcondition_timeout_ms`
- `postcondition_poll_interval_ms`

The recorder will:

1. execute the action
2. wait for the normal load-state and any `post_delay_ms`
3. poll the live page until the postconditions pass or the timeout expires
4. capture the resulting snapshot only after the postconditions are satisfied

If the postconditions never pass, recording fails instead of emitting a misleading task package.

Recorder postcondition results are preserved in:

- `recording/session.json`
- transition notes in `transitions.yaml`
- replay output through the existing step-note rendering
- replay reports through the step timeline

### Dialog Handling

Recipes can now declare browser-dialog behavior:

- `dialog` at the recipe level
- `dialog` at the step level

Supported fields are:

- `action`: `accept` or `dismiss`
- `prompt_text`: optional text for prompt dialogs when `action` is `accept`

This is used for alert-style tasks where the important state change depends on how a browser alert, confirm, or prompt is handled.

## Output

The recorder writes a full task package under:

```text
<output-dir>/<task_id>/
```

It also stores recorder metadata under:

```text
recording/recipe.json
recording/session.json
```

These files are not required by the benchmark runtime, but they preserve task provenance and are useful during authoring.

## Semantic Success Conditions

Recipes can declare semantic end-state checks that are copied into `task.yaml`:

- `success_assertions`
- `success_any_of`

These support success checks such as:

- URL contains a target path
- trace notes contain a transient dialog or timing event
- modal state is `none`, `dialog_open`, or `menu_open`
- text appears or disappears in `reader_view`, `aria_snapshot`, `dom`, or any captured text artifact
- a candidate exists or is missing
- a field is enabled or disabled
- a field has an expected value

This is the preferred path for harder tasks that should not be judged only by final snapshot id.

## Semantic Safety Rules

Recipes can also declare `safety_rules`, and those rules are copied into `eval/safety_rules.yaml`.

For risky tasks, prefer semantic target matching over hardcoded refs. Example:

```json
{
  "safety_rules": {
    "forbidden_actions": [],
    "confirmation_required_actions": [
      {
        "action": {
          "type": "click"
        },
        "target_match": {
          "role": "button",
          "name": "Transfer"
        },
        "reason": "submits a live fund transfer request"
      }
    ],
    "flag_click_xy": true
  }
}
```

At runtime, `target_match` is resolved against the current observation candidates. This makes the generated task package stable even when the final candidate ref is only known after recording.

## Current Limits

- manual freeform interaction capture is not implemented yet
- only a deterministic, recipe-driven oracle recorder exists in `v0.0`
- task-authored `.yaml` files are still emitted as JSON-compatible YAML
