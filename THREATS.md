# THREATS.md: what could go wrong with LedgerLine, and what stops it

Each threat names the attack, the defence, and the test that proves it.

| # | Threat | Defence | Test (test_ledgerline.py) |
|---|---|---|---|
| 1 | **Replay / double-click / network retry** pays twice | Mandatory `Idempotency-Key`, per user, stored with a hash of the request; `UNIQUE(user_id, idem_key)` in the DB | `test_idempotent_replay_returns_same_result_once` |
| 2 | **Same key reused for a different request** to smuggle a changed amount | Request hash mismatch returns 409 | `test_key_reuse_with_different_payload_rejected` |
| 3 | **Concurrent duplicates** (20 parallel identical requests) | Writers serialised with `BEGIN IMMEDIATE`; key looked up inside the same transaction | `test_concurrent_duplicate_requests_pay_once` |
| 4 | **Double-spend race**: many parallel withdrawals of the same balance | Atomic conditional `UPDATE ... WHERE balance >= amount`; `CHECK(balance>=0)` as backstop | `test_concurrent_withdrawals_cannot_double_spend` |
| 5 | **Overdraft / negative amounts / zero / floats / strings / booleans** | Server-side validation: positive int only; DB CHECK on balance and entry amount | `test_overdraft_and_bad_amounts_rejected` |
| 6 | **Integer overflow / absurd amounts** (e.g. 2^70) | `MAX_AMOUNT` cap, so oversized values give 400, never a 500 | `test_amount_cap_and_huge_ints` |
| 7 | **Moving someone else's money / reading their data** (IDOR) | Ownership check on every debit and every read; unknown or foreign accounts are refused | `test_cannot_move_money_from_someone_elses_account` |
| 8 | **Missing / forged token** | Bearer token to user via stored SHA-256 hash; 401 otherwise. Tokens are 256-bit random | `test_bad_token_and_unknown_role` |
| 9 | **Privilege escalation** (holder becomes admin/auditor, self-funds, reads audit log) | Roles in DB; public signup only makes holders; only admins create staff; deposits admin-only; oversight reads need admin/auditor; admin `ADMIN_TOKEN` has no default and must be 16+ chars | `test_holders_cannot_print_money`, `test_holders_cannot_see_audit_log_or_reconcile_or_make_staff`, `test_admin_can_fund_but_never_withdraw_or_transfer_customer_money` |
| 9b | **Auditor tampering** | Auditors are read-only for every write path | `test_auditor_is_read_only_but_sees_everything` |
| 9c | **Opposing concurrent transfers** (lost updates, money created/destroyed) | Serialised writes; conservation checked | `test_concurrent_opposite_transfers_conserve_money` |
| 10 | **Partial failure** (debit without credit) | One DB transaction: debit, credit, entries, idempotency record commit or roll back together | `test_failed_transfer_leaves_no_partial_state` |
| 11 | **Cross-currency transfer** (value created by mixing currencies) | Currency must match on both accounts | `test_currency_mismatch_and_self_transfer` |
| 12 | **Self-transfer** tricks | Rejected | same test |
| 13 | **Ledger tampering** (edit/delete history, cached balance forgery) | Triggers block UPDATE/DELETE on entries, transactions, audit log; `reconcile()` recomputes balances from entries | `test_ledger_is_immutable_and_tampering_detected` |
| 14 | **Attacks leave no trace** (token guessing, probing other people's accounts, trying admin pages) | Every refused request is written to the append-only audit log: failed money movements, failed logins (a short hash prefix of the guess, never the token itself), denied account/statement reads, denied audit-log and reconcile access, denied staff or account creation. Successful reads are deliberately not logged, to keep the log useful | `test_rejected_attempts_are_audited`, `test_failed_login_is_audited_without_storing_the_token`, `test_denied_and_missing_account_reads_are_audited`, `test_denied_statement_read_is_audited`, `test_holder_denied_oversight_is_audited`, `test_denied_staff_creation_and_auditor_account_creation_are_audited`, `test_successful_reads_do_not_flood_the_audit_log` |
| 15 | **Malformed / oversized / non-object JSON** crashing the server | 16 KB body cap, JSON must be an object, generic 500 hides internals | verified manually (400 responses) |
| 16 | **Money creation from nothing** | Only the system account may go negative; every entry set sums to zero; global sum checked by `reconcile()` | `test_basic_flow_balances` |

| 17 | **XSS via account data in the dashboard** | All dynamic values rendered with `textContent`; CSP allows only the page's own script (hash) and same-origin requests; `nosniff`; token kept in sessionStorage | manual review (no automated browser test) |

## Known gaps (not defended; stated honestly)
- **Deposits are an admin action** standing in for a payment gateway; there is no real external funding source or confirmation.
- **Demo tokens** (`SEED_DEMO=1`) are public by design; seeding must stay off in anything real.
- **No rate limiting**, so a client could flood the API. It can also grow the audit log by sending many bad requests, because refused requests are now recorded. Mitigation: per-client request limits (not built yet).
- **Tokens never expire** and are not rotated; there is no TLS inside the app (Render terminates HTTPS in front of it).
- **Dashboard has no automated browser tests**; the token lives in sessionStorage, so an XSS bug would expose it (mitigated by the CSP above).
- **Account IDs reveal existence** (404 vs success when sending to an unknown id).
- **Single-node SQLite**: fine for the assignment; production would use PostgreSQL with row locks.
- **Free hosting resets the database** on restart.
