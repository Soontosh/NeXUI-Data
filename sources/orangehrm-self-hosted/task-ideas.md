# Task Ideas

Recorded tasks:

1. `orangehrm-pim-search-admin-employee-001`
2. `orangehrm-pim-open-admin-detail-001`
3. `orangehrm-add-employee-boundary-001`
4. `orangehrm-pim-search-ava-patel-001`
5. `orangehrm-pim-open-ava-detail-001`
6. `orangehrm-contact-details-open-001`
7. `orangehrm-contact-details-boundary-001`
8. `orangehrm-apply-leave-boundary-001`
9. `orangehrm-pim-search-marcus-lee-001`
10. `orangehrm-pim-open-ava-edit-boundary-001`
11. `orangehrm-add-employee-login-details-boundary-001`
12. `orangehrm-contact-details-save-verify-001`
13. `orangehrm-pim-open-marcus-edit-boundary-001`
14. `orangehrm-contact-details-save-verify-alt-email-001`
15. `orangehrm-pim-open-ava-save-verify-middle-name-001`
16. `orangehrm-apply-leave-save-verify-list-001`
17. `orangehrm-pim-save-reopen-contact-boundary-001`
18. `orangehrm-pim-save-reopen-contact-save-reverify-001`

Next queue:

1. Extend the monstrous OrangeHRM cohort beyond Ava Patel only if a second seeded employee or leave workflow can support the same two-save cross-view standard.
2. Avoid adding unstable admin or multi-user flows that do not reseed cleanly.

Authoring rules:
- keep login inside every recipe
- boundary tasks need explicit unsafe traces
- mutating tasks must set `requires_source_reset: true`
- keep OrangeHRM reseeds serialized; do not validate reset-aware tasks in parallel against the same runtime
