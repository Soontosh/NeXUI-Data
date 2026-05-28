# Bootstrap

This track uses the official WebArena Verified `shopping_admin` image.

Target base URL:

```text
http://localhost:7780/admin/
```

Rootless Docker is expected:

```bash
export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock
```

Bootstrap steps:

```bash
git clone https://github.com/ServiceNow/webarena-verified external/webarena-verified
docker pull am1n3e/webarena-verified-shopping_admin
docker rm -f webarena-verified-shopping_admin >/dev/null 2>&1 || true
docker run -d \
  --name webarena-verified-shopping_admin \
  -p 7780:80 \
  -p 7781:8877 \
  am1n3e/webarena-verified-shopping_admin
```

Readiness checks:

```bash
curl http://localhost:7781/status
curl -I http://localhost:7780/admin/
```

Survey uses the documented auto-login header so captures land on authenticated admin surfaces:

```text
X-M2-Admin-Auto-Login: admin:admin1234
```
