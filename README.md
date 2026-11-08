# LedgerLine: money movement with a ledger you can prove

Python 3 standard library + SQLite. No dependencies. **Live URL:** `<add after deploying>`
See `THREATS.md` (threat model + tests) and `PROMPTS.md` (AI use log).

## Run locally
```
python3 test_ledgerline.py                                   # 28 tests incl. concurrency
ADMIN_TOKEN=<16+ chars> SEED_DEMO=1 python3 server.py        # API on :8000
ADMIN_TOKEN=<same> python3 demo.py                           # guided demo (second terminal)
```
Env vars: `ADMIN_TOKEN` (min 16 chars; creates the administrator, no default), `SEED_DEMO=1` (optional demo data), `PORT`, `LEDGER_DB`.

## Dashboard
Open `http://localhost:8000/` (or the live URL). Sign in with a token (or sign up as a holder) to see accounts, move money, view statements; auditors/admins also get reconcile and the audit log. It is a single static page (`index.html`) calling the same API; all data is rendered with `textContent` (no HTML injection) under a strict Content-Security-Policy.

## Roles
| Role | Can | Cannot |
|---|---|---|
| **holder** (public signup `POST /users`) | open accounts; withdraw/transfer from **own** accounts; read own balance and statement | fund accounts, see others' accounts, audit log |
| **admin** (from `ADMIN_TOKEN`) | fund accounts (deposits), create auditors/admins, read everything, reconcile | withdraw or transfer a customer's money |
| **auditor** (created by admin) | read every account, statement, audit log, reconcile | any write |

Seed data (only if `SEED_DEMO=1`): tokens `demo-alice-token` (holder, $1000.00), `demo-bob-token` (holder, $50.00), `demo-auditor-token`. These are public demo tokens, so never enable seeding on a real system.

## API (Bearer token auth; amounts are integers in minor units, e.g. cents)
| Method | Path | Who |
|---|---|---|
| POST | /users | anyone (creates a holder; token returned once) |
| POST | /admin/users `{"role":"auditor"}` | admin |
| POST | /accounts `{"currency":"USD"}` | holder/admin |
| GET | / | the dashboard (no auth) |
| GET | /me | any user: your id and role |
| GET | /accounts | own accounts (holder) or all (admin/auditor) |
| GET | /accounts/{id}, /accounts/{id}/entries | owner, admin, auditor |
| POST | /deposits `{"account_id","amount"}` | admin |
| POST | /withdrawals `{"account_id","amount"}` | account owner |
| POST | /transfers `{"from","to","amount"}` | owner of `from` |
| GET | /audit?limit=N | admin/auditor |
| GET | /reconcile | admin/auditor |

POST money endpoints **require** an `Idempotency-Key` header. Errors: 400 validation, 401 auth, 403 forbidden, 404, 409 key reuse, 422 insufficient funds.

## How it works
- **Double-entry:** every transaction writes two signed entries that sum to zero. Money enters or leaves only via a per-currency system account. Cached balances are updated in the same DB transaction.
- **No overdraft:** atomic `UPDATE ... WHERE balance >= amount`, plus a `CHECK (balance >= 0)` constraint.
- **Idempotency:** key + request hash stored per user, with `UNIQUE(user_id, idem_key)`. Same request replays the stored result; a different request under the same key gives 409.
- **Concurrency:** each money movement is one `BEGIN IMMEDIATE` transaction (writers serialised). On PostgreSQL this would be `SELECT ... FOR UPDATE` on both accounts in sorted-id order.
- **Audit trail:** `entries`, `transactions` and `audit_log` are append-only (DB triggers reject UPDATE/DELETE). Rejected attempts are logged too.
- **Proof:** `/reconcile` recomputes every balance from entries and checks that every transaction and the whole ledger sum to zero.

## Limitations (honest list)
Dashboard is basic and was only tested by hand. Tokens do not expire and there is no rate limiting. SQLite single node; free hosting resets the database on restart. No reversals, pagination, or multi-currency FX. Audit log has no hash chain.
