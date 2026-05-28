# Reset Notes

Use the deterministic reseed script so the environment returns to a known-good benchmark state.

Reset requirements:

- rebuild the OrangeHRM install from the official dev environment
- recreate the frontend bundle and runtime-write permissions
- restore the seeded employees and leave configuration
- clear any leave requests, employee edits, or audit entries created by prior runs

Preferred reset command:

```bash
export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock
cd /home/santosh/NeXUI
./scripts/reseed_orangehrm.sh
```

What the reseed script does:

- tears down the OrangeHRM Docker state and starts `php-8.1`, `mysql57`, and `nginx` through the repo-managed start wrapper
- temporarily patches the installer config to apply the benchmark admin account and database settings, then restores the checkout file
- rebuilds the Vue frontend bundle in `src/client`
- restores runtime-write permissions without changing tracked mode bits in the OrangeHRM checkout
- seeds the benchmark employees and leave setup documented in `seed-notes.md`

Current status:

- the reset path is runnable from this session with rootless Docker
- post-reset benchmark entities are deterministic enough for PIM, contact-details, add-employee, and apply-leave task authoring
