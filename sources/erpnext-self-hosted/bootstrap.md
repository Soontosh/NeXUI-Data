# Bootstrap

Target checkout:
- `external/frappe_docker`

Bootstrap path:
1. Clone the official repo:
   - `git clone https://github.com/frappe/frappe_docker external/frappe_docker`
2. Use the repo-managed Docker Compose override:
   - `sources/erpnext-self-hosted/compose.erpnext-nexui.yml`
   - this remaps the `frontend` service from `8080` to `localhost:8090`
3. Start the disposable ERPNext stack:
   - `export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock`
   - `cd external/frappe_docker`
   - `docker compose -f pwd.yml -f /home/santosh/NeXUI/sources/erpnext-self-hosted/compose.erpnext-nexui.yml up -d`
4. Wait for the `create-site` service to finish and for `http://localhost:8090/login` to respond.
5. Use the disposable demo login:
   - username: `Administrator`
   - password: `admin`
6. The reseed path will also complete the first-run setup wizard and create:
   - organization: `NExUI Benchmark Lab`
   - abbreviation: `NBL`
7. Reset the source later through:
   - `./scripts/reseed_erpnext.sh`

Design constraints:
- do not use an ad hoc community stack
- do not share ports with OrangeHRM
- keep the first authoring batch on explicit UI login rather than stored session state
