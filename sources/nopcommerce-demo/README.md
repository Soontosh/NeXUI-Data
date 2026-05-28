# nopCommerce Demo Store

This source package tracks authoring work for `nopcommerce-demo`.

nopCommerce adds a retail/e-commerce UI style to the benchmark. It is useful for search, category navigation, cart flows, configurable products, and stop-before-checkout tasks.

## Source Focus

- Product search and result verification
- Category browsing
- Configurable product pages
- Cart review and checkout-boundary tasks
- Wishlist and compare-list state changes

## Workflow

1. Validate the source with `./nexui validate-source sources/nopcommerce-demo`.
2. Survey the home, search, cart, and configurable product entry points with `./nexui survey-source sources/nopcommerce-demo --overwrite`.
3. Review the captured candidates and state metadata under `captures/`.
4. Promote the best task ideas into recipes under `recipes/`.
5. Use `./nexui record` to generate benchmark task packages.

## Notes

- The official nopCommerce demo page states that the frontend and backend demos are not interconnected.
- That same official page states the demo is reset to its original state every hour.
- Some pages appear to reject `HEAD` requests, so survey/capture is the most reliable intake check.
