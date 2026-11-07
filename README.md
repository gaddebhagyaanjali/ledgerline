# LedgerLine: money movement with a ledger you can prove

A small payments backend (Python 3 stdlib + SQLite, zero dependencies) where every transaction is
**accurate, authorised, traceable and recorded in a reliable ledger**.

## Run
```
python test_ledgerline.py        # 12 tests incl. concurrency
python server.py                 # API on :8000  (ADMIN_KEY env for /reconcile, default "admin")
```

## API
| Method | Path | Notes |
|---|---|---|
| POST | /users | returns `user_id` + bearer `token` (shown once, only its hash is stored) |
| POST | /accounts | `{"currency":"USD"}` |
| POST | /deposits | `{"account_id","amount"}` + `Idempotency-Key` header |
| POST | /withdrawals | `{"account_id","amount"}` + `Idempotency-Key` |
| POST | /transfers | `{"from","to","amount"}` + `Idempotency-Key` |
| GET | /accounts/{id} , /accounts/{id}/entries | owner only (balance / statement) |
| GET | /reconcile | admin: proves the books balance |

Amounts are **integers in minor units** (cents). Floats are rejected, so there is no rounding error.

Example:
```
curl -XPOST localhost:8000/users                         # -> token
curl -XPOST localhost:8000/accounts -H "Authorization: Bearer $T" -d '{"currency":"USD"}'
curl -XPOST localhost:8000/deposits -H "Authorization: Bearer $T" -H "Idempotency-Key: dep-001" \
     -d '{"account_id":"<id>","amount":10000}'            # run twice: second reply has "replayed":true
```

## How each problem is solved
| Risk | Defence | Where |
|---|---|---|
| **Duplicate requests** | Mandatory `Idempotency-Key`, scoped per user, stored with a hash of the request. Same key + same request returns the original result (`replayed:true`); same key + different request returns 409. `UNIQUE(user_id, idem_key)` backs it at DB level. | `_post_tx`, schema |
| **Simultaneous withdrawals** | Each transfer runs in one `BEGIN IMMEDIATE` transaction (writers serialised) and debits with an atomic conditional `UPDATE ... WHERE balance >= amount`. A `CHECK(balance>=0)` is the last line of defence. 15 threads withdrawing the full balance, so exactly 1 succeeds. | `_post_tx` |
| **Unauthorised transactions** | Bearer token to user; caller must own the debited account (or the credited one for deposits). Ownership checked on reads too. Currency mismatch, self-transfer and bad amounts rejected. | `_post_tx`, `_owned` |
| **Incorrect balances** | Double-entry: every transaction writes two signed entries summing to zero; money enters/leaves only via per-currency system accounts. Cached `balance` updated in the same DB transaction as the entries. `reconcile()` re-derives every balance from entries and checks the global sum is 0, so tampering is detected. | `reconcile` |
| **Traceability** | `entries` and `transactions` and `audit_log` are append-only (DB triggers abort UPDATE/DELETE). Audit log records successes and *rejected* attempts (who, what, key, why). Statements list every entry. | schema, `_audit` |
| **Partial failure** | All-or-nothing: any error rolls back debit, credit, entries and idempotency record together. Failed requests are not cached, so clients can safely retry. | `_post_tx` |

## Design decisions & trade-offs
- **SQLite for portability.** Its single-writer lock gives serialisation for free. On PostgreSQL the same
  guarantees come from `SELECT ... FOR UPDATE` on both accounts **locked in sorted id order** (avoids
  deadlocks) at `READ COMMITTED`, or `SERIALIZABLE` with retry. The schema and logic carry over unchanged.
- **Cached balance + entries** (rather than only SUM) for O(1) reads, with reconciliation as the proof.
- **No reversals yet:** corrections would be new compensating transactions, never edits.

## Known limitations / future work
Token auth is demo-grade (add expiry/rotation, TLS, rate limiting); no pagination; idempotency records never
expire (add TTL); audit-log hash chaining would make tampering by a DB admin evident; reversals/refunds,
multi-currency FX, and metrics are not implemented.
