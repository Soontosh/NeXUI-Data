# pretix Self-Hosted

Research-grade source package for self-hosting `pretix` as a deterministic modern authenticated app source.

Current status:
- `authoring_status: validated`
- local standalone runtime is reachable on `http://localhost:8100/`
- deterministic reseed hook: `./scripts/reseed_pretix.sh`
- deterministic login: `admin@localhost / admin`
- 5 production tasks are recorded and validated

Planned role in the benchmark:
- organizer and event administration workflows
- product configuration
- orders or attendees views
- hard and very-hard authenticated event-management tasks

Primary upstream references:
- official self-hosting docs: https://docs.pretix.eu/self-hosting/
- official Docker small-scale docs: https://docs.pretix.eu/self-hosting/installation/docker_smallscale/
- official repository: https://github.com/pretix/pretix
