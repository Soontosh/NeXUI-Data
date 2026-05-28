# Bootstrap

Goal: prepare the official WebArena Verified map environment on `http://localhost:3030/`.

Recommended upstream path:
1. Clone the official repo:
   - `git clone https://github.com/ServiceNow/webarena-verified external/webarena-verified`
2. Use rootless Docker:
   - `export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock`
3. Initialize the map data:
   - full data bootstrap:
     - `./scripts/setup_webarena_map_data.sh`
   - route-first bootstrap:
     - `./scripts/setup_webarena_map_data.sh downloads/webarena-verified-map routing`
   - CI-sized route-only fallback if the large routing tar is corrupted or impractical:
     - `./scripts/setup_webarena_map_data.sh downloads/webarena-verified-map ci-routing`
   - geocoder-only bootstrap:
     - `./scripts/setup_webarena_map_data.sh downloads/webarena-verified-map geocoder`
   - full backend bootstrap for route + search work:
     - `./scripts/setup_webarena_map_data.sh downloads/webarena-verified-map backend`
4. Pull the optimized map image:
   - `docker pull am1n3e/webarena-verified-map`
5. Start the local map runtime:
   - `docker rm -f webarena-verified-map >/dev/null 2>&1 || true`
   - `docker run -d --name webarena-verified-map -p 3030:8080 -p 3031:8877 -v webarena-verified-map-tile-db:/data/database -v webarena-verified-map-routing-car:/data/routing/car -v webarena-verified-map-routing-bike:/data/routing/bike -v webarena-verified-map-routing-foot:/data/routing/foot -v webarena-verified-map-nominatim-db:/data/nominatim/postgres -v webarena-verified-map-nominatim-flatnode:/data/nominatim/flatnode -v webarena-verified-map-website-db:/var/lib/postgresql/14/main -v webarena-verified-map-tiles:/data/tiles -v webarena-verified-map-style:/data/style am1n3e/webarena-verified-map`
   - `./scripts/patch_webarena_map_assets.sh webarena-verified-map http://localhost:3030`
6. Check backend readiness:
   - route-only readiness:
     - `./scripts/check_webarena_map_readiness.sh http://localhost:3030 "Carnegie Mellon University" "-79.9436,40.4435;-79.9959,40.4406" routing`
   - geocoder-only readiness:
     - `./scripts/check_webarena_map_readiness.sh http://localhost:3030 "Carnegie Mellon University" "-79.9436,40.4435;-79.9959,40.4406" search`
   - full readiness:
     - `./scripts/check_webarena_map_readiness.sh`

Notes:
- The official docs require a map-specific setup-init step before the container is useful.
- The frontend can render without the heavy map datasets.
- Routing can be brought up independently of geocoding because `osrm_routing.tar` is much smaller than `nominatim_volumes.tar`.
- The public benchmark runtime must be served through the container's Apache port so the browser can use same-origin `/osrm/` and `/nominatim/` routes.
- The source manifest now bakes the compiled-asset patch into `start_command` and `reseed_command`; run the same helper manually only if you start the container outside the source runtime contract.
- Search, disambiguation, and full cross-view map tasks still require the geocoder path.
- `./nexui validate-source sources/webarena-verified-map --check-remote` now runs the readiness script as part of runtime validation, so the source will correctly fail remote validation until backend data is actually present.
- The current source has route-capable seeded Monaco captures available once routing readiness passes, but search and disambiguation remain blocked until the geocoder path is healthy.

Archive cleanup and redownload:
- `./scripts/setup_webarena_map_data.sh` downloads large tarballs into `downloads/webarena-verified-map/` before extracting them into Docker volumes.
- After the Docker volumes are populated, the running container uses those named volumes, not the tarballs under `downloads/`.
- If disk space is tight, it is safe to remove the local archive directory after bootstrap:
  - `rm -rf downloads/webarena-verified-map`
- If the archives are removed and you later need to rebuild the map volumes on this machine, rerun one of the documented bootstrap commands:
  - full data bootstrap: `./scripts/setup_webarena_map_data.sh downloads/webarena-verified-map full`
  - route-only bootstrap: `./scripts/setup_webarena_map_data.sh downloads/webarena-verified-map routing`
  - geocoder-only bootstrap: `./scripts/setup_webarena_map_data.sh downloads/webarena-verified-map geocoder`
  - backend bootstrap: `./scripts/setup_webarena_map_data.sh downloads/webarena-verified-map backend`
