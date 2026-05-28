# NExUI

NExUI is an accessibility-first benchmark for context-aware assistive UI agents.

This repository currently defines the `NExUI-Core v0.0` benchmark contract:

- task package structure
- observation schema
- action submission schema
- trace format
- scoring report format
- safety taxonomy
- explanation rubric
- source website policy

The first implementation goal is a small end-to-end development slice with 10 to 15 tasks built on top of these schemas.

## Current CLI

The repository now includes a minimal offline runner and task scaffold.

Use the local wrapper:

```bash
./nexui list-sources
./nexui list-tasks
./nexui init-source my-site --site-name "My Site" --base-url https://example.com/ --source-track other --category other --hosting-mode live_demo --redistribution-class redistributable_source
./nexui validate-source sources/govuk-service-prototype-local
./nexui reseed-source sources/cypress-realworld-app
./nexui validate-splits
./nexui survey-source sources/w3c-bad
./nexui inspect examples/tasks/account-settings-demo
./nexui validate-task examples/tasks/account-settings-demo
./nexui validate-task examples/tasks/account-settings-demo --reseed-source
./nexui capture --url https://example.com --snapshot-dir tmp/example-snapshot
./nexui record --recipe examples/recipes/account-settings-local.json --output-dir tmp/recorded-tasks
./nexui record --recipe examples/recipes/account-settings-local.json --output-dir tmp/recorded-tasks --reseed-source
./nexui run examples/tasks/account-settings-demo --agent oracle
./nexui run examples/tasks/account-settings-demo --agent oracle --reseed-source
./nexui replay traces/account-settings-demo-oracle.json
./nexui replay traces/account-settings-demo-oracle.json --task examples/tasks/account-settings-demo --video videos/account-settings-demo.mp4
./nexui replay traces/account-settings-demo-oracle.json --task examples/tasks/account-settings-demo --report reports/account-settings-demo.html
./nexui score traces/account-settings-demo-oracle.json --task examples/tasks/account-settings-demo
./nexui init-task my-new-task --output-dir examples/tasks
```

Task-authored `.yaml` files are currently expected to be JSON-compatible YAML.

## Dataset Inventory And Splits

The repository now treats task metadata and split manifests as first-class benchmark assets.

Each production `task.yaml` can carry:

- `difficulty_band`
- `difficulty_dimensions`
- `source_surface`
- `split`
- `stability_runs_passed`

The current split manifests live under:

```text
splits/
  dev.json
  validation.json
  test.json
  challenge.json
```

Use:

```bash
./nexui list-tasks
./nexui validate-splits
```

`challenge.json` is intended to be a subset of `test.json`. The current repository state keeps the validated production tasks in `dev` while the benchmark is still being expanded.

## Source Tracks

The source-authoring layer now supports explicit portfolio metadata:

- `source_track`: accessibility-first demo, UI automation demo, service-form pattern, modern authenticated app, enterprise workflow, or sandboxed benchmark environment
- `hosting_mode`: live demo, self-hosted app, benchmark environment, pattern-derived prototype, or local fixture
- `reset_strategy`: none, manual reset, reseed command, docker reset, or fixture reload
- `determinism_level`: low, medium, or high

Each source package also carries onboarding artifacts:

- `bootstrap.md`
- `reset-notes.md`
- `seed-notes.md`

Source entry points can now be either remote `url` targets or local `path` targets. That makes local fixtures and pattern-derived prototypes first-class sources instead of second-class authoring hacks.
For benchmark environments and self-hosted sources that need deterministic local auth, `capture_defaults.http_headers` can now be declared in `site.yaml`, and recorder recipes can declare `http_headers` too.

`./nexui validate-source ...` now checks that a source package is internally consistent before survey or recording.
For self-hosted or benchmark-environment sources, manifests can also define machine-readable runtime metadata such as:

- `runtime.local_checkout_path`
- `runtime.healthcheck_url`
- `runtime.runtime_recipe`
- `runtime.bootstrap_commands`
- `runtime.start_command`
- `runtime.reseed_command`
- `runtime.readiness_command`

Source manifests can also track planning and legal state with fields such as:

- `legal_review_status`
- `reset_verified`
- `source_priority`

This makes it possible to distinguish “documented source” from “runtime-ready source” during authoring.

## Local Setup

The local wrapper prefers a repo `.venv` automatically when it exists:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```
