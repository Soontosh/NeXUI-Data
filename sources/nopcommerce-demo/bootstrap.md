# Bootstrap

nopCommerce is a public live demo and does not require local application setup for intake.

## Base URL

`https://demo.nopcommerce.com/`

## Official Demo Notes

The official nopCommerce demo page says:

- the frontend and backend demos are not interconnected
- the site is reset to its original state every hour

## Commands

```bash
./nexui validate-source sources/nopcommerce-demo
./nexui survey-source sources/nopcommerce-demo --overwrite
```

## Notes

- No authentication is required for browsing-oriented tasks.
- Avoid relying on persistent cart or wishlist state across long authoring sessions because the public demo is shared and periodically reset.
