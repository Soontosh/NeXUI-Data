# Demo Videos

This directory contains a curated set of oracle replay videos grouped by difficulty tier.

Each video is an `.mp4` exported from an existing benchmark task replay and is intended to provide a quick visual sample of the benchmark without requiring the full runtime setup.

## Tiers

### Easy

- `easy/accessible-university-open-info-001.mp4`
- `easy/demoblaze-open-laptops-category-001.mp4`
- `easy/parabank-register-open-001.mp4`
- `easy/w3c-bad-after-home-001.mp4`

### Medium

- `medium/cypress-rwa-login-open-personal-feed-001.mp4`
- `medium/demoqa-practice-form-submit-modal-001.mp4`
- `medium/govuk-service-validation-recovery-001.mp4`
- `medium/parabank-account-history-001.mp4`

### Hard

- `hard/cypress-rwa-open-darrel-contact-step-001.mp4`
- `hard/erpnext-open-customer-list-filter-001.mp4`
- `hard/pretix-open-seeded-product-detail-001.mp4`
- `hard/webarena-map-search-cmu-from-home-001.mp4`

### Very Hard

- `very_hard/cypress-rwa-bank-account-create-save-verify-list-001.mp4`
- `very_hard/erpnext-new-customer-save-verify-list-001.mp4`
- `very_hard/gitlab-create-issue-save-verify-detail-001.mp4`
- `very_hard/govuk-service-double-validation-to-summary-001.mp4`

### Monstrous

`Monstrous` is the internal top-end cohort inside `very_hard`, used for the longest-horizon and most demanding tasks in the benchmark.

- `monstrous/cypress-rwa-request-submit-reopen-comment-reverify-detail-001.mp4`
- `monstrous/erpnext-new-customer-save-rename-reverify-detail-001.mp4`
- `monstrous/gitlab-create-issue-list-reopen-edit-save-verify-001.mp4`
- `monstrous/orangehrm-pim-save-reopen-contact-save-reverify-001.mp4`

## Regeneration

The source replay exports live under the local `videos/` directory. If you need to regenerate one of these demos, use:

```bash
./nexui replay traces/<task-id>-oracle.json --task examples/tasks/<task-id> --video demos/<tier>/<task-id>.mp4
```
