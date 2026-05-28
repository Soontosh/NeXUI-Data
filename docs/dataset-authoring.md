# Dataset Authoring Workflow

## Purpose

The NExUI runtime, capture pipeline, and recorder are now sufficient to build individual tasks. The missing piece for real benchmark sites is a repeatable authoring workflow that handles:

- source intake
- source policy and provenance
- entry-point surveying
- task idea tracking
- progression from site survey to recorded task package

This document defines that workflow.

## Inspiration

This workflow is intentionally similar in spirit to Terminal-Bench's adapter and registry model:

- keep dataset metadata explicit and versionable
- separate source intake from task generation
- preserve provenance and review artifacts
- make generated tasks reproducible from documented inputs

Relevant references:

- Terminal-Bench registry: `registry.json`-style dataset discovery and versioning
- Terminal-Bench adapter workflow: fork or understand source benchmark, generate tasks into a standard format, document parity and provenance

## Authoring Units

NExUI now distinguishes between:

- `source package`: metadata and working files for one real site
- `source track`: a family of related sources and task styles, such as modern authenticated apps or service-form prototypes
- `survey capture`: snapshot bundles collected from source entry points
- `recording recipe`: deterministic path through a page or workflow
- `task package`: benchmark-ready runnable task

## Source Package Layout

```text
sources/
  registry.json
  <site-id>/
    site.yaml
    README.md
    bootstrap.md
    reset-notes.md
    seed-notes.md
    intake-checklist.md
    notes.md
    task-ideas.md
    captures/
      <entry-id>/
        s000/
          ...
    recipes/
      ...
    survey-summary.json
```

`site.yaml` can also include a `runtime` section for self-hosted and benchmark-environment tracks. This should describe:

- where the local checkout is expected to live
- how to tell whether the source is up
- how to bootstrap it
- how to start it
- how to reseed or reset it

## Workflow

### 0. Choose The Right Source Track

Before intake, classify the source into one of the benchmark tracks:

- `accessibility_first_demo`
- `ui_automation_demo`
- `service_form_pattern`
- `modern_authenticated_app`
- `enterprise_workflow`
- `sandboxed_benchmark_env`

This determines the expected hosting model, reset strategy, auth model, and likely difficulty range.

### 1. Source Intake

Create a source package:

```bash
./nexui init-source the-internet \
  --site-name "The Internet" \
  --base-url https://the-internet.herokuapp.com/ \
  --source-track ui_automation_demo \
  --category ui_automation_demo \
  --hosting-mode live_demo \
  --redistribution-class live_only_academic_source
```

This creates a source workspace and registers it in `sources/registry.json`.

Fill these files immediately for stateful or self-hosted tracks:

- `bootstrap.md`
- `reset-notes.md`
- `seed-notes.md`

### 2. Entry-Point Survey

Fill `site.yaml` with one or more entry points, then capture them:

```bash
./nexui survey-source sources/the-internet
```

This writes snapshot bundles under `captures/<entry-id>/s000/` and a `survey-summary.json` file for quick review.

Entry points may now be either:

- `url`: for live demos, self-hosted apps, and benchmark environments
- `path`: for local fixtures and pattern-derived prototypes checked into the repo

Self-hosted and benchmark-environment sources can also declare `capture_defaults.http_headers` in `site.yaml` when survey must send deterministic local auth or routing headers.

For a local fixture or prototype source, validate it first:

```bash
./nexui validate-source sources/govuk-service-prototype-local
```

For a self-hosted source, use the same validation path to distinguish metadata completeness from actual runtime readiness:

```bash
./nexui validate-source sources/cypress-realworld-app --check-remote
```

That command now reports:

- whether required onboarding docs exist
- whether local path-based entry points resolve
- whether configured runtime checkout paths exist
- whether the configured healthcheck URL responds when probed
- whether an optional `runtime.readiness_command` succeeds for deeper backend checks

### 3. Task Idea Triage

After survey, author candidate tasks in:

- `site.yaml` under `task_ideas`
- `task-ideas.md` for higher-level notes

This is where you decide whether a task is:

- safe enough to package
- reproducible enough for the public split
- supported by the current capture and recorder tooling

### 4. Recipe Authoring

Translate a selected task idea into a deterministic recording recipe under:

```text
sources/<site-id>/recipes/
```

The recipe should point to the real site URL and express actions semantically where possible, for example `target_role + target_name`.

### 5. Record The Task

Use the recorder to emit a benchmark task package:

```bash
./nexui record \
  --recipe sources/the-internet/recipes/login-basic.json \
  --output-dir examples/tasks
```

### 6. Validate

Validate the generated task with:

```bash
./nexui inspect examples/tasks/<task-id>
./nexui run examples/tasks/<task-id> --agent oracle
./nexui run examples/tasks/<task-id> --agent oracle --reseed-source
./nexui score traces/<trace>.json --task examples/tasks/<task-id>
```

For mutating tasks on reseedable sources, set `requires_source_reset: true` in `task.yaml` and use `./nexui reseed-source <source>` or the `--reseed-source` flag on `record`, `run`, and `validate-task`.

## Registry

`sources/registry.json` is the canonical list of source packages in the repository. It is the equivalent of a dataset intake queue rather than a public benchmark registry.

Each registry entry now records:

- source track
- hosting mode
- reset strategy
- determinism level
- authoring status
- legal review status
- reset verification status
- source priority

The repository now also supports explicit source validation before survey or recording:

- onboarding docs must exist
- local `path` entry points must resolve
- optional remote URL checks can be enabled with `./nexui validate-source ... --check-remote`
- self-hosted runtime metadata can be checked for checkout-path and healthcheck readiness
- self-hosted or benchmark-environment sources can optionally add `runtime.readiness_command` when "frontend is up" is not enough to declare the runtime ready

Recommended source statuses:

- `planned`
- `intake`
- `surveyed`
- `recording`
- `validated`
- `published`
- `blocked`

## Seed Real Sites And Tracks

The repository now includes seed manifests for these real candidate sites:

- `w3c-bad`
- `the-internet`
- `ui-testing-playground`
- `demoqa`
- `orangehrm`
- `parabank`
- `cypress-realworld-app`
- `orangehrm-self-hosted`
- `govuk-design-patterns`
- `govuk-service-prototype-local`
- `hmrc-prototype-guidance`
- `webarena-verified-shopping-admin`

These span multiple source tracks and are not all intended to become benchmark tasks directly. For example:

- `govuk-design-patterns` and `hmrc-prototype-guidance` are pattern sources for building local prototypes
- `govuk-service-prototype-local` is the first runnable local prototype derived from the service-form pattern track
- `cypress-realworld-app`, `orangehrm-self-hosted`, and `webarena-verified-shopping-admin` are intended as self-hosted or benchmark-environment task sources

## Current Limits

- survey only captures initial entry-point states, not multi-page crawls
- login state injection and credential management are still manual
- source onboarding docs are now existence-checked, but richer machine validation of bootstrap correctness is still pending
- source manifests are JSON-compatible YAML to stay aligned with the current stdlib-only Python runtime
- review checklists are documented, not yet machine-enforced

## Task Metadata And Split Management

As the benchmark scales, authoring also needs to maintain benchmark-wide inventory metadata rather than only per-task correctness.

Production `task.yaml` files can now declare:

- `difficulty_band`
- `difficulty_dimensions`
- `source_surface`
- `split`
- `stability_runs_passed`

Dataset splits live under `splits/` and should be validated regularly:

```bash
./nexui list-tasks
./nexui validate-splits
```

The intended split contract is:

- `dev`, `validation`, and `test` are mutually disjoint
- `challenge` is a subset of `test`
- harder tasks should prefer semantic success assertions over final-snapshot equality

For the current development stage, the validated production tasks are assigned to `dev` while the benchmark is still being expanded.
