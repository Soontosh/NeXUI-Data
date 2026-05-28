# Reset Notes

## Shared Demo State

- The official nopCommerce demo page states the demo is reset to its original state every hour.
- The frontend is a shared live demo, so other users may have changed cart, wishlist, or compare-list state since the last reset.

## Practical Reset Guidance

- Prefer recording tasks from stable entry points such as home, search, category, product, and cart pages.
- For cart or wishlist tasks, start from a fresh page load and verify the current state before recording.
- If state looks contaminated, wait for the next hourly reset or choose a different task window.

## Commands

```bash
# No local reset command exists for the public demo.
```
