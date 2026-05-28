# Reset Notes

This environment is reset by replacing the container with a fresh image-backed instance.

Use rootless Docker:

```bash
export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock
```

Reset command:

```bash
docker rm -f webarena-verified-shopping_admin >/dev/null 2>&1 || true
docker run -d \
  --name webarena-verified-shopping_admin \
  -p 7780:80 \
  -p 7781:8877 \
  am1n3e/webarena-verified-shopping_admin
```

Post-reset checks:

```bash
curl http://localhost:7781/status
curl -I http://localhost:7780/admin/
```

Treat any stateful admin edits as invalid until the container has been recreated.
