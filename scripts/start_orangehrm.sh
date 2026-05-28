#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV_ENV_DIR="$ROOT_DIR/external/orangehrm-os-dev-environment"
APP_DIR="$ROOT_DIR/external/orangehrm"
ENV_DIST_FILE="$DEV_ENV_DIR/.env.dist"
ENV_FILE="$DEV_ENV_DIR/.env"
NGINX_CONF="$DEV_ENV_DIR/server/nginx/config/orangehrm.conf"
SOCKET_PATH="/run/user/$(id -u)/docker.sock"

if [[ -z "${DOCKER_HOST:-}" && -S "$SOCKET_PATH" ]]; then
  export DOCKER_HOST="unix://$SOCKET_PATH"
fi

if [[ ! -d "$DEV_ENV_DIR" ]]; then
  echo "Missing OrangeHRM dev environment checkout: $DEV_ENV_DIR" >&2
  exit 1
fi

if [[ ! -d "$APP_DIR" ]]; then
  echo "Missing OrangeHRM app checkout: $APP_DIR" >&2
  exit 1
fi

if [[ ! -f "$ENV_DIST_FILE" ]]; then
  echo "Missing OrangeHRM env template: $ENV_DIST_FILE" >&2
  exit 1
fi

if [[ ! -f "$NGINX_CONF" ]]; then
  echo "Missing OrangeHRM nginx config: $NGINX_CONF" >&2
  exit 1
fi

upsert_env_value() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s#^${key}=.*#${key}=${value}#" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >>"$ENV_FILE"
  fi
}

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$ENV_DIST_FILE" "$ENV_FILE"
fi

upsert_env_value "LOCAL_SRC" "$APP_DIR"
upsert_env_value "REMOTE_SRC" "/var/www"
upsert_env_value "MYSQL_ROOT_PW" "root"
upsert_env_value "NGINX_PORT" "8080"
upsert_env_value "NGINX_SSL_PORT" "8443"

backup_file="$(mktemp)"
cp "$NGINX_CONF" "$backup_file"
cleanup() {
  if [[ -f "$backup_file" ]]; then
    cp "$backup_file" "$NGINX_CONF"
    rm -f "$backup_file"
  fi
}
trap cleanup EXIT

perl -0pi -e 's/server_name php81(?: localhost 127\.0\.0\.1)?;/server_name php81 localhost 127.0.0.1;/g' "$NGINX_CONF"

cd "$DEV_ENV_DIR"
docker compose build nginx
docker compose up -d php-8.1 mysql57 nginx

echo "OrangeHRM runtime started."
