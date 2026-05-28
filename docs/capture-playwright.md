# Playwright Capture Pipeline

## Purpose

The current NExUI runtime can execute packaged offline tasks. This capture pipeline is the first bridge from a live page to a task package snapshot.

The pipeline writes the required `v0.0` snapshot artifacts for one page state:

- `screenshot.png`
- `dom.json`
- `ax_tree.json`
- `aria_snapshot.yml`
- `reader_view.txt`
- `candidates.json`
- `metadata.json`

## Dependency Model

The repository now uses two runtimes on purpose:

- Python: top-level CLI, task runtime, scoring, and packaging
- Node.js + Playwright: browser automation and snapshot capture

Browser capture depends on:

- `node >= 24`
- `npm >= 11`
- `playwright = 1.60.0`
- a locally installed Chromium browser via `npm run browsers:install`

We keep capture in Node because Playwright's browser and accessibility APIs are more direct there, while the benchmark runtime remains Python-based.

## Installation

From the repository root:

```bash
npm install
npm run browsers:install
```

The Python CLI itself still has no third-party runtime dependency.

## CLI Usage

Capture directly into a snapshot directory:

```bash
./nexui capture \
  --url https://example.com \
  --snapshot-dir tmp/example-snapshot
```

Capture into a task package snapshot slot:

```bash
./nexui capture \
  --url https://example.com \
  --task examples/tasks/account-settings-demo \
  --snapshot-id s000
```

Useful flags:

- `--wait-until domcontentloaded|load|networkidle|commit`
- `--delay-ms 1000`
- `--timeout-ms 30000`
- `--viewport-width 1440`
- `--viewport-height 900`
- `--locale en-US`
- `--browser chromium`
- `--headed`

## Capture Heuristics

The first capture version is intentionally heuristic rather than benchmark-perfect.

### Candidate extraction

Candidate elements are generated from the live DOM using a semantic selector set and lightweight accessibility heuristics:

- native interactive elements such as links, buttons, inputs, selects, textareas, and summary
- common ARIA interactive roles
- focusable elements with `tabindex`
- content-editable elements

Refs are assigned in DOM order as `e1`, `e2`, and so on. These refs are stable only within the captured snapshot, which matches the `v0.0` contract.

### Accessibility tree

`ax_tree.json` is captured from Chromium through the DevTools Accessibility domain when available. This is Chromium-specific in `v0.0`.

### ARIA snapshot

`aria_snapshot.yml` is captured via Playwright's `locator.ariaSnapshot()` API and stored as the raw YAML string returned by Playwright.

### Reader view

`reader_view.txt` is a semantic linearization generated from visible landmarks, headings, form controls, and text content. It is intended as a useful review artifact, not a full assistive technology emulation.

## Current Limits

- Chromium is the only fully supported browser for capture in `v0.0`
- login flows, cookies, and multi-step oracle recording are not implemented yet
- `capture` records one page state at a time
- the Python runtime still expects task-authored `.yaml` files to be JSON-compatible YAML

For multi-step trajectory generation, use the recorder layer documented in:

- [docs/recorder.md](/home/santosh/NeXUI/docs/recorder.md)
