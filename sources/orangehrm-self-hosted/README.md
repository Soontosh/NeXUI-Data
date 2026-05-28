# OrangeHRM Self-Hosted

This source package tracks authoring work for `orangehrm-self-hosted`.

## Workflow

1. Bring up the official OrangeHRM development environment using the checkouts under `external/orangehrm` and `external/orangehrm-os-dev-environment`.
2. Export `DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock` unless it is already set in the shell environment.
3. Run `./scripts/reseed_orangehrm.sh` to rebuild the local install, frontend bundle, seeded employees, and seeded leave balance.
4. Run `./nexui validate-source sources/orangehrm-self-hosted --check-remote`.
5. Run `./nexui survey-source sources/orangehrm-self-hosted` to capture the login and PIM entry points.
6. Review captures and expand `task_ideas`.
7. Add recording recipes under `recipes/`.
8. Use `./nexui record` to generate benchmark task packages.

## Current Status

- official OrangeHRM repositories are checked out locally
- Docker Compose is installed as a user-space CLI plugin
- the dev-environment config is prepared for `localhost:8080`
- the reseed script rebuilds the app install, frontend bundle, and benchmark seed data
- the seeded entities include `NExUI Admin` (`0001`), `Ava Patel` (`0002`), `Marcus Lee` (`0003`), and `Annual Leave`
- the seeded admin account has a deterministic 10-day Annual Leave balance for bounded leave-request authoring
- the login, PIM, My Info, and Leave surfaces are usable for recording
