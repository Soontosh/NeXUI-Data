#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${1:-webarena-verified-map}"
PUBLIC_BASE_URL="${2:-http://localhost:3030}"

wait_for_container() {
  local attempts=0
  until docker exec "$CONTAINER_NAME" sh -lc 'test -d /app/public/assets'; do
    attempts=$((attempts + 1))
    if [[ "$attempts" -ge 60 ]]; then
      echo "[fail] assets directory did not become available in $CONTAINER_NAME" >&2
      exit 1
    fi
    sleep 1
  done
}

wait_for_container

docker exec "$CONTAINER_NAME" sh -lc "
set -e
asset=\$(ls /app/public/assets/application-*.js 2>/dev/null | head -n 1)
if [ -z \"\$asset\" ]; then
  echo '[fail] could not find application asset' >&2
  exit 1
fi
python3 - \"\$asset\" \"$PUBLIC_BASE_URL\" <<'PY'
from pathlib import Path
import sys

asset = Path(sys.argv[1])
base = sys.argv[2].rstrip('/')
text = asset.read_text()
replacements = {
    'NOMINATIM_URL:\"/nominatim/\"': f'NOMINATIM_URL:\"{base}/nominatim/\"',
    'FOSSGIS_OSRM_URL:\"/osrm/\"': f'FOSSGIS_OSRM_URL:\"{base}/osrm/\"',
    'NOMINATIM_URL:\"http://localhost:8080/nominatim/\"': f'NOMINATIM_URL:\"{base}/nominatim/\"',
    'FOSSGIS_OSRM_URL:\"http://localhost:8080/osrm/\"': f'FOSSGIS_OSRM_URL:\"{base}/osrm/\"',
}
updated = text
for old, new in replacements.items():
    updated = updated.replace(old, new)
if updated == text:
    raise SystemExit('asset patch made no changes')
asset.write_text(updated)
PY
rm -f \"\$asset\".gz \"\$asset\".br
"

echo "[ok] patched WebArena map assets in $CONTAINER_NAME for $PUBLIC_BASE_URL"
