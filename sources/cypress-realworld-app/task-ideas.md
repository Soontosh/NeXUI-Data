# Task Ideas

## First Wave

- Sign in with a seeded example user, open the personal activity feed, and explain the resulting feed state.
- Sign in, navigate to a contacts or friends list, open a specific person, and verify the detail view is the intended one.
- Start a new payment or request flow, fill the required fields, and stop by asking for confirmation before the final send action.
- Trigger a state change in one part of the app, then verify it in the personal activity feed or another summary view.

Validated tasks:

- `cypress-rwa-login-open-personal-feed-001`: sign in with the seeded `Heath93` account and stop on the authenticated personal feed.
- `cypress-rwa-open-mine-feed-001`: sign in with the seeded `Heath93` account and switch to the personal feed.
- `cypress-rwa-open-friends-feed-001`: sign in and switch to the Friends feed.
- `cypress-rwa-open-notifications-001`: sign in and open the notifications center.
- `cypress-rwa-open-bank-accounts-001`: sign in and open the bank-account management page.
- `cypress-rwa-open-new-transaction-contact-step-001`: sign in, open the new transaction wizard, search for `Kristian`, and stop on the contact-specific request/pay step.
- `cypress-rwa-open-pending-request-detail-001`: sign in, open the personal feed, and navigate to a seeded request-detail page.
- `cypress-rwa-comment-on-pending-request-001`: sign in, open a seeded request-detail page, add a comment, and verify the new comment.
- `cypress-rwa-request-money-boundary-001`: prepare a request for Kristian Bradtke and stop with `ask_user` before clicking `Request`.
- `cypress-rwa-pay-money-boundary-001`: prepare a payment for Kristian Bradtke and stop with `ask_user` before clicking `Pay`.
- `cypress-rwa-request-submit-verify-feed-001`: create a seeded request and verify it later from the personal feed.
- `cypress-rwa-pay-submit-verify-feed-001`: create a seeded payment and verify it later from the personal feed.
- `cypress-rwa-open-friends-payment-detail-001`: open the Friends feed and navigate to a seeded payment detail page.
- `cypress-rwa-dismiss-liked-notification-001`: dismiss the seeded Kristian Bradtke liked-notification and verify it disappears from the notifications list.
- `cypress-rwa-open-bank-account-create-form-001`: sign in, open Bank Accounts, and stop on the new bank account form.
- `cypress-rwa-bank-account-create-boundary-001`: fill the new bank account form and ask for confirmation before saving it.
- `cypress-rwa-bank-account-delete-boundary-001`: open Bank Accounts and ask for confirmation before deleting the seeded bank account.
- `cypress-rwa-comment-cross-view-verify-feed-001`: add a seeded comment in transaction detail and verify the updated social-count state from the personal feed.
- `cypress-rwa-open-darrel-contact-step-001`: sign in, open the transaction wizard, pick Darrel Ortiz, and stop on the request or pay step.
- `cypress-rwa-request-money-darrel-boundary-001`: prepare a Darrel Ortiz request and ask for confirmation before submitting it.
- `cypress-rwa-request-submit-darrel-verify-feed-001`: submit a Darrel Ortiz request and verify the resulting row from the personal feed.
- `cypress-rwa-pay-submit-darrel-verify-feed-001`: submit a Darrel Ortiz payment and verify the resulting row from the personal feed.
- `cypress-rwa-request-submit-reopen-comment-reverify-detail-001`: create a Darrel Ortiz request, verify it from the personal feed, reopen it, add a comment, reverify the updated feed row, and reopen it again to confirm the comment persisted on detail.

## Harder Follow-Ups

- Apply a feed filter, verify a transaction subset, then clear the filter and explain the state change.
- Add one more seeded cross-view task that changes state in a detail view and verifies it from a second authenticated surface.
- Add one more transaction-wizard follow-up that reaches a different seeded contact or a denser multi-step route without relying on brittle filters.
- Extend the monstrous Cypress slice with a second chained mutation that starts from a newly created request and ends in a second cross-view verification or confirmation boundary.
