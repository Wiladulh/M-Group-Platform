# Progress

## P13-FIX1 — DONE (CI green on release target)

- Status: DONE; CI green on the release target SHA.
- Cleanup HEAD: acab77e (temporary workflow removed; no workflow run/status check was returned for this cleanup commit).
- Tag: v0.2.1-ws-binding @ 930d2dc (annotated).
- Tests: 218 passed.
- Coverage: 91.20%.
- Note: REFUNDED status reverted to DISPENSE_FAILED per spec §5.
  Refund is recorded as a separate `REFUND` ledger row, not a status.

## P14 — WebUI 3a (in progress)

- Baseline: spec v1.3 §14 + Decision Log #21 (single admin, no RBAC).
- Scope: auth, layout, dashboard, member, top-up, transactions.
- Deferred: Cashier/Vending/Products/Reports/Settings (P15).
- Deferred: QRIS/Xendit (post-v1.3, see docs/ASSUMPTIONS.md A-P14-03).
