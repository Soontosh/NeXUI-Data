# Reset Notes

Intended reset contract:
- reset strategy: `docker_reset`
- runtime hook: rerun the documented map container command after data initialization is complete

Current validated behavior:
- map runtime reset is container-based
- the backing volumes should be treated as part of the deterministic local environment once the initial data setup has been completed
- `./scripts/setup_webarena_map_data.sh` is now the supported data bootstrap path for the Docker volumes used by this repo's map source
- the runtime command must publish the container's Apache-backed map services on host port `3030`
- the runtime command must also run `./scripts/patch_webarena_map_assets.sh webarena-verified-map http://localhost:3030` so the browser-facing JS bundle points at the host-visible `/osrm/` and `/nominatim/` services after every clean container boot

Open work for the next implementation phase:
1. finish the geocoder bootstrap so `./scripts/check_webarena_map_readiness.sh ... search` passes
2. confirm whether the populated map volumes can be reused safely across repeated authoring cycles
3. record the first search and disambiguation tasks after the geocoder endpoint is healthy
4. decide whether full source readiness should remain route-only until geocoder work is complete
