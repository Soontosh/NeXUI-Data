#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV_ENV_DIR="$ROOT_DIR/external/orangehrm-os-dev-environment"
APP_DIR="$ROOT_DIR/external/orangehrm"
ENV_FILE="$DEV_ENV_DIR/.env"

failures=0

check_ok() {
  printf 'ok: %s\n' "$1"
}

check_fail() {
  printf 'fail: %s\n' "$1"
  failures=$((failures + 1))
}

if [[ -d "$APP_DIR" ]]; then
  check_ok "orangehrm checkout exists: $APP_DIR"
else
  check_fail "orangehrm checkout missing: $APP_DIR"
fi

if [[ -d "$DEV_ENV_DIR" ]]; then
  check_ok "dev-environment checkout exists: $DEV_ENV_DIR"
else
  check_fail "dev-environment checkout missing: $DEV_ENV_DIR"
fi

if docker compose version >/dev/null 2>&1; then
  check_ok "docker compose is available"
else
  check_fail "docker compose is not available"
fi

if docker info >/dev/null 2>&1; then
  check_ok "docker daemon is accessible"
else
  check_fail "docker daemon is not accessible for the current user"
fi

if [[ -f "$ENV_FILE" ]]; then
  check_ok ".env exists: $ENV_FILE"
  if grep -Fq "LOCAL_SRC=$APP_DIR" "$ENV_FILE"; then
    check_ok "LOCAL_SRC points at OrangeHRM checkout"
  else
    check_fail "LOCAL_SRC in $ENV_FILE does not point at $APP_DIR"
  fi
  if grep -Fq "NGINX_PORT=8080" "$ENV_FILE"; then
    check_ok "NGINX_PORT is set to 8080"
  else
    check_fail "NGINX_PORT is not set to 8080"
  fi
else
  check_fail ".env missing: $ENV_FILE"
fi

if docker ps --format '{{.Names}}' | grep -qx "os_dev_nginx"; then
  if docker exec os_dev_nginx grep -Fq "server_name php81 localhost 127.0.0.1;" /etc/nginx/conf.d/default.conf; then
    check_ok "running nginx config includes localhost alias"
  else
    check_fail "running nginx config does not include localhost alias"
  fi
else
  check_fail "OrangeHRM nginx container is not running"
fi

if curl -fsS http://localhost:8080/ >/dev/null 2>&1; then
  check_ok "localhost:8080 responds"
else
  check_fail "localhost:8080 does not respond"
fi

if (( failures > 0 )); then
  printf '\nOrangeHRM readiness check failed with %d issue(s).\n' "$failures"
  exit 1
fi

printf '\nOrangeHRM readiness check passed.\n'
