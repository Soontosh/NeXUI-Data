# WebArena Verified Shopping Admin

This source package tracks authoring work for the official WebArena Verified `shopping_admin` environment.

## Workflow

1. Start the official container with rootless Docker and expose ports `7780` and `7781`.
2. Run `./nexui validate-source sources/webarena-verified-shopping-admin --check-remote`.
3. Run `./nexui survey-source sources/webarena-verified-shopping-admin --overwrite`.
4. Review the authenticated dashboard and admin-grid captures.
5. Expand `task_ideas` and add recorder recipes under `recipes/`.

Survey relies on the documented Magento admin auto-login header so captures reach authenticated admin pages deterministically without brittle UI-login setup.
