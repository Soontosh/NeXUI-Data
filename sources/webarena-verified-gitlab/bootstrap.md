# Bootstrap

This track uses the official WebArena Verified `gitlab` image.

Target base URL:

```text
http://localhost:8023/
```

Rootless Docker is expected:

```bash
export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock
```

Bootstrap steps:

```bash
git clone https://github.com/ServiceNow/webarena-verified external/webarena-verified
docker pull am1n3e/webarena-verified-gitlab
docker rm -f webarena-verified-gitlab >/dev/null 2>&1 || true
docker run -d \
  --name webarena-verified-gitlab \
  -p 8023:8023 \
  -p 8024:8877 \
  am1n3e/webarena-verified-gitlab
```

Readiness checks:

```bash
curl http://localhost:8024/status
curl -I http://localhost:8023/users/sign_in
```

Authentication for recorded tasks uses the seeded UI login:

```text
username: byteblaze
password: hello1234
```

Because GitLab startup can take several minutes, do not record tasks until the sign-in page responds cleanly and `validate-source --check-remote` passes.
