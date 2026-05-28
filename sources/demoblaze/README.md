# Demoblaze Store

This source package tracks authoring work for `demoblaze`.

Demoblaze adds a lightweight retail storefront to the benchmark. It is useful for category browsing, product navigation, cart state changes, and bounded stop-before-purchase tasks.

## Source Focus

- Category navigation
- Product detail navigation
- Cart verification
- Stop-before-purchase flows
- Modal interaction from a retail storefront

## Workflow

1. Validate the source with `./nexui validate-source sources/demoblaze --check-remote`.
2. Survey the home and cart entry points with `./nexui survey-source sources/demoblaze --overwrite`.
3. Review the captured candidates under `captures/`.
4. Promote the strongest task ideas into recipes under `recipes/`.
5. Use `./nexui record` to generate benchmark task packages.
