#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV_ENV_DIR="$ROOT_DIR/external/orangehrm-os-dev-environment"
APP_DIR="$ROOT_DIR/external/orangehrm"
SOCKET_PATH="/run/user/$(id -u)/docker.sock"
CONF_FILE="$APP_DIR/lib/confs/Conf.php"
INSTALLER_CONFIG="$APP_DIR/installer/cli_install_config.yaml"

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

if [[ ! -f "$INSTALLER_CONFIG" ]]; then
  echo "Missing OrangeHRM installer config: $INSTALLER_CONFIG" >&2
  exit 1
fi

cleanup_mode_drift() {
  chmod 644 \
    "$APP_DIR/lib/confs/cryptokeys/.htaccess" \
    "$APP_DIR/src/cache/.gitignore" \
    "$APP_DIR/src/log/.gitignore"
}

rm -f "$CONF_FILE"

cd "$DEV_ENV_DIR"

docker compose down -v --remove-orphans || true
for name in os_dev_php81 os_dev_mysql57 os_dev_nginx; do
  docker rm -f "$name" >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do
    if ! docker ps -a --format '{{.Names}}' | grep -qx "$name"; then
      break
    fi
    sleep 1
  done
done
"$ROOT_DIR/scripts/start_orangehrm.sh"

for _ in $(seq 1 60); do
  if docker compose exec -T mysql57 mysqladmin --skip-ssl ping -uroot -proot --silent >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! docker compose exec -T mysql57 mysqladmin --skip-ssl ping -uroot -proot --silent >/dev/null 2>&1; then
  echo "MySQL did not become ready in time." >&2
  exit 1
fi

installer_backup="$(mktemp)"
cp "$INSTALLER_CONFIG" "$installer_backup"
restore_installer_config() {
  if [[ -f "$installer_backup" ]]; then
    cp "$installer_backup" "$INSTALLER_CONFIG"
    rm -f "$installer_backup"
  fi
}
trap 'restore_installer_config; cleanup_mode_drift' EXIT

cat >"$INSTALLER_CONFIG" <<'EOF'
database:
  hostName: mysql57
  hostPort: 3306
  databaseName: orangehrm_nexui
  privilegedDatabaseUser: root
  privilegedDatabasePassword: root
  useSameDbUserForOrangeHRM: y # y/n, if this field `n` fill `orangehrmDatabaseUser` and `orangehrmDatabasePassword`
  orangehrmDatabaseUser: ~
  orangehrmDatabasePassword: ~
  isExistingDatabase: n # y/n
  enableDataEncryption: n # y/n

organization:
  name: NExUI Benchmark Lab
  country: US

admin:
  adminUserName: nexui_admin
  adminPassword: NExUIAdmin!2026
  adminEmployeeFirstName: NExUI
  adminEmployeeLastName: Admin
  workEmail: admin@nexui.local
  contactNumber: 7015550100
  registrationConsent: true

license:
  agree: y # y/n
EOF

docker compose exec -T php-8.1 bash -lc 'cd /var/www/src && composer install --no-interaction --prefer-dist'
docker compose exec -T php-8.1 bash -lc 'cd /var/www && rm -f lib/confs/Conf.php'
docker compose exec -T php-8.1 bash -lc 'for _ in $(seq 1 60); do mysqladmin --skip-ssl ping -hmysql57 -uroot -proot --silent >/dev/null 2>&1 && exit 0; sleep 2; done; echo "MySQL was not reachable from php-8.1 in time." >&2; exit 1'
docker compose exec -T php-8.1 bash -lc 'cd /var/www && php installer/cli_install.php'
restore_installer_config
docker compose exec -T php-8.1 bash -lc 'cd /var/www/src/client && corepack yarn install && corepack yarn build'
docker compose exec -T php-8.1 bash -lc "cd /var/www && find src/cache src/log lib/confs/cryptokeys -type d -exec chmod 777 {} + && touch src/log/orangehrm.log && chmod 666 src/log/orangehrm.log"

docker compose exec -T mysql57 mysql -uroot -proot -D orangehrm_nexui <<'SQL'
START TRANSACTION;

UPDATE ohrm_leave_type
SET deleted = 1
WHERE name = 'Annual Leave';

DELETE FROM ohrm_leave_entitlement
WHERE emp_number = 1;

DELETE FROM ohrm_leave_period_history;

DELETE FROM hs_hr_config
WHERE name = 'leave_period_defined';

DELETE FROM hs_hr_employee
WHERE employee_id IN ('0002', '0003');

INSERT INTO hs_hr_employee (
  employee_id,
  emp_lastname,
  emp_firstname,
  emp_middle_name,
  emp_work_email,
  joined_date
) VALUES
  ('0002', 'Patel', 'Ava', '', 'ava.patel@example.test', '2026-01-15'),
  ('0003', 'Lee', 'Marcus', '', 'marcus.lee@example.test', '2026-02-03');

INSERT INTO ohrm_leave_type (
  name,
  deleted,
  exclude_in_reports_if_no_entitlement,
  operational_country_id
) VALUES (
  'Annual Leave',
  0,
  0,
  NULL
);

SET @annual_leave_type_id := LAST_INSERT_ID();

INSERT INTO ohrm_leave_period_history (
  leave_period_start_month,
  leave_period_start_day,
  created_at
) VALUES (
  1,
  1,
  CURDATE()
);

INSERT INTO hs_hr_config (
  name,
  value
) VALUES (
  'leave_period_defined',
  'Yes'
);

INSERT INTO ohrm_leave_entitlement (
  emp_number,
  no_of_days,
  days_used,
  leave_type_id,
  from_date,
  to_date,
  credited_date,
  note,
  entitlement_type,
  deleted,
  created_by_id
) VALUES (
  1,
  10.000000000000000,
  0.0000,
  @annual_leave_type_id,
  '2026-01-01 00:00:00',
  '2026-12-31 23:59:59',
  '2026-01-01 00:00:00',
  'NExUI benchmark seeded annual leave balance',
  1,
  0,
  1
);

COMMIT;
SQL

cleanup_mode_drift
trap - EXIT

echo "OrangeHRM reseed complete."
