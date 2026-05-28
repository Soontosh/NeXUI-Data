# ERPNext Self-Hosted

Milestone B intake package for the first ERPNext enterprise-workflow source.

Planned authoring approach:
- use the official `frappe_docker` checkout
- bind the local ERPNext UI to `http://localhost:8090/`
- create a deterministic `nexui.localhost` site
- seed one administrator account plus a small fixed business dataset

This package is intentionally repo-side only until the local runtime is reachable and surveyable.
