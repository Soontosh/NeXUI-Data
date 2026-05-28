# Accessible University Demo Site

This source package tracks authoring work for `accessible-university`.

Accessible University is a public accessibility-demo site maintained by AccessComputing at the University of Washington. It provides stable `Before`, `After`, and `Info` pages that are well-suited for explanation-heavy navigation and before/after accessibility comparisons.

## Source Focus

- Accessibility-first navigation tasks
- Before/after page discrimination
- Screen-reader-oriented structure explanations
- Form and link-understanding tasks grounded in accessibility issues

## Workflow

1. Update `site.yaml` with track metadata, entry points, auth notes, and task ideas.
   Entry points may use either remote `url` targets or local `path` targets.
2. Validate the source with `./nexui validate-source sources/accessible-university --check-remote`.
3. Survey the overview, before, after, and info entry points with `./nexui survey-source sources/accessible-university --overwrite`.
4. Review the captured candidates, accessibility-tree structure, and reader views under `captures/`.
5. Promote the strongest task ideas into recipes under `recipes/`.
6. Use `./nexui record` to generate benchmark task packages.
