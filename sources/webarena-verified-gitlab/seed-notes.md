# Seed Notes

Current local seed assumptions for the official image:

- GitLab username: `byteblaze`
- GitLab password: `hello1234`
- env-ctrl health endpoint: `http://localhost:8024/status`
- GitLab base URL: `http://localhost:8023/`

Known seeded entities referenced by upstream WebArena Verified tests:

- project: `byteblaze/a11y-syntax-highlighting`
- project: `byteblaze/a11y-webring.club`
- stable issue route: `byteblaze/a11y-webring.club/-/issues/21`
- stable settings route: `byteblaze/a11y-syntax-highlighting/edit`

Before authoring mutating tasks, record the exact title or description strings chosen for issue-creation and settings-edit workflows so rerun validation can target deterministic persisted state.
