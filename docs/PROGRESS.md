# Progress

## P13-FIX1 — DONE (CI green on release target)

- Status: DONE; CI green on the release target SHA.
- Cleanup HEAD: acab77e (temporary workflow removed; no workflow run/status check was returned for this cleanup commit).
- Tag: v0.2.1-ws-binding @ 930d2dc (annotated).
- Tests: 218 passed.
- Coverage: 91.20%.
- Note: REFUNDED status reverted to DISPENSE_FAILED per spec §5.
  Refund is recorded as a separate `REFUND` ledger row, not a status.

## P13-FIX2 — DONE (merged)

- Status: DONE. PR #2 merged to `main`.
- Merge commit: 70202b6
- Tests: 221 passed
- Coverage: 91.20%
- Change: `cli.py` `BALANCE_STATUSES` no longer contains stale `REFUNDED`
  (refunds are separate REFUND ledger rows per spec §5).
- Add: regression test `test_cli_balance_statuses.py` (minimal guard;
  root cause of prior `I001` failures resolved by structure alignment,
  specific trigger not identified — see technical debt below).
- Technical debt: `I001` failures on the initial test file structure
  (multiline docstring + single import) were resolved by aligning the
  structure with `test_cli_seed.py`/`test_ledger.py` (single-line docstring
  + multi-import). Specific Ruff 0.17.4 trigger not confirmed due to lack
  of `ruff check --diff` in CI. Revisit in P15 with local `ruff` access.

## P14 — WebUI 3a (in progress)

- Baseline: spec v1.3 §14 + Decision Log #21 (single admin, no RBAC).
- Scope: auth, layout, dashboard, member, top-up, transactions.
- Deferred: Cashier/Vending/Products/Reports/Settings (P15).
- Deferred: QRIS/Xendit (post-v1.3, see docs/ASSUMPTIONS.md A-P14-03).

## P14-a — Frontend Foundation — DONE

- Status: DONE. Semua checkpoint (CP1-CP5) selesai.
- Branch: p14-a-cp1, merge commit 0a90ddc, HEAD 02eef762.
- Tests: 224 passed (221 baseline + 3 smoke test).
- Coverage: 91.11% (turun 0.09% dari 91.20% baseline; bukan regresi fungsional, hanya penambahan file test).
- Ruff: clean (check + format).
- Tailwind: v3.4.17 standalone CLI, pinned, tanpa CDN/Node. Build via temporary workflow.
- Files: pyproject.toml (+jinja2), .gitignore (+binary), tailwind.config.js, input.css, app.css, app.js, base.html, main.py (mount static + Jinja2Templates + endpoint /), test_web.py.
- Smoke tests: test_home_page, test_static_css, test_static_js.
- Technical debt I001: tetap. Revisit P15.
- Warning pre-existing (catat untuk P15):
  - pytest-asyncio loop scope belum ditetapkan.
  - Starlette httpx deprecation warning di testclient.
- Out of scope P14-a (deferred): auth, dashboard, member, topup, transactions, RBAC, QRIS/Xendit, vendor libraries (HTMX/Alpine/Chart.js).
