# Reset Notes

This environment is reset by replacing the container with a fresh image-backed instance.

Use rootless Docker:

```bash
export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock
```

Reset command:

```bash
docker rm -f webarena-verified-gitlab >/dev/null 2>&1 || true
docker run -d \
  --name webarena-verified-gitlab \
  -p 8023:8023 \
  -p 8024:8877 \
  am1n3e/webarena-verified-gitlab
```

Post-reset checks:

```bash
curl http://localhost:8024/status
curl -I http://localhost:8023/users/sign_in
```

Treat any issue creation or project-settings edits as invalid until the container has been recreated.
