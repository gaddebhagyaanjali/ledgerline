"""LedgerLine core: double-entry ledger with idempotency, authorisation and audit trail."""
import contextlib, hashlib, json, secrets, sqlite3, time, uuid

class LedgerError(Exception):
    status, code = 400, "bad_request"
    def __init__(self, msg=""):
        super().__init__(msg or self.code)
class ValidationError(LedgerError):   status, code = 400, "validation_error"
class Unauthenticated(LedgerError):   status, code = 401, "unauthenticated"
class Forbidden(LedgerError):         status, code = 403, "forbidden"
class NotFound(LedgerError):          status, code = 404, "not_found"
class IdempotencyConflict(LedgerError): status, code = 409, "idempotency_key_reused_with_different_request"
class InsufficientFunds(LedgerError): status, code = 422, "insufficient_funds"

MAX_AMOUNT = 10**12   # minor units; stops overflow and absurd requests
ROLES = ("admin", "holder", "auditor")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
  role TEXT NOT NULL DEFAULT 'holder' CHECK (role IN ('admin','holder','auditor')));
CREATE TABLE IF NOT EXISTS accounts(
  id TEXT PRIMARY KEY,
  owner_id TEXT REFERENCES users(id),          -- NULL for system accounts
  currency TEXT NOT NULL,
  is_system INTEGER NOT NULL DEFAULT 0,
  balance INTEGER NOT NULL DEFAULT 0,          -- cached; provable from entries
  CHECK (is_system = 1 OR balance >= 0));      -- DB-level overdraft guard
CREATE TABLE IF NOT EXISTS transactions(
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  idem_key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  kind TEXT NOT NULL,
  response TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(user_id, idem_key));                  -- DB-level duplicate guard
CREATE TABLE IF NOT EXISTS entries(            -- append-only
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  txn_id TEXT NOT NULL REFERENCES transactions(id),
  account_id TEXT NOT NULL REFERENCES accounts(id),
  amount INTEGER NOT NULL CHECK (amount <> 0), -- signed minor units: debit<0, credit>0
  created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log(          -- append-only, includes rejected attempts
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL, user_id TEXT, action TEXT NOT NULL,
  idem_key TEXT, detail TEXT, outcome TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS entries_no_update BEFORE UPDATE ON entries
  BEGIN SELECT RAISE(ABORT, 'ledger entries are immutable'); END;
CREATE TRIGGER IF NOT EXISTS entries_no_delete BEFORE DELETE ON entries
  BEGIN SELECT RAISE(ABORT, 'ledger entries are immutable'); END;
CREATE TRIGGER IF NOT EXISTS txn_no_update BEFORE UPDATE ON transactions
  BEGIN SELECT RAISE(ABORT, 'transactions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS txn_no_delete BEFORE DELETE ON transactions
  BEGIN SELECT RAISE(ABORT, 'transactions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit log is immutable'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit log is immutable'); END;
"""

def _h(s): return hashlib.sha256(s.encode()).hexdigest()
def _id(): return uuid.uuid4().hex

class Ledger:
    def __init__(self, path="ledgerline.db"):
        self.path = path
        c = self._conn(); c.executescript(SCHEMA); c.close()

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA journal_mode=WAL")
        return c

    # ---------- identity & roles ----------
    def _role(self, c, user_id):
        r = c.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if not r: raise Unauthenticated("unknown user")
        return r["role"]

    def create_user(self, role="holder", token=None):
        if role not in ROLES: raise ValidationError("role must be admin, holder or auditor")
        uid, token = _id(), token or secrets.token_urlsafe(32)
        c = self._conn()
        try:
            c.execute("INSERT INTO users(id,token_hash,role) VALUES(?,?,?)", (uid, _h(token), role))
        finally: c.close()
        return {"user_id": uid, "role": role, "token": token}   # token shown once; only hash stored

    def whoami(self, user_id):
        c = self._conn()
        try: return {"user_id": user_id, "role": self._role(c, user_id)}
        finally: c.close()

    def readiness(self):
        """Can this instance serve traffic? One True/False per dependency. Never returns error text,
        so a failing probe cannot leak paths, hostnames or credentials."""
        try:
            c = self._conn()
            try: c.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            finally: c.close()
            return {"database": True}
        except Exception:
            return {"database": False}

    def admin_create_user(self, actor_id, role):
        """Only an administrator can create admin/auditor users (public signup is holder-only)."""
        with self._audited(actor_id, "create_staff_user", str(role)[:30]):
            c = self._conn()
            try:
                if self._role(c, actor_id) != "admin": raise Forbidden("administrators only")
            finally: c.close()
            return self.create_user(role)

    def ensure_user(self, token, role):
        """Bootstrap helper: create the user for this token if it does not exist yet."""
        c = self._conn()
        try:
            r = c.execute("SELECT id FROM users WHERE token_hash=?", (_h(token),)).fetchone()
        finally: c.close()
        return r["id"] if r else self.create_user(role, token)["user_id"]

    def authenticate(self, token):
        if not token:
            self._audit(None, "authenticate", None, "no token supplied", "rejected:unauthenticated")
            raise Unauthenticated("missing token")
        c = self._conn()
        r = c.execute("SELECT id FROM users WHERE token_hash=?", (_h(token),)).fetchone()
        c.close()
        if not r:
            self._audit(None, "authenticate", None, "token_hash:" + _h(token)[:8], "rejected:unauthenticated")
            raise Unauthenticated("invalid token")
        return r["id"]

    def create_account(self, user_id, currency):
        with self._audited(user_id, "create_account", str(currency)[:10]):
            if not (isinstance(currency, str) and len(currency) == 3 and currency.isalpha()):
                raise ValidationError("currency must be a 3-letter code")
            aid = _id()
            c = self._conn()
            try:
                if self._role(c, user_id) != "holder":
                    raise Forbidden("only account holders can open accounts")
                c.execute("INSERT INTO accounts(id,owner_id,currency) VALUES(?,?,?)",
                          (aid, user_id, currency.upper()))
            finally: c.close()
            return {"account_id": aid, "currency": currency.upper(), "balance": 0}

    def seed_demo(self, admin_id):
        """Demo data: two holders, one auditor, funded accounts. Idempotent. Only used if SEED_DEMO=1."""
        out = {}
        for name, bal in (("alice", 100000), ("bob", 5000)):
            uid = self.ensure_user(f"demo-{name}-token", "holder")
            c = self._conn()
            try:
                r = c.execute("SELECT id FROM accounts WHERE owner_id=? ORDER BY rowid LIMIT 1", (uid,)).fetchone()
            finally: c.close()
            aid = r["id"] if r else self.create_account(uid, "USD")["account_id"]
            self.deposit(admin_id, f"seed-{name}", aid, bal)
            out[name] = {"token": f"demo-{name}-token", "account_id": aid}
        self.ensure_user("demo-auditor-token", "auditor")
        out["auditor"] = {"token": "demo-auditor-token"}
        return out

    # ---------- money movement ----------
    def deposit(self, user_id, idem_key, account_id, amount):
        return self._post(user_id, idem_key, "deposit", None, account_id, amount)
    def withdraw(self, user_id, idem_key, account_id, amount):
        return self._post(user_id, idem_key, "withdrawal", account_id, None, amount)
    def transfer(self, user_id, idem_key, src, dst, amount):
        return self._post(user_id, idem_key, "transfer", src, dst, amount)

    def _system_account(self, c, currency):
        sid = "system-" + currency
        c.execute("INSERT OR IGNORE INTO accounts(id,owner_id,currency,is_system) VALUES(?,?,?,1)",
                  (sid, None, currency))
        return sid

    def _post(self, user_id, idem_key, kind, src, dst, amount):
        try:
            if not isinstance(idem_key, str) or not idem_key.strip() or len(idem_key) > 128:
                raise ValidationError("Idempotency-Key header required (1-128 chars)")
            if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
                raise ValidationError("amount must be a positive integer (minor units)")
            if amount > MAX_AMOUNT: raise ValidationError("amount exceeds maximum")
            req_hash = _h(json.dumps([kind, src, dst, amount]))
            return self._post_tx(user_id, idem_key, kind, src, dst, amount, req_hash)
        except LedgerError as e:
            self._audit(user_id, kind, idem_key, f"{src}->{dst} {amount}", "rejected:" + e.code)
            raise

    def _post_tx(self, user_id, idem_key, kind, src, dst, amount, req_hash):
        c = self._conn()
        try:
            c.execute("BEGIN IMMEDIATE")           # serialises writers: no race between check and update
            role = self._role(c, user_id)
            if role == "auditor": raise Forbidden("auditors are read-only")
            if kind == "deposit" and role != "admin":
                raise Forbidden("only administrators can fund accounts")
            prev = c.execute("SELECT request_hash,response FROM transactions "
                             "WHERE user_id=? AND idem_key=?", (user_id, idem_key)).fetchone()
            if prev:
                if prev["request_hash"] != req_hash:
                    raise IdempotencyConflict("key already used with a different request")
                c.execute("COMMIT")
                return {**json.loads(prev["response"]), "replayed": True}

            def load(aid):
                r = c.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
                if not r: raise NotFound("account not found")
                return r
            if kind == "deposit":
                d = load(dst)
                owner = c.execute("SELECT role FROM users WHERE id=?", (d["owner_id"],)).fetchone()
                if not owner or owner["role"] != "holder":
                    raise Forbidden("deposits can only go into an account holder's account")
                s = load(self._system_account(c, d["currency"]))
            elif kind == "withdrawal":
                s = load(src); d = load(self._system_account(c, s["currency"]))
            else:
                if src == dst: raise ValidationError("source and destination must differ")
                s, d = load(src), load(dst)

            # authorisation: whoever debits must own the account being debited (admins fund
            # accounts via deposits but can never move a customer's money out).
            if kind != "deposit" and s["owner_id"] != user_id:
                raise Forbidden("you do not own this account")
            if s["currency"] != d["currency"]:
                raise ValidationError("currency mismatch")

            # atomic conditional debit: fails if funds are insufficient at this instant
            cur = c.execute("UPDATE accounts SET balance=balance-? "
                            "WHERE id=? AND (is_system=1 OR balance>=?)", (amount, s["id"], amount))
            if cur.rowcount != 1: raise InsufficientFunds("insufficient funds")
            c.execute("UPDATE accounts SET balance=balance+? WHERE id=?", (amount, d["id"]))

            txn_id, now = _id(), time.time()
            resp = {"transaction_id": txn_id, "kind": kind, "from": s["id"], "to": d["id"],
                    "amount": amount, "currency": s["currency"], "status": "completed"}
            c.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?,?)",
                      (txn_id, user_id, idem_key, req_hash, kind, json.dumps(resp), now))
            c.execute("INSERT INTO entries(txn_id,account_id,amount,created_at) VALUES(?,?,?,?)",
                      (txn_id, s["id"], -amount, now))
            c.execute("INSERT INTO entries(txn_id,account_id,amount,created_at) VALUES(?,?,?,?)",
                      (txn_id, d["id"], amount, now))
            c.execute("INSERT INTO audit_log(ts,user_id,action,idem_key,detail,outcome) VALUES(?,?,?,?,?,?)",
                      (now, user_id, kind, idem_key, txn_id, "completed"))
            c.execute("COMMIT")
            return {**resp, "replayed": False}
        except BaseException:
            if c.in_transaction: c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    def _audit(self, user_id, action, idem_key, detail, outcome):
        c = self._conn()
        try:
            c.execute("INSERT INTO audit_log(ts,user_id,action,idem_key,detail,outcome) VALUES(?,?,?,?,?,?)",
                      (time.time(), user_id, action, idem_key, detail, outcome))
        finally:
            c.close()

    @contextlib.contextmanager
    def _audited(self, user_id, action, detail=""):
        """Run a block; if the request is refused (403/404/400...), write it to the audit log, then re-raise."""
        try:
            yield
        except LedgerError as e:
            self._audit(user_id, action, None, detail, "rejected:" + e.code)
            raise

    # ---------- reads ----------
    def _viewable(self, c, user_id, account_id):
        """Holders see only their own accounts; auditors and admins may read any (read-only)."""
        role = self._role(c, user_id)
        a = c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not a: raise NotFound("account not found")
        if role == "holder" and a["owner_id"] != user_id: raise Forbidden("you do not own this account")
        return a

    def get_account(self, user_id, account_id):
        with self._audited(user_id, "read_account", str(account_id)[:64]):
            c = self._conn()
            try:
                a = self._viewable(c, user_id, account_id)
                return {"account_id": a["id"], "currency": a["currency"], "balance": a["balance"]}
            finally: c.close()

    def list_accounts(self, user_id):
        c = self._conn()
        try:
            if self._role(c, user_id) == "holder":
                rows = c.execute("SELECT id,currency,balance FROM accounts WHERE owner_id=?", (user_id,))
            else:
                rows = c.execute("SELECT id,currency,balance FROM accounts WHERE is_system=0")
            return [{"account_id": r["id"], "currency": r["currency"], "balance": r["balance"]} for r in rows]
        finally: c.close()

    def statement(self, user_id, account_id):
        with self._audited(user_id, "read_statement", str(account_id)[:64]):
            c = self._conn()
            try:
                self._viewable(c, user_id, account_id)
                rows = c.execute("SELECT e.id,e.txn_id,t.kind,e.amount,e.created_at FROM entries e "
                                 "JOIN transactions t ON t.id=e.txn_id WHERE e.account_id=? ORDER BY e.id",
                                 (account_id,)).fetchall()
                return [dict(r) for r in rows]
            finally: c.close()

    def _oversight(self, c, user_id):
        if self._role(c, user_id) not in ("admin", "auditor"):
            raise Forbidden("auditors and administrators only")

    def audit_entries(self, user_id, limit=100):
        with self._audited(user_id, "read_audit_log"):
            c = self._conn()
            try:
                self._oversight(c, user_id)
                limit = max(1, min(int(limit), 500))
                rows = c.execute("SELECT id,ts,user_id,action,idem_key,detail,outcome FROM audit_log "
                                 "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
                return [dict(r) for r in rows]
            finally: c.close()

    def reconcile(self, user_id):
        with self._audited(user_id, "reconcile"):
            c = self._conn()
            try: self._oversight(c, user_id)
            finally: c.close()
        return self._reconcile()

    def _reconcile(self):
        """Prove the books: every txn nets to zero, and every cached balance equals its entries."""
        c = self._conn(); problems = []
        try:
            for r in c.execute("SELECT txn_id,SUM(amount) s FROM entries GROUP BY txn_id HAVING s<>0"):
                problems.append(f"txn {r['txn_id']} does not balance ({r['s']})")
            for r in c.execute("SELECT a.id,a.balance,COALESCE(SUM(e.amount),0) s FROM accounts a "
                               "LEFT JOIN entries e ON e.account_id=a.id GROUP BY a.id "
                               "HAVING a.balance<>s"):
                problems.append(f"account {r['id']} cached {r['balance']} != ledger {r['s']}")
            total = c.execute("SELECT COALESCE(SUM(amount),0) FROM entries").fetchone()[0]
            if total != 0: problems.append(f"ledger total is {total}, expected 0")
            return {"ok": not problems, "problems": problems}
        finally: c.close()
