# Reset Notes

Current reset contract:
- reset strategy: `reseed_command`
- runtime hook: `./scripts/reseed_pretix.sh`

Current behavior:
1. remove the `pretix-nexui` container and the `pretix-nexui-data` / `pretix-nexui-public` Docker volumes
2. recreate the standalone Pretix runtime on `localhost:8100`
3. wait for `/control/login`
4. log in as `admin@localhost / admin`
5. enable `Admin mode`
6. recreate organizer `NExUI Benchmark Lab` (`nexui`)
7. recreate event `NExUI Benchmark Event` (`nexui-event`)
8. save a single `General Admission` product
9. leave the control panel ready for survey and first-batch recording

Notes:
- The standalone image still emits background AMQP/cron warnings in logs, but the control UI and seeded admin workflow remain usable for authoring.
