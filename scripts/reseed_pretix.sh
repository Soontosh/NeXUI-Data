#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECKOUT_DIR="$ROOT_DIR/external/pretix"
HEALTHCHECK_URL="http://localhost:8100/control/login?next=/control/"

export DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"

if [[ ! -d "$CHECKOUT_DIR" ]]; then
  echo "Missing pretix checkout at $CHECKOUT_DIR" >&2
  exit 1
fi

docker rm -f pretix-nexui >/dev/null 2>&1 || true
docker volume rm pretix-nexui-data pretix-nexui-public >/dev/null 2>&1 || true

docker run -d \
  --name pretix-nexui \
  -p 8100:80 \
  -v pretix-nexui-data:/var/pretix/data \
  -v pretix-nexui-public:/public \
  pretix/standalone:stable >/dev/null

deadline=$((SECONDS + 900))
while (( SECONDS < deadline )); do
  if curl -fsS -I "$HEALTHCHECK_URL" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

if (( SECONDS >= deadline )); then
  echo "pretix control login did not become ready at $HEALTHCHECK_URL" >&2
  docker logs --tail 200 pretix-nexui >&2 || true
  exit 1
fi

node - <<'JS'
const { chromium } = require('playwright');

const LOGIN_URL = 'http://localhost:8100/control/login?next=/control/';
const ORGANIZER_NAME = 'NExUI Benchmark Lab';
const ORGANIZER_SLUG = 'nexui';
const EVENT_NAME = 'NExUI Benchmark Event';
const EVENT_SLUG = 'nexui-event';
const PRODUCT_NAME = 'General Admission';
const CONTACT_EMAIL = 'admin@example.test';
const EVENT_BASE_URL = `http://localhost:8100/control/event/${ORGANIZER_SLUG}/${EVENT_SLUG}`;

async function ensureLoggedIn(page) {
  await page.goto(LOGIN_URL, { waitUntil: 'load' });
  await page.locator('#id_email').fill('admin@localhost');
  await page.locator('#id_password').fill('admin');
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.waitForTimeout(1000);
  const adminModeButton = page.getByRole('button', { name: 'Admin mode' });
  if (await adminModeButton.count()) {
    await adminModeButton.click();
    await page.waitForTimeout(1000);
  }
}

async function pageLooksMissing(page) {
  const title = await page.title();
  if (/not found/i.test(title)) {
    return true;
  }
  const body = await page.locator('body').innerText();
  return /could not find the the resource you requested|selected event was not found/i.test(body);
}

async function ensureOrganizer(page) {
  await page.goto('http://localhost:8100/control/organizers/', { waitUntil: 'load' });
  if (await page.getByText(ORGANIZER_NAME, { exact: true }).count()) {
    return;
  }

  await page.goto('http://localhost:8100/control/organizers/add', { waitUntil: 'load' });
  await page.getByLabel('Name').fill(ORGANIZER_NAME);
  await page.getByLabel('Short form').fill(ORGANIZER_SLUG);
  await page.getByRole('button', { name: 'Save' }).click();
  await page.waitForTimeout(1000);

  if (!page.url().includes(`/control/organizer/${ORGANIZER_SLUG}/`)) {
    throw new Error(`Organizer creation did not land on ${ORGANIZER_SLUG}: ${page.url()}`);
  }
}

async function ensureEvent(page) {
  const eventSettingsUrl = `${EVENT_BASE_URL}/settings/`;
  await page.goto(eventSettingsUrl, { waitUntil: 'load' });
  if (!(await pageLooksMissing(page))) {
    return;
  }

  await page.goto('http://localhost:8100/control/events/add', { waitUntil: 'load' });
  await page.locator('input[name="foundation-has_subevents"]').nth(0).check();
  await page.locator('#id_foundation-locales_0_0').check();
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.waitForTimeout(800);

  await page.locator('#id_basics-name_0').fill(EVENT_NAME);
  await page.locator('#id_basics-slug').fill(EVENT_SLUG);
  await page.locator('#id_basics-date_from_0').fill('2026-06-15');
  await page.locator('#id_basics-date_from_1').fill('10:00');
  await page.locator('#id_basics-date_to_0').fill('2026-06-15');
  await page.locator('#id_basics-date_to_1').fill('18:00');
  await page.locator('#id_basics-currency').selectOption({ label: 'USD - US Dollar' });
  await page.locator('#id_basics-timezone').selectOption({ label: 'UTC' });
  await page.locator('#id_basics-no_taxes').check();
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.locator('#id_form-0-name_0').waitFor({ state: 'visible' });

  if (await pageLooksMissing(page)) {
    throw new Error(`Event creation landed on a missing-resource page: ${page.url()}`);
  }
}

async function ensureProduct(page) {
  const itemsUrl = `${EVENT_BASE_URL}/items/`;
  await page.goto(itemsUrl, { waitUntil: 'load' });
  if (!(await pageLooksMissing(page)) && await page.getByText(PRODUCT_NAME, { exact: true }).count()) {
    return;
  }

  const quickstartUrl = `${EVENT_BASE_URL}/quickstart/?congratulations=1`;
  await page.goto(quickstartUrl, { waitUntil: 'load' });
  await page.locator('#id_form-0-name_0').waitFor({ state: 'visible' });
  await page.locator('#id_form-0-name_0').fill(PRODUCT_NAME);
  await page.locator('#id_form-0-default_price').fill('25.00');
  await page.locator('#id_form-0-quota').fill('100');
  if (await page.locator('#id_form-1-DELETE').count()) {
    await page.locator('#id_form-1-DELETE').evaluate((el) => {
      el.checked = true;
      el.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }
  await page.locator('#id_contact_mail').fill(CONTACT_EMAIL);
  await page.getByRole('button', { name: 'Save' }).click();
  await page.waitForTimeout(1500);

  await page.goto(itemsUrl, { waitUntil: 'load' });
  if (await pageLooksMissing(page)) {
    throw new Error(`Seeded event items page is still missing after quickstart save: ${page.url()}`);
  }
  if (!(await page.getByText(PRODUCT_NAME, { exact: true }).count())) {
    throw new Error(`Event items page did not show seeded product '${PRODUCT_NAME}'`);
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.setDefaultTimeout(15000);

  await ensureLoggedIn(page);
  await ensureOrganizer(page);
  await ensureEvent(page);
  await ensureProduct(page);

  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
JS

echo "pretix runtime is ready at $HEALTHCHECK_URL"
echo "Seeded organizer: NExUI Benchmark Lab (nexui)"
echo "Seeded event: NExUI Benchmark Event (nexui-event)"
echo "Seeded product: General Admission"
echo "Current deterministic login: admin@localhost / admin"
