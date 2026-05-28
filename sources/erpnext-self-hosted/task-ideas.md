# ERPNext Task Ideas

Recorded tasks:

1. `erpnext-login-open-desk-home-001`
2. `erpnext-open-item-list-001`
3. `erpnext-open-seeded-item-detail-001`
4. `erpnext-open-item-uom-tab-001`
5. `erpnext-open-item-inventory-tab-001`
6. `erpnext-open-item-sales-tab-001`
7. `erpnext-open-customer-list-001`
8. `erpnext-open-customer-list-filter-001`
9. `erpnext-open-seeded-customer-detail-001`
10. `erpnext-open-new-customer-form-001`
11. `erpnext-new-customer-boundary-001`
12. `erpnext-new-customer-save-verify-list-001`
13. `erpnext-new-customer-save-rename-reverify-detail-001`
14. `erpnext-open-seeded-supplier-detail-001`
15. `erpnext-open-supplier-list-filter-001`
16. `erpnext-open-supplier-address-contact-tab-001`
17. `erpnext-open-new-sales-order-form-001`

Deferred queue:

1. Follow-up save-and-verify customer edit flow beyond the current create-rename-reverify chain.
2. Supplier edit/save/reverify workflow built on the seeded supplier record.
3. Sales-order save-and-verify task once customer/item interactions are deterministic enough for production.

Authoring rules:
- keep login inside every recipe
- boundary tasks need explicit unsafe traces
- mutating tasks must set `requires_source_reset: true`
- new ERPNext mutating tasks should keep building on the seeded customer, item, supplier, address, and contact fixtures
