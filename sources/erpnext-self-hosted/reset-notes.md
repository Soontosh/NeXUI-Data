# Reset Notes

Reset strategy: `reseed_command`

Current reset contract:
1. run `docker compose down -v --remove-orphans` against the disposable `pwd.yml` stack plus the local port override
2. bring the stack back with `docker compose ... up -d`
3. wait for the `create-site` service to exit successfully
4. wait for `http://localhost:8090/login` to return successfully
5. complete the first-run setup wizard automatically
6. seed deterministic business fixtures
7. leave the runtime on the disposable demo site's default seeded login

Reset entrypoint:
- `./scripts/reseed_erpnext.sh`

Current guarantees:
- this reset path recreates the default disposable ERPNext demo site
- it seeds:
  - customer `NExUI Test Customer`
  - item `NEXUI-ITEM-001`
  - supplier `NExUI Test Supplier`
  - address `NExUI Test Customer Billing`
  - contact `customer@example.test`
- treat the source as runtime-ready only after the stack is actually reachable on `localhost:8090`
