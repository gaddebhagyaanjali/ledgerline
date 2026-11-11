# LedgerLine – Money Movement with a Verifiable Ledger

LedgerLine is a lightweight ledger-based money movement application built with Python and SQLite. It demonstrates secure account management, role-based access control, double-entry bookkeeping, transaction integrity, audit logging, and reconciliation.

> **Important:** This is an educational demonstration project. It is not a production banking system or a real-money payment service.

## Technology Stack

- **Backend:** Python 3 standard library
- **Database:** SQLite
- **Frontend:** HTML, CSS, JavaScript
- **Containerization:** Docker
- **Testing:** Python unittest

The application uses Python's standard library and SQLite. No third-party Python dependencies are required.

## Features

- User registration and account management
- Role-based access control for holders, administrators, and auditors
- Administrator approval and user status management
- Double-entry ledger accounting
- Deposits, withdrawals, and transfers
- Idempotency protection for money movement requests
- Prevention of overdrafts
- Append-only transaction and audit records
- Account balance reconciliation
- Health and readiness endpoints
- Docker container with a non-root application user
- Persistent SQLite database storage through a Docker volume

## Project Structure

```text
ledgerline/
├── ledger.py
├── server.py
├── index.html
├── bootstrap_admin.py
├── demo.py
├── test_ledgerline.py
├── Dockerfile
├── README.md
├── THREATS.md
└── PROMPTS.md
```

## Run Locally

### 1. Run the test suite

```bash
python3 test_ledgerline.py
```

### 2. Start the application

Set an administrator token containing at least 16 characters:

```bash
export ADMIN_TOKEN="your-private-admin-token"
export SEED_DEMO=1
python3 server.py
```

The API and dashboard will be available at:

`http://localhost:8000`

### 3. Run the guided demo

Open another terminal in the project directory:

```bash
ADMIN_TOKEN="your-private-admin-token" python3 demo.py
```

Use synthetic demo data only. Demo tokens must never be enabled on a real system.

## Run with Docker

### 1. Build the Docker image

```bash
docker build -t ledgerline-final .
```

### 2. Create a persistent database volume

```bash
docker volume create ledgerline-data
```

### 3. Generate an administrator token

```bash
export ADMIN_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Keep this token private. Do not commit it to GitHub or share it in screenshots.

### 4. Bootstrap the administrator

```bash
docker run --rm \
  -e ADMIN_TOKEN="$ADMIN_TOKEN" \
  -e LEDGER_DB=/data/ledgerline.db \
  -v ledgerline-data:/data \
  ledgerline-final python bootstrap_admin.py
```

### 5. Start the application

```bash
docker run -d \
  --name ledgerline-test \
  -p 8001:8000 \
  -e ONBOARDING_MODE=manual \
  -v ledgerline-data:/data \
  ledgerline-final
```

Open the dashboard:

`http://localhost:8001`

Sign in using the administrator token generated earlier.

The Docker volume keeps the SQLite database separate from the container's writable filesystem, so the data can persist when the container is replaced, provided the volume is retained.

### 6. Verify application health

Check whether the application is running:

```bash
curl -i http://localhost:8001/health
```

Check whether the application and database are ready:

```bash
curl -i http://localhost:8001/ready
```

Inspect Docker health status:

```bash
docker inspect --format='{{.State.Health.Status}}' ledgerline-test
```

Expected responses:

- `/health`: HTTP 200
- `/ready`: HTTP 200 when the database is available
- Docker health status: `healthy`

## Configuration

| Environment variable | Description |
|---|---|
| `ADMIN_TOKEN` | Administrator bootstrap token; minimum 16 characters |
| `ONBOARDING_MODE` | `auto` or `manual`; defaults to `auto` |
| `SEED_DEMO` | Set to `1` to load synthetic demo data |
| `PORT` | HTTP server port; defaults to `8000` |
| `LEDGER_DB` | SQLite database path |

## User Roles and Permissions

| Role | Permissions |
|---|---|
| **Holder** | Open accounts, view own balances and statements, withdraw and transfer from own accounts |
| **Administrator** | Manage users, approve or disable accounts, fund holder accounts, view records and reconcile |
| **Auditor** | Read all accounts, statements and audit records; run reconciliation |

Administrators and auditors cannot withdraw or transfer customer funds through the holder money movement endpoints.

## API Overview

All authenticated requests use Bearer token authentication.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/users` | Register a holder |
| POST | `/admin/users` | Create an administrator or auditor |
| GET | `/admin/users?status=pending` | List pending users |
| POST | `/admin/users/{id}/status` | Change user status |
| POST | `/accounts` | Open an account |
| GET | `/accounts` | List permitted accounts |
| GET | `/accounts/{id}` | View account details |
| GET | `/accounts/{id}/entries` | View account ledger entries |
| POST | `/deposits` | Deposit funds |
| POST | `/withdrawals` | Withdraw funds |
| POST | `/transfers` | Transfer funds |
| GET | `/audit` | View audit records |
| GET | `/reconcile` | Reconcile ledger balances |
| GET | `/health` | Check process health |
| GET | `/ready` | Check application and database readiness |

Money movement requests require an `Idempotency-Key` header.

Amounts are represented as integer minor units, such as cents, to avoid floating-point rounding errors.

## Accounting and Security Design

### Double-entry accounting

Each transaction generates two signed ledger entries whose sum is zero. Money enters or leaves through a per-currency system account.

### Overdraft prevention

Balance updates use conditional SQL updates and database constraints to prevent accounts from becoming negative.

### Idempotency

Money movement requests use an idempotency key and request hash. Repeating the same request returns its stored result, while reusing a key for a different request is rejected.

### Transaction concurrency

Money movement operations use SQLite `BEGIN IMMEDIATE` transactions to serialize database writers.

### Audit trail

Ledger entries, transactions, and audit records are protected against updates and deletions through database triggers. Rejected attempts are also logged.

### Reconciliation

The reconciliation endpoint recomputes account balances from ledger entries and checks transaction and ledger balancing.

### Administrator bootstrap

Administrator bootstrap supports token-based creation and rotation. Older bootstrap administrators are disabled when a new administrator token is established.

### Application security

The application includes role-based authorization, bearer-token authentication, input validation, and a Content Security Policy with a hash-pinned script. Inline styles are permitted by the current policy.

## Testing

Run:

```bash
python3 test_ledgerline.py
```

The test suite currently contains **63 tests**, covering:

- Ledger and transaction correctness
- Authentication and authorization
- Idempotency
- Concurrent money movements
- HTTP API behavior
- Administrator bootstrap
- Reconciliation

## Limitations and Future Improvements

LedgerLine is a demonstration implementation and has known limitations:

- SQLite is intended for a single-node deployment in this implementation.
- No external payment gateway or independent funding verification is integrated.
- Administrator deposits are not backed by real payment verification.
- Authentication tokens do not currently expire.
- Rate limiting is not implemented.
- The application does not implement transaction reversals, pagination, or foreign-exchange conversion.
- The audit log does not use a cryptographic hash chain.
- The dashboard has received manual testing; automated browser testing is not included.
- Persistent storage must be configured by the deployment host. Temporary or ephemeral hosting storage can result in data loss.

## Project Documentation

- `THREATS.md` – Threat model, security considerations, and related tests.
- `PROMPTS.md` – AI assistance and development activity log.

## Disclaimer

LedgerLine is developed for learning, demonstration, and software engineering assessment purposes. Use synthetic data only. It is not intended to process real customer funds or replace a regulated financial system.