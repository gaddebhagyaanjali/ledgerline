# LedgerLine: money movement with a ledger you can prove

Python 3 standard library + SQLite. No dependencies. **Live URL:** `<add after deploying>`
See `THREATS.md` (threat model + tests) and `PROMPTS.md` (AI use log).

## Run locally
```
python3 test_ledgerline.py                                   # 63 tests incl. concurrency, HTTP and the bootstrap script
ADMIN_TOKEN=<16+ chars> SEED_DEMO=1 python3 server.py        # API on :8000
ADMIN_TOKEN=<same> python3 demo.py                           # guided demo (second terminal)
```
Env vars: `ADMIN_TOKEN` (min 16 chars; defines the bootstrap administrator, no default), `ONBOARDING_MODE` (`auto` default: new holders can use the system at once; `manual`: an admin must approve each signup), `SEED_DEMO=1` (optional demo data), `PORT`, `LEDGER_DB`.

**First administrator.** At start-up, if `ADMIN_TOKEN` is set, that administrator is created (or re-activated), and every *older* bootstrap administrator is disabled, so changing `ADMIN_TOKEN` really changes who can log in. You can also run `python3 bootstrap_admin.py` by hand: with `ADMIN_TOKEN` set it does the same (the token is never printed); without it, it creates the first administrator only if none exists and prints a generated token **once**.

**Onboarding.** Every user has a status: `pending` (waiting for approval, can only call `/me`), `active`, or `disabled` (token revoked at once). Admins approve, disable and re-enable users; every change is audited. An older database file is upgraded in place on start-up.

## Dashboard
Open `http://localhost:8000/` (or the live URL). Sign in with a token (or sign up as a holder) to see accounts, move money, view statements; auditors/admins also get reconcile and the audit log. It is a single static page (`index.html`) calling the same API; all data is rendered with `textContent` (no HTML injection) under a strict Content-Security-Policy.

## Roles
| Role | Can | Cannot |
|---|---|---|
| **holder** (public signup `POST /users`; needs approval first in `manual` mode) | open accounts; withdraw/transfer from **own** accounts; read own balance and statement | fund accounts, see others' accounts, audit log |
| **admin** (from `ADMIN_TOKEN`) | fund account holders' accounts (deposits), create auditors/admins, approve/disable/re-enable users, read everything, reconcile | withdraw or transfer a customer's money; open or own accounts |
| **auditor** (created by admin) | read every account, statement, audit log, reconcile | any write |

Seed data (only if `SEED_DEMO=1`): tokens `demo-alice-token` (holder, $1000.00), `demo-bob-token` (holder, $50.00), `demo-auditor-token`. These are public demo tokens, so never enable seeding on a real system.

## API (Bearer token auth; amounts are integers in minor units, e.g. cents)
| Method | Path | Who |
|---|---|---|
| POST | /users `{"display_name":"Pat"}` (name optional) | anyone: creates a holder (`active`, or `pending` in manual mode); token returned once |
| POST | /admin/users `{"role":"auditor"}` | admin: create an auditor or admin |
| GET | /admin/users?status=pending | admin: list users (never their tokens) |
| POST | /admin/users/{id}/status `{"status":"active"\|"disabled"}` | admin: approve, disable or re-enable (not yourself) |
| POST | /accounts `{"currency":"USD"}` | holder only |
| GET | / | the dashboard (no auth) |
| GET | /me | any signed-in user, even `pending`: your id, role, status, display name |
| GET | /accounts | own accounts (holder) or all (admin/auditor) |
| GET | /accounts/{id}, /accounts/{id}/entries | owner, admin, auditor |
| POST | /deposits `{"account_id","amount"}` | admin, into a holder's account only |
| POST | /withdrawals `{"account_id","amount"}` | account owner |
| POST | /transfers `{"from","to","amount"}` | owner of `from` |
| GET | /audit?limit=N | admin/auditor |
| GET | /reconcile | admin/auditor |
| GET | /health | anyone: is the process up? (200, no database check) |
| GET | /ready | anyone: 200 if the database works, 503 if not (no error details are returned) |

**Health checks:** point your host's health check at `/ready` (it fails when the database is unreachable) and use `/health` for a plain "is it running" check. Neither needs a token and neither reveals internals.

POST money endpoints **require** an `Idempotency-Key` header. Errors: 400 validation, 401 auth, 403 forbidden, 404, 409 key reuse, 422 insufficient funds.

## How it works
- **Double-entry:** every transaction writes two signed entries that sum to zero. Money enters or leaves only via a per-currency system account. Cached balances are updated in the same DB transaction.
- **No overdraft:** atomic `UPDATE ... WHERE balance >= amount`, plus a `CHECK (balance >= 0)` constraint.
- **Idempotency:** key + request hash stored per user, with `UNIQUE(user_id, idem_key)`. Same request replays the stored result; a different request under the same key gives 409.
- **Concurrency:** each money movement is one `BEGIN IMMEDIATE` transaction (writers serialised). On PostgreSQL this would be `SELECT ... FOR UPDATE` on both accounts in sorted-id order.
- **Audit trail:** `entries`, `transactions` and `audit_log` are append-only (DB triggers reject UPDATE/DELETE). Rejected attempts are logged too.
- **Proof:** `/reconcile` recomputes every balance from entries and checks that every transaction and the whole ledger sum to zero.

## Limitations (honest list)
An admin can still fund an account held by a second identity they control (deposits stand in for a payment gateway; there is no real external funding check). Dashboard is basic and was only tested by hand. Tokens do not expire and there is no rate limiting. SQLite single node; free hosting resets the database on restart. No reversals, pagination, or multi-currency FX. Audit log has no hash chain.
