#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_ROOT="$REPO_ROOT/external/frappe_docker"
OVERRIDE_FILE="$REPO_ROOT/sources/erpnext-self-hosted/compose.erpnext-nexui.yml"
HEALTHCHECK_URL="http://localhost:8090/login"

export DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"

if [[ ! -d "$STACK_ROOT" ]]; then
  echo "Missing frappe_docker checkout at $STACK_ROOT" >&2
  exit 1
fi

cd "$STACK_ROOT"

docker compose -f pwd.yml -f "$OVERRIDE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
docker compose -f pwd.yml -f "$OVERRIDE_FILE" up -d

create_site_id="$(docker compose -f pwd.yml -f "$OVERRIDE_FILE" ps -q create-site)"
if [[ -n "$create_site_id" ]]; then
  deadline=$((SECONDS + 900))
  while (( SECONDS < deadline )); do
    state="$(docker inspect -f '{{.State.Status}}' "$create_site_id" 2>/dev/null || true)"
    exit_code="$(docker inspect -f '{{.State.ExitCode}}' "$create_site_id" 2>/dev/null || true)"
    if [[ "$state" == "exited" ]]; then
      if [[ "$exit_code" == "0" ]]; then
        break
      fi
      docker logs "$create_site_id" >&2 || true
      echo "ERPNext create-site exited with code $exit_code" >&2
      exit 1
    fi
    sleep 5
  done
fi

deadline=$((SECONDS + 600))
while (( SECONDS < deadline )); do
  if curl -fsS "$HEALTHCHECK_URL" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

if (( SECONDS >= deadline )); then
  echo "ERPNext healthcheck did not become ready at $HEALTHCHECK_URL" >&2
  exit 1
fi

node - <<'JS'
const { chromium } = require('playwright');

const LOGIN_URL = 'http://localhost:8090/login';
const SETUP_EMAIL = 'nexui.admin@example.test';
const SETUP_PASSWORD = 'NExUIAdmin!2026';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  await page.goto(LOGIN_URL, { waitUntil: 'networkidle' });
  await page.getByLabel(/email/i).fill('Administrator');
  await page.getByLabel(/password/i).fill('admin');
  await page.getByRole('button', { name: /login/i }).click();
  await page.waitForTimeout(1500);

  for (let attempts = 0; attempts < 12; attempts++) {
    const url = page.url();
    if (!url.includes('/desk/setup-wizard/')) {
      await browser.close();
      return;
    }

    if (url.endsWith('/0')) {
      await page.waitForTimeout(1000);
      if (!page.url().includes('/desk/setup-wizard/')) {
        continue;
      }
      const next = page.getByRole('button', { name: /next/i });
      if (!(await next.count())) {
        await page.waitForTimeout(1000);
        continue;
      }
      await next.click();
      await page.waitForTimeout(1000);
      continue;
    }

    if (url.endsWith('/1')) {
      await page.locator('input[data-fieldname="full_name"]').fill('NExUI Admin');
      await page.locator('input[data-fieldname="email"]').fill(SETUP_EMAIL);
      await page.locator('input[data-fieldname="password"]').fill(SETUP_PASSWORD);
      await page.getByRole('button', { name: /next/i }).click();
      await page.waitForTimeout(1000);
      continue;
    }

    if (url.endsWith('/2')) {
      await page.locator('input[data-fieldname="company_name"]').fill('NExUI Benchmark Lab');
      await page.locator('input[data-fieldname="company_abbr"]').fill('NBL');
      await page.getByRole('button', { name: /complete setup/i }).click();
      await page.waitForTimeout(3000);
      continue;
    }

    break;
  }

  if (page.url().includes('/desk/setup-wizard/')) {
    throw new Error(`ERPNext setup wizard remained active at ${page.url()}`);
  }

  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
JS

docker exec frappe_docker-backend-1 bash -lc 'mkdir -p /home/frappe/logs /home/frappe/frappe-bench/frontend/logs'
docker exec -i frappe_docker-backend-1 bash -lc 'cd /home/frappe/frappe-bench && ./env/bin/python -' \
  < "$REPO_ROOT/scripts/seed_erpnext_fixtures.py"

echo "ERPNext runtime is ready at $HEALTHCHECK_URL"
echo "Current seeded login: Administrator / admin"
echo "Setup wizard is completed with organization 'NExUI Benchmark Lab'"
