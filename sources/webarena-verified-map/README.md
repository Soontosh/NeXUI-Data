# WebArena Verified Map

Surveyed source package for the official WebArena Verified map environment.

Current status:
- `authoring_status: surveyed`
- local runtime validated on `http://localhost:3030/`
- survey captures recorded for `map-home`, `map-search`, and `map-route`
- no production tasks are recorded yet

Planned role in the benchmark:
- map search
- search disambiguation
- route planning
- hard and very-hard sandboxed navigation tasks

Primary upstream references:
- official repo: https://github.com/ServiceNow/webarena-verified
- official docs: https://servicenow.github.io/webarena-verified/

Local data notes:
- The local Docker bootstrap for this source is documented in `bootstrap.md`.
- The map data bootstrap downloads large archives into `downloads/webarena-verified-map/`, then extracts them into Docker volumes.
- Once those Docker volumes are populated, the archive directory can be deleted to reclaim space and recreated later by rerunning `./scripts/setup_webarena_map_data.sh`.
