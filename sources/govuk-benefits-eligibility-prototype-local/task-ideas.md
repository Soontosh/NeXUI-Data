# Task Ideas

Validated tasks:

- `govuk-benefits-guidance-review-001`: choose the `Not working` route, verify the inset guidance, and continue to check answers.
- `govuk-benefits-change-updates-add-email-001`: reach check answers on the no-email branch, change the updates answer to `Yes`, and verify the email row appears.
- `govuk-benefits-change-updates-remove-email-001`: reach check answers on the email branch, change the updates answer to `No`, and verify the email row disappears.
- `govuk-benefits-income-validation-recovery-001`: trigger the monthly-income validation error, recover, and stop on the corrected check-answers page.
- `govuk-benefits-multi-edit-check-answers-001`: make two summary edits and verify both propagate to the final review state.
- `govuk-benefits-result-boundary-001`: reach check answers and ask for confirmation before continuing to the eligibility result.
- `govuk-benefits-employed-result-001`: follow an employed route through check answers and stop on the positive eligibility result page.
- `govuk-benefits-change-children-from-summary-001`: change the childcare-count answer from the summary and verify the updated review state preserves later answers.
- `govuk-benefits-not-working-result-001`: follow a not-working route through check answers and stop on the extra-checks eligibility result page.
- `govuk-benefits-invalid-email-format-recovery-001`: trigger the invalid-email-format validation error, recover, and stop on the corrected check-answers page.
- `govuk-benefits-self-employed-result-001`: follow a self-employed route and stop on check answers with the route details visible in the final summary.
- `govuk-benefits-employed-change-updates-result-001`: take the employed route, add email updates from check answers, and continue to the result page.
- `govuk-benefits-double-validation-branch-flip-email-readd-boundary-001`: recover from income and email validation errors, flip the route from Employed to Not working, change children, remove and re-add the email branch, and stop with `ask_user` before continuing to the eligibility result.

Next candidates:

- Reach the result page on different work-status branches and verify the final result wording changes appropriately.
- Extend the monstrous benefits cohort with a true result-page follow-through that starts from a mutated review state and verifies the final wording on the alternate branch.
