# WebArena Verified GitLab

This source package tracks authoring work for `webarena-verified-gitlab`.

## Workflow

1. Start the official container with rootless Docker and expose ports `8023` and `8024`.
2. Run `DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock ./nexui validate-source sources/webarena-verified-gitlab --check-remote`.
3. Run `./nexui survey-source sources/webarena-verified-gitlab --overwrite`.
4. Review login, issues, issue-detail, new-issue, and project-settings captures.
5. Expand `task_ideas` and add recorder recipes under `recipes/`.
6. Use `./nexui record` to generate benchmark task packages.

Survey captures can validate routing and candidate extraction, but the first recorded tasks should perform a deterministic UI login with the seeded `byteblaze` account before relying on authenticated controls.
