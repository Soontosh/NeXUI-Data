# Bootstrap

This track should be run only against the official self-hosted OrangeHRM development environment.

Prepared local checkouts:

- `/home/santosh/NeXUI/external/orangehrm`
- `/home/santosh/NeXUI/external/orangehrm-os-dev-environment`

Prepared local Docker Compose plugin:

- `~/.docker/cli-plugins/docker-compose`

Target base URL in this workspace:

```text
http://localhost:8080/
```

Bootstrap steps:

1. Use the OrangeHRM source checkout at `external/orangehrm`.
2. Use the official dev environment at `external/orangehrm-os-dev-environment`.
3. Start the environment with the repo-managed wrapper:

```bash
export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock
cd /home/santosh/NeXUI
./scripts/start_orangehrm.sh
```

4. The start wrapper creates or updates `external/orangehrm-os-dev-environment/.env` so `LOCAL_SRC`, `REMOTE_SRC`, and `NGINX_PORT=8080` are correct for this workspace.
5. The wrapper temporarily patches the PHP 8.1 Nginx vhost during the image build so the runtime answers on `localhost`, then restores the checkout file so `external/` does not stay dirty.
6. Install PHP dependencies inside the PHP 8.1 container:

```bash
docker compose exec -T php-8.1 bash -lc 'cd /var/www/src && composer install --no-interaction --prefer-dist'
```

7. Complete the OrangeHRM installer using the seeded values from `seed-notes.md`.
8. Build the frontend bundle from the OrangeHRM client source:

```bash
docker compose exec -T php-8.1 bash -lc 'cd /var/www/src/client && corepack yarn install && corepack yarn build'
```

9. Ensure runtime-write directories are writable inside the app container:

```bash
docker compose exec -T php-8.1 bash -lc 'cd /var/www && find src/cache src/log lib/confs/cryptokeys -type d -exec chmod 777 {} + && touch src/log/orangehrm.log && chmod 666 src/log/orangehrm.log'
```

Quick readiness check:

```bash
./scripts/check_orangehrm_readiness.sh
```

Preferred deterministic reset once the environment is bootstrapped:

```bash
export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock
cd /home/santosh/NeXUI
./scripts/reseed_orangehrm.sh
```

Current state:

- rootless Docker works in this workspace through `DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock`
- OrangeHRM is installed, reseedable, and the PIM, My Info, and Leave surfaces have been validated for benchmark authoring
- the benchmark runtime no longer depends on leaving manual OrangeHRM patches checked into the local `external/` worktrees

Avoid recording against the public hosted demo for benchmark task generation.
