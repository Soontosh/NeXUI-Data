# Bootstrap

Goal: prepare a local pretix control panel on `http://localhost:8100/` with one seeded organizer, one seeded event, and one seeded ticket product.

Recommended upstream path:
1. Clone the official repository:
   - `git clone https://github.com/pretix/pretix external/pretix`
2. Review the official self-hosting and Docker small-scale docs.
3. Use rootless Docker:
   - `export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock`
4. Pull the official standalone image:
   - `docker pull pretix/standalone:stable`
5. Use the repo-managed reseed flow:
   - `./scripts/reseed_pretix.sh`

Notes:
- The reseed script removes the named Pretix volumes, recreates the standalone container, waits for `/control/login`, logs in as the default standalone admin account, enables admin mode, creates the seeded organizer/event, and saves a single seeded `General Admission` product.
- The control UI is now reachable on `localhost:8100`, but the source should stay below `validated` until the first recorder-backed task batch confirms the auth-gated control surfaces are stable.
