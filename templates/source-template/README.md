# __SITE_NAME__

This source package tracks authoring work for `__SITE_ID__`.

## Workflow

1. Update `site.yaml` with track metadata, entry points, auth notes, and task ideas.
   Entry points may use either remote `url` targets or local `path` targets.
2. For self-hosted or benchmark sources, fill in the `runtime` section with checkout, healthcheck, bootstrap, start, and reset details.
3. Fill `bootstrap.md`, `reset-notes.md`, and `seed-notes.md` before recording stateful tasks.
4. Run `./nexui validate-source <source-package>` before survey, especially for self-hosted tracks.
5. Run `./nexui survey-source <source-package>` to capture entry-point states.
6. Review captures and expand `task_ideas`.
7. Add recording recipes under `recipes/`.
8. Use `./nexui record` to generate benchmark task packages.
