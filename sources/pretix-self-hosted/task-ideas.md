# Task Ideas

Planned first batch:

1. `pretix-login-open-organizer-dashboard-001` recorded
2. `pretix-open-events-list-001` recorded
3. `pretix-open-seeded-event-detail-001` recorded
4. `pretix-open-product-list-001` recorded
5. `pretix-open-add-product-form-001` recorded
6. `pretix-open-seeded-product-detail-001` recorded
7. `pretix-open-product-price-tab-001` recorded
8. `pretix-open-product-availability-tab-001` recorded
9. `pretix-add-product-boundary-001` recorded
10. `pretix-product-original-price-boundary-001` recorded
11. `pretix-product-name-boundary-001` recorded
12. `pretix-product-max-per-order-boundary-001` recorded
13. `pretix-create-product-save-verify-list-001` recorded
14. `pretix-product-name-save-verify-list-001` recorded
15. `pretix-product-original-price-save-verify-001` recorded
16. `pretix-product-max-per-order-save-verify-001` recorded
17. `pretix-product-default-price-save-verify-list-001` recorded
18. `pretix-event-contact-email-save-verify-001` recorded
19. `pretix-product-multi-tab-save-list-open-verify-001` recorded
20. `pretix-open-orders-or-attendees-list-001` deferred: current `/orders/` route returns `Internal Server Error`

Authoring rules:
- keep login inside every first-batch recipe
- boundary tasks need explicit unsafe traces
- mutating tasks should use `requires_source_reset: true`
- the organizer, event, and product fixtures are now deterministic through `./scripts/reseed_pretix.sh`
- the product surface is now the stable mutable Pretix domain, including the seeded General, Price, and Availability tabs
- the seeded event settings surface now also supports a stable reseed-aware contact-email mutation
- the monstrous Pretix cohort now starts with a multi-tab product mutation that saves once, verifies from the list, and reopens the product for tab-level re-verification
