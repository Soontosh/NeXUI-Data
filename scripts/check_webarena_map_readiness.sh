#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://localhost:3030}"
SEARCH_QUERY="${2:-Carnegie Mellon University}"
ROUTE_COORDS="${3:--79.9436,40.4435;-79.9959,40.4406}"
MODE="${4:-full}"
SERVICE_URL="${MAP_SERVICE_URL:-$BASE_URL}"

case "$MODE" in
  full|routing|search|frontend)
    ;;
  *)
    echo "Usage: $0 [base-url] [search-query] [route-coords] [full|routing|search|frontend]" >&2
    exit 2
    ;;
esac

urlencode() {
  python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$1"
}

fail() {
  echo "[fail] $1" >&2
  exit 1
}

pass() {
  echo "[ok] $1"
}

frontend_code="$(curl -sS -o /tmp/webarena-map-home.html -w '%{http_code}' "$BASE_URL/")"
[[ "$frontend_code" == "200" ]] || fail "frontend home returned $frontend_code"
pass "frontend home responds with 200"

if [[ "$MODE" == "frontend" ]]; then
  exit 0
fi

search_page_code="$(curl -sS -o /tmp/webarena-map-search.html -w '%{http_code}' "$BASE_URL/search?query=$(urlencode "$SEARCH_QUERY")")"
[[ "$search_page_code" == "200" ]] || fail "search page returned $search_page_code"
grep -q "Search Results" /tmp/webarena-map-search.html || fail "search page did not render Search Results"
pass "search page opens"

if [[ "$MODE" == "search" || "$MODE" == "full" ]]; then
  geocoder_code="$(curl -sS -o /tmp/webarena-map-geocoder.html -w '%{http_code}' "$SERVICE_URL/nominatim/search?format=jsonv2&q=$(urlencode "$SEARCH_QUERY")")"
  if [[ "$geocoder_code" == "200" ]]; then
    pass "geocoder endpoint responds with 200"
  else
    fail "geocoder endpoint returned $geocoder_code"
  fi
fi

if [[ "$MODE" == "routing" || "$MODE" == "full" ]]; then
  routing_code="$(curl -sS -o /tmp/webarena-map-routing.json -w '%{http_code}' "$SERVICE_URL/osrm/routed-car/route/v1/driving/${ROUTE_COORDS}?overview=false")"
  if [[ "$routing_code" == "200" ]]; then
    pass "routing proxy responds with 200"
  else
    fail "routing proxy returned $routing_code"
  fi
fi
