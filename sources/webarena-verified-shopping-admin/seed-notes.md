# Seed Notes

Current local seed assumptions for the official image:

- admin username: `admin`
- admin password: `admin1234`
- auto-login header for survey and optional recipe authoring:

```text
X-M2-Admin-Auto-Login: admin:admin1234
```

- env-ctrl health endpoint: `http://localhost:7781/status`
- admin base URL: `http://localhost:7780/admin/`

Before authoring tasks, record the exact seeded entities chosen from the live image:

- admin users or roles used for list/detail verification
- safe configuration or catalog surfaces used for update-and-verify tasks
- any destructive or irreversible actions that should be guarded by `ask_user`
