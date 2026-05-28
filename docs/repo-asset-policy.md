# Repository Asset Policy

This document records the first publication-hygiene decision for NExUI: which assets belong in Git, which should be fetched after clone, and what must be cleaned from Git history before a public release.

## Current Audit Findings

Audit command:

```bash
./scripts/audit_repo_assets.py
```

Current repo state from the audit:

- no currently tracked files over `10 MB`
- no currently tracked files over `50 MB`
- task packages are large in aggregate, but individual tracked files stay within ordinary Git limits
- the main publication risk is **historical**, not current: old WebArena map archives still exist in Git history

Largest historical blobs identified so far:

- `downloads/webarena-verified-map/nominatim_volumes.tar`
- `downloads/webarena-verified-map/osrm_routing.tar`
- `downloads/webarena-verified-map/osm_tile_server.tar`
- an older partial `downloads/webarena-verified-map/nominatim_volumes.tar`

These archives are much too large for a healthy public Git history and must not remain in release history.

## Policy Decisions

### Keep in ordinary Git

Keep these in normal Git:

- source manifests and source docs
- scripts and bootstrap helpers
- task packages
- split manifests
- schemas, reports, and validation code
- moderate-size snapshot assets already embedded in task packages

Rationale:

- these files are benchmark-defining artifacts
- they are versioned inputs to evaluation and authoring
- they are small enough for ordinary Git usage

### Do not use Git LFS by default

NExUI should not move runtime downloads into Git LFS by default.

Do **not** use LFS for:

- `downloads/**/*.tar`
- `downloads/**/*.pbf`
- container-generated outputs
- runtime logs
- source-runtime caches

Rationale:

- these assets are reproducible or fetchable on demand
- LFS would move the storage burden rather than solving it
- download scripts are a better fit than versioning giant archives

Git LFS should only be introduced later if a benchmark-critical binary must truly live in-repo and cannot be regenerated.

### Fetch on demand after clone

These classes should be treated as post-clone downloads:

- `downloads/webarena-verified-map/*`
- other large source-specific archives added in the future
- any reproducible heavy bootstrap payloads for self-hosted sources

Rationale:

- the repo should store the instructions and scripts
- machines should fetch heavyweight runtime data only when that source is needed

### Never treat nested source checkouts as vendored payloads

For `external/`:

- the main repo may reference nested repos or local checkouts
- the main repo should not track their heavyweight payloads directly
- benchmark-specific runtime changes should be applied by repo-managed scripts, not by leaving nested repos dirty

## Required History Decision Before Public Release

Because the huge WebArena map archives already exist in Git history, a simple working-tree cleanup is **not** enough for a polished public release.

Before public publication, remove those history entries with a history rewrite tool such as:

- `git filter-repo`

Target paths for history cleanup:

- `downloads/webarena-verified-map/nominatim_volumes.tar`
- `downloads/webarena-verified-map/osrm_routing.tar`
- `downloads/webarena-verified-map/osm_tile_server.tar`
- `downloads/webarena-verified-map/monaco-latest.osm.pbf`
- and, in general, `downloads/webarena-verified-map/**`

## What Comes Next

The next publication-hygiene phase should:

1. stop tracking heavyweight download artifacts in the repo tree
2. add ignore rules so they are not recommitted
3. add download/bootstrap scripts for post-clone retrieval
4. add documentation for a fresh clone to fetch all required assets
5. rewrite Git history to remove previously committed giant archives before public release
