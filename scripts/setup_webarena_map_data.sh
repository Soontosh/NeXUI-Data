#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${1:-$ROOT_DIR/downloads/webarena-verified-map}"
MODE="${2:-full}"

export DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"

mkdir -p "$DATA_DIR"

case "$MODE" in
  full|backend|routing|geocoder|search|tiles|ci-routing)
    ;;
  *)
    echo "Usage: $0 [data-dir] [full|backend|routing|geocoder|search|tiles|ci-routing]" >&2
    exit 2
    ;;
esac

download_if_missing() {
  local url="$1"
  local out="$2"
  if [[ -f "$out" ]]; then
    if tar -tf "$out" >/dev/null 2>&1; then
      echo "[skip] valid archive exists: $out"
      return
    fi
    echo "[resume] incomplete archive detected: $out"
  fi
  echo "[download] $url"
  wget -c -O "$out" "$url"
  tar -tf "$out" >/dev/null 2>&1
}

ensure_volume() {
  local volume="$1"
  if ! docker volume inspect "$volume" >/dev/null 2>&1; then
    echo "[create] volume $volume"
    docker volume create "$volume" >/dev/null
  fi
}

volume_empty() {
  local volume="$1"
  local first
  first="$(docker run --rm -v "${volume}:/vol:ro" alpine sh -lc 'ls -A /vol | head -1' || true)"
  [[ -z "$first" ]]
}

extract_if_empty() {
  local tar_file="$1"
  local volume="$2"
  local strip_components="$3"
  local extract_path="$4"
  ensure_volume "$volume"
  if ! volume_empty "$volume"; then
    echo "[skip] volume already has data: $volume"
    return
  fi
  echo "[extract] $tar_file -> $volume"
  local tar_name
  tar_name="$(basename "$tar_file")"
  local tar_dir
  tar_dir="$(cd "$(dirname "$tar_file")" && pwd)"
  local cmd="tar -xf /tar/${tar_name} --strip-components=${strip_components} -C /vol"
  if [[ -n "$extract_path" ]]; then
    cmd+=" ${extract_path}"
  fi
  docker run --rm \
    -v "${tar_dir}:/tar:ro" \
    -v "${volume}:/vol" \
    alpine sh -lc "$cmd"
}

generate_ci_routing_if_empty() {
  local pbf_path="$1"
  local volume="$2"
  local profile_lua="$3"
  local marker="us-northeast-latest.osrm.mldgr"
  ensure_volume "$volume"
  if ! volume_empty "$volume"; then
    local existing
    existing="$(docker run --rm -v "${volume}:/vol:ro" alpine sh -lc "test -f /vol/${marker} && echo yes || true")"
    if [[ "$existing" == "yes" ]]; then
      echo "[skip] ci routing data already exists: $volume"
      return
    fi
    echo "[reset] clearing non-routing contents from $volume"
    docker run --rm -v "${volume}:/vol" alpine sh -lc 'rm -rf /vol/* /vol/.[!.]* /vol/..?* 2>/dev/null || true'
  fi

  local pbf_dir
  pbf_dir="$(cd "$(dirname "$pbf_path")" && pwd)"
  local pbf_name
  pbf_name="$(basename "$pbf_path")"
  echo "[generate] monaco ci routing (${profile_lua}) -> $volume"
  docker run --rm \
    -v "${pbf_dir}:/seed:ro" \
    -v "${volume}:/data" \
    ghcr.io/project-osrm/osrm-backend:v5.27.1 \
    bash -lc "cp /seed/${pbf_name} /data/us-northeast-latest.osm.pbf && \
      osrm-extract -p /opt/${profile_lua}.lua /data/us-northeast-latest.osm.pbf && \
      osrm-partition /data/us-northeast-latest.osrm && \
      osrm-customize /data/us-northeast-latest.osrm && \
      rm -f /data/us-northeast-latest.osm.pbf"
}

if [[ "$MODE" == "full" || "$MODE" == "tiles" ]]; then
  download_if_missing \
    "https://webarena-map-server-data.s3.amazonaws.com/osm_tile_server.tar" \
    "$DATA_DIR/osm_tile_server.tar"
fi
if [[ "$MODE" == "full" || "$MODE" == "backend" || "$MODE" == "geocoder" || "$MODE" == "search" ]]; then
  download_if_missing \
    "https://webarena-map-server-data.s3.amazonaws.com/nominatim_volumes.tar" \
    "$DATA_DIR/nominatim_volumes.tar"
fi
if [[ "$MODE" == "full" || "$MODE" == "backend" || "$MODE" == "routing" ]]; then
  download_if_missing \
    "https://webarena-map-server-data.s3.amazonaws.com/osrm_routing.tar" \
    "$DATA_DIR/osrm_routing.tar"
fi

if [[ "$MODE" == "ci-routing" ]]; then
  if [[ ! -f "$DATA_DIR/monaco-latest.osm.pbf" ]]; then
    echo "[download] https://download.geofabrik.de/europe/monaco-latest.osm.pbf"
    curl -L --fail --retry 3 --retry-delay 2 \
      -o "$DATA_DIR/monaco-latest.osm.pbf" \
      "https://download.geofabrik.de/europe/monaco-latest.osm.pbf"
  else
    echo "[skip] monaco PBF exists: $DATA_DIR/monaco-latest.osm.pbf"
  fi
fi

if [[ "$MODE" == "full" || "$MODE" == "tiles" ]]; then
  extract_if_empty \
    "$DATA_DIR/osm_tile_server.tar" \
    "webarena-verified-map-tile-db" \
    "6" \
    "projects/ogma3/docker/volumes/osm-data/_data"
fi

if [[ "$MODE" == "full" || "$MODE" == "backend" || "$MODE" == "routing" ]]; then
  extract_if_empty \
    "$DATA_DIR/osrm_routing.tar" \
    "webarena-verified-map-routing-car" \
    "1" \
    "car"
  extract_if_empty \
    "$DATA_DIR/osrm_routing.tar" \
    "webarena-verified-map-routing-bike" \
    "1" \
    "bike"
  extract_if_empty \
    "$DATA_DIR/osrm_routing.tar" \
    "webarena-verified-map-routing-foot" \
    "1" \
    "foot"
fi

if [[ "$MODE" == "ci-routing" ]]; then
  generate_ci_routing_if_empty \
    "$DATA_DIR/monaco-latest.osm.pbf" \
    "webarena-verified-map-routing-car" \
    "car"
  generate_ci_routing_if_empty \
    "$DATA_DIR/monaco-latest.osm.pbf" \
    "webarena-verified-map-routing-bike" \
    "bicycle"
  generate_ci_routing_if_empty \
    "$DATA_DIR/monaco-latest.osm.pbf" \
    "webarena-verified-map-routing-foot" \
    "foot"
fi

if [[ "$MODE" == "full" || "$MODE" == "backend" || "$MODE" == "geocoder" || "$MODE" == "search" ]]; then
  extract_if_empty \
    "$DATA_DIR/nominatim_volumes.tar" \
    "webarena-verified-map-nominatim-db" \
    "7" \
    "projects/metis2/docker/docker/volumes/nominatim-data/_data"
  extract_if_empty \
    "$DATA_DIR/nominatim_volumes.tar" \
    "webarena-verified-map-nominatim-flatnode" \
    "7" \
    "projects/metis2/docker/docker/volumes/nominatim-flatnode/_data"
fi

case "$MODE" in
  full)
    echo "[done] WebArena map data volumes are ready."
    ;;
  backend)
    echo "[done] WebArena map backend volumes are ready (routing + nominatim)."
    ;;
  routing)
    echo "[done] WebArena map routing volumes are ready."
    ;;
  ci-routing)
    echo "[done] WebArena map Monaco CI routing volumes are ready."
    ;;
  geocoder|search)
    echo "[done] WebArena map geocoder volumes are ready."
    ;;
  tiles)
    echo "[done] WebArena map tile volumes are ready."
    ;;
esac
