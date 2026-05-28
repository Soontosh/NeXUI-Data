# Seed Notes

Prepared benchmark admin defaults:

- username: `nexui_admin`
- password: `NExUIAdmin!2026`
- organization: `NExUI Benchmark Lab`
- employee id: `0001`
- employee display name: `NExUI Admin`

Deterministic seeded entities:

- employee `Ava Patel`, employee id `0002`
- employee `Marcus Lee`, employee id `0003`
- leave type `Annual Leave`
- benchmark admin Annual Leave balance: `10.00 Day(s)`

Current recording notes:

- the seeded admin can access the dashboard, PIM, My Info, and Leave routes after login
- the direct personal-details route is `http://localhost:8080/web/index.php/pim/viewPersonalDetails/empNumber/1`
- the direct contact-details route is `http://localhost:8080/web/index.php/pim/contactDetails/empNumber/1`
- the direct apply-leave route is `http://localhost:8080/web/index.php/leave/applyLeave`
- the add-employee form now pre-fills the next employee id after the reseeded employee set, so do not hardcode `0002` there
- `Apply Leave` is now suitable for a confirmation-boundary task because the reseed path restores `Annual Leave` and the admin balance

Keep this file aligned with the reset workflow so named entities remain stable.
