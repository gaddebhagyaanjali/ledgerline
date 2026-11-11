import json, os, subprocess, sys, tempfile, sqlite3, threading, unittest, urllib.error, urllib.request
from ledger import *

class T(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".db"); self.L = Ledger(self.path)
        mk = lambda role: self.L.create_user(role)["user_id"]
        self.admin, self.auditor = mk("admin"), mk("auditor")
        self.alice, self.bob = mk("holder"), mk("holder")
        self.a = self.L.create_account(self.alice, "USD")["account_id"]
        self.b = self.L.create_account(self.bob, "USD")["account_id"]
    def tearDown(self): os.path.exists(self.path) and os.remove(self.path)
    def bal(self, u, a): return self.L.get_account(u, a)["balance"]
    def fund(self, acct, amt, key="fund"): return self.L.deposit(self.admin, key, acct, amt)

    # ---- money correctness
    def test_basic_flow_balances(self):
        self.fund(self.a, 1000)
        self.L.transfer(self.alice, "t1", self.a, self.b, 300)
        self.L.withdraw(self.bob, "w1", self.b, 100)
        self.assertEqual((self.bal(self.alice, self.a), self.bal(self.bob, self.b)), (700, 200))
        self.assertTrue(self.L.reconcile(self.auditor)["ok"])

    def test_overdraft_and_bad_amounts_rejected(self):
        with self.assertRaises(InsufficientFunds): self.L.withdraw(self.alice, "o", self.a, 1)
        for bad in (0, -5, 1.5, "10", True, None):
            with self.assertRaises(ValidationError): self.fund(self.a, bad, "b")

    def test_amount_cap_and_huge_ints(self):
        for bad in (MAX_AMOUNT + 1, 2**70):
            with self.assertRaises(ValidationError): self.fund(self.a, bad, "big")

    def test_currency_mismatch_and_self_transfer(self):
        eur = self.L.create_account(self.bob, "EUR")["account_id"]
        self.fund(self.a, 100)
        with self.assertRaises(ValidationError): self.L.transfer(self.alice, "m", self.a, eur, 10)
        with self.assertRaises(ValidationError): self.L.transfer(self.alice, "s2", self.a, self.a, 10)

    def test_failed_transfer_leaves_no_partial_state(self):
        self.fund(self.a, 50)
        with self.assertRaises(InsufficientFunds): self.L.transfer(self.alice, "f", self.a, self.b, 80)
        self.assertEqual((self.bal(self.alice, self.a), self.bal(self.bob, self.b)), (50, 0))
        self.assertTrue(self.L.reconcile(self.admin)["ok"])

    # ---- idempotency
    def test_idempotent_replay_returns_same_result_once(self):
        r1 = self.fund(self.a, 500, "k"); r2 = self.fund(self.a, 500, "k")
        self.assertEqual(r1["transaction_id"], r2["transaction_id"]); self.assertTrue(r2["replayed"])
        self.assertEqual(self.bal(self.alice, self.a), 500)

    def test_key_reuse_with_different_payload_rejected(self):
        self.fund(self.a, 500, "k")
        with self.assertRaises(IdempotencyConflict): self.fund(self.a, 600, "k")

    def test_missing_idempotency_key_rejected(self):
        for k in (None, "", "   "):
            with self.assertRaises(ValidationError): self.fund(self.a, 5, k)

    def test_concurrent_duplicate_requests_pay_once(self):
        self.fund(self.a, 1000); res = []
        def go(): res.append(self.L.transfer(self.alice, "same", self.a, self.b, 100)["transaction_id"])
        ts = [threading.Thread(target=go) for _ in range(20)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(len(set(res)), 1); self.assertEqual(self.bal(self.bob, self.b), 100)

    # ---- concurrency
    def test_concurrent_withdrawals_cannot_double_spend(self):
        self.fund(self.a, 100); ok, fail = [], []
        def go(i):
            try: self.L.withdraw(self.alice, f"w{i}", self.a, 100); ok.append(i)
            except InsufficientFunds: fail.append(i)
        ts = [threading.Thread(target=go, args=(i,)) for i in range(15)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual((len(ok), len(fail)), (1, 14))
        self.assertEqual(self.bal(self.alice, self.a), 0); self.assertTrue(self.L.reconcile(self.admin)["ok"])

    def test_concurrent_opposite_transfers_conserve_money(self):
        self.fund(self.a, 1000, "fa"); self.fund(self.b, 1000, "fb")
        def go(i):
            for j in range(10):
                try:
                    if i % 2: self.L.transfer(self.alice, f"x{i}-{j}", self.a, self.b, 7)
                    else:     self.L.transfer(self.bob, f"y{i}-{j}", self.b, self.a, 11)
                except InsufficientFunds: pass
        ts = [threading.Thread(target=go, args=(i,)) for i in range(8)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(self.bal(self.alice, self.a) + self.bal(self.bob, self.b), 2000)
        self.assertTrue(self.L.reconcile(self.admin)["ok"])

    # ---- authorisation & roles
    def test_cannot_move_money_from_someone_elses_account(self):
        self.fund(self.b, 500)
        with self.assertRaises(Forbidden): self.L.transfer(self.alice, "x", self.b, self.a, 100)
        with self.assertRaises(Forbidden): self.L.withdraw(self.alice, "x2", self.b, 100)
        with self.assertRaises(Forbidden): self.L.get_account(self.alice, self.b)
        with self.assertRaises(Forbidden): self.L.statement(self.alice, self.b)
        self.assertEqual(self.bal(self.bob, self.b), 500)

    def test_holders_cannot_print_money(self):
        with self.assertRaises(Forbidden): self.L.deposit(self.alice, "d", self.a, 100)
        self.assertEqual(self.bal(self.alice, self.a), 0)

    def test_admin_can_fund_but_never_withdraw_or_transfer_customer_money(self):
        self.fund(self.a, 500)
        with self.assertRaises(Forbidden): self.L.withdraw(self.admin, "w", self.a, 100)
        with self.assertRaises(Forbidden): self.L.transfer(self.admin, "t", self.a, self.b, 100)

    def test_auditor_is_read_only_but_sees_everything(self):
        self.fund(self.a, 500)
        self.assertEqual(self.bal(self.auditor, self.a), 500)
        self.assertEqual(len(self.L.statement(self.auditor, self.a)), 1)
        self.assertGreaterEqual(len(self.L.list_accounts(self.auditor)), 2)
        self.assertGreaterEqual(len(self.L.audit_entries(self.auditor)), 1)
        with self.assertRaises(Forbidden): self.L.deposit(self.auditor, "d", self.a, 1)
        with self.assertRaises(Forbidden): self.L.withdraw(self.auditor, "w", self.a, 1)
        with self.assertRaises(Forbidden): self.L.create_account(self.auditor, "USD")

    def test_holders_cannot_see_audit_log_or_reconcile_or_make_staff(self):
        with self.assertRaises(Forbidden): self.L.audit_entries(self.alice)
        with self.assertRaises(Forbidden): self.L.reconcile(self.alice)
        for role in ("admin", "auditor"):
            with self.assertRaises(Forbidden): self.L.admin_create_user(self.alice, role)
        with self.assertRaises(Forbidden): self.L.admin_create_user(self.auditor, "admin")
        self.assertEqual(self.L.admin_create_user(self.admin, "auditor")["role"], "auditor")

    def test_holder_lists_only_own_accounts(self):
        self.assertEqual([x["account_id"] for x in self.L.list_accounts(self.alice)], [self.a])

    def test_whoami_reports_role(self):
        self.assertEqual(self.L.whoami(self.auditor)["role"], "auditor")
        self.assertEqual(self.L.whoami(self.alice)["role"], "holder")

    def test_bad_token_and_unknown_role(self):
        with self.assertRaises(Unauthenticated): self.L.authenticate("nope")
        with self.assertRaises(ValidationError): self.L.admin_create_user(self.admin, "root")

    # ---- integrity & audit
    def test_ledger_is_immutable_and_tampering_detected(self):
        self.fund(self.a, 50)
        c = sqlite3.connect(self.path)
        for sql in ("UPDATE entries SET amount=999", "DELETE FROM entries", "DELETE FROM audit_log",
                    "UPDATE transactions SET kind='x'"):
            with self.assertRaises(sqlite3.DatabaseError): c.execute(sql)
        c.execute("UPDATE accounts SET balance=9999 WHERE id=?", (self.a,)); c.commit(); c.close()
        self.assertFalse(self.L.reconcile(self.auditor)["ok"])

    def test_rejected_attempts_are_audited(self):
        with self.assertRaises(InsufficientFunds): self.L.withdraw(self.alice, "z", self.a, 10)
        self.assertEqual(self.L.audit_entries(self.auditor)[0]["outcome"], "rejected:insufficient_funds")

    def test_seed_demo_is_idempotent(self):
        self.L.seed_demo(self.admin); self.L.seed_demo(self.admin)
        tok = self.L.authenticate("demo-alice-token")
        self.assertEqual(self.L.list_accounts(tok)[0]["balance"], 100000)

    # ---- audit of refused access (not only refused money movements)
    def _audit_rows(self, n=10): return self.L.audit_entries(self.auditor, n)   # newest first

    def test_failed_login_is_audited_without_storing_the_token(self):
        guess = "super-secret-guess-123"
        with self.assertRaises(Unauthenticated): self.L.authenticate(guess)
        with self.assertRaises(Unauthenticated): self.L.authenticate(None)
        newest, older = self._audit_rows(2)
        self.assertEqual((newest["action"], newest["detail"], newest["outcome"]),
                         ("authenticate", "no token supplied", "rejected:unauthenticated"))
        self.assertIsNone(older["user_id"]); self.assertTrue(older["detail"].startswith("token_hash:"))
        dump = str(sqlite3.connect(self.path).execute("SELECT * FROM audit_log").fetchall())
        self.assertNotIn(guess, dump)                      # the guessed token itself is never stored

    def test_denied_and_missing_account_reads_are_audited(self):
        with self.assertRaises(Forbidden): self.L.get_account(self.alice, self.b)
        with self.assertRaises(NotFound): self.L.get_account(self.alice, "0" * 32)
        missing, denied = self._audit_rows(2)
        self.assertEqual((denied["user_id"], denied["action"], denied["detail"], denied["outcome"]),
                         (self.alice, "read_account", self.b, "rejected:forbidden"))
        self.assertEqual((missing["action"], missing["outcome"]), ("read_account", "rejected:not_found"))

    def test_denied_statement_read_is_audited(self):
        with self.assertRaises(Forbidden): self.L.statement(self.alice, self.b)
        row = self._audit_rows(1)[0]
        self.assertEqual((row["user_id"], row["action"], row["outcome"]),
                         (self.alice, "read_statement", "rejected:forbidden"))

    def test_holder_denied_oversight_is_audited(self):
        with self.assertRaises(Forbidden): self.L.audit_entries(self.alice)
        with self.assertRaises(Forbidden): self.L.reconcile(self.alice)
        recon, audit = self._audit_rows(2)
        self.assertEqual((recon["action"], recon["user_id"], recon["outcome"]), ("reconcile", self.alice, "rejected:forbidden"))
        self.assertEqual((audit["action"], audit["user_id"], audit["outcome"]), ("read_audit_log", self.alice, "rejected:forbidden"))

    def test_denied_staff_creation_and_auditor_account_creation_are_audited(self):
        with self.assertRaises(Forbidden): self.L.admin_create_user(self.alice, "admin")
        with self.assertRaises(Forbidden): self.L.create_account(self.auditor, "USD")
        acct, staff = self._audit_rows(2)
        self.assertEqual((staff["action"], staff["user_id"], staff["detail"], staff["outcome"]),
                         ("create_staff_user", self.alice, "admin", "rejected:forbidden"))
        self.assertEqual((acct["action"], acct["user_id"], acct["outcome"]),
                         ("create_account", self.auditor, "rejected:forbidden"))

    def test_successful_reads_do_not_flood_the_audit_log(self):
        before = len(self._audit_rows(500))
        self.L.get_account(self.alice, self.a); self.L.statement(self.alice, self.a); self.L.list_accounts(self.alice)
        self.assertEqual(len(self._audit_rows(500)), before)


    # ---- separation of duties: an admin must not be able to mint money for themselves
    def test_admins_and_auditors_cannot_open_accounts(self):
        for who in (self.admin, self.auditor):
            with self.assertRaises(Forbidden): self.L.create_account(who, "USD")
        self.assertEqual(self.L.list_accounts(self.admin).__len__(), 2)   # only alice's and bob's exist
        row = self._audit_rows(1)[0]
        self.assertEqual((row["action"], row["outcome"]), ("create_account", "rejected:forbidden"))

    def test_deposit_into_a_non_holder_account_is_refused(self):
        # Simulate an old/legacy account owned by staff (bypassing the API) to test the second rule on its own.
        c = sqlite3.connect(self.path)
        for who, aid in ((self.admin, "legacy-admin-acct"), (self.auditor, "legacy-auditor-acct")):
            c.execute("INSERT INTO accounts(id,owner_id,currency) VALUES(?,?,?)", (aid, who, "USD"))
        c.commit(); c.close()
        for i, aid in enumerate(("legacy-admin-acct", "legacy-auditor-acct")):
            with self.assertRaises(Forbidden): self.L.deposit(self.admin, f"mint{i}", aid, 500000)
            self.assertEqual(self.L.get_account(self.admin, aid)["balance"], 0)
        self.assertTrue(self.L.reconcile(self.auditor)["ok"])

    def test_deposit_into_the_system_account_is_refused(self):
        self.fund(self.a, 100)                       # creates system-USD
        with self.assertRaises(Forbidden): self.L.deposit(self.admin, "sys", "system-USD", 50)

    def test_refused_mint_attempt_is_audited(self):
        with self.assertRaises(Forbidden): self.L.create_account(self.admin, "USD")
        with self.assertRaises(NotFound): self.L.deposit(self.admin, "x", "no-such-account", 5)
        self.assertEqual({r["outcome"] for r in self._audit_rows(2)}, {"rejected:forbidden", "rejected:not_found"})

    def test_admin_can_still_fund_a_holder(self):
        r = self.fund(self.a, 1234)
        self.assertEqual((r["status"], self.bal(self.alice, self.a)), ("completed", 1234))

    # ---- onboarding, user management, token revocation, first admin
    def _new_user(self, **kw): return self.L.create_user("holder", **kw)

    def test_pending_user_cannot_use_the_system_until_approved(self):
        u = self._new_user(status="pending", display_name="Pat")
        self.assertEqual(self.L.whoami(u["user_id"])["status"], "pending")      # can still ask "who am I"
        for attempt in (lambda: self.L.create_account(u["user_id"], "USD"),
                        lambda: self.L.list_accounts(u["user_id"]),
                        lambda: self.L.get_account(u["user_id"], self.a)):
            with self.assertRaises(Forbidden): attempt()
        self.L.set_user_status(self.admin, u["user_id"], "active")
        self.assertEqual(self.L.create_account(u["user_id"], "USD")["balance"], 0)

    def test_only_admins_can_list_users_or_change_status(self):
        for who in (self.alice, self.auditor):
            with self.assertRaises(Forbidden): self.L.list_users(who)
            with self.assertRaises(Forbidden): self.L.set_user_status(who, self.bob, "disabled")
        self.assertEqual(self.L.whoami(self.bob)["status"], "active")
        self.assertEqual(self._audit_rows(1)[0]["outcome"], "rejected:forbidden")

    def test_disabled_user_loses_access_immediately(self):
        u = self._new_user()
        self.assertEqual(self.L.authenticate(u["token"]), u["user_id"])
        self.assertTrue(self.L.set_user_status(self.admin, u["user_id"], "disabled")["changed"])
        with self.assertRaises(Unauthenticated): self.L.authenticate(u["token"])        # the token is revoked
        with self.assertRaises(Unauthenticated): self.L.whoami(u["user_id"])
        with self.assertRaises(Unauthenticated): self.L.create_account(u["user_id"], "USD")
        row = next(r for r in self._audit_rows(10) if r["action"] == "authenticate")
        self.assertEqual((row["user_id"], row["detail"]), (u["user_id"], "disabled account"))

    def test_disabled_user_with_money_cannot_move_it(self):
        u = self._new_user(); acct = self.L.create_account(u["user_id"], "USD")["account_id"]
        self.fund(acct, 500)
        self.L.set_user_status(self.admin, u["user_id"], "disabled")
        with self.assertRaises(Unauthenticated): self.L.withdraw(u["user_id"], "w", acct, 100)
        with self.assertRaises(Unauthenticated): self.L.transfer(u["user_id"], "t", acct, self.b, 100)
        self.assertEqual(self.L.get_account(self.admin, acct)["balance"], 500)
        self.assertTrue(self.L.reconcile(self.auditor)["ok"])

    def test_admin_can_reenable_a_user(self):
        u = self._new_user(); self.L.set_user_status(self.admin, u["user_id"], "disabled")
        self.L.set_user_status(self.admin, u["user_id"], "active")
        self.assertEqual(self.L.authenticate(u["token"]), u["user_id"])

    def test_admin_cannot_change_their_own_status(self):
        with self.assertRaises(Forbidden): self.L.set_user_status(self.admin, self.admin, "disabled")
        self.assertEqual(self.L.whoami(self.admin)["status"], "active")

    def test_user_status_input_is_validated(self):
        for bad in ("pending", "root", None, 5):
            with self.assertRaises(ValidationError): self.L.set_user_status(self.admin, self.alice, bad)
        with self.assertRaises(NotFound): self.L.set_user_status(self.admin, "no-such-user", "disabled")
        with self.assertRaises(ValidationError): self.L.list_users(self.admin, status="bogus")

    def test_status_changes_and_signups_are_audited(self):
        u = self._new_user(display_name="Lee")
        self.assertEqual((self._audit_rows(1)[0]["action"], self._audit_rows(1)[0]["outcome"]), ("signup", "completed"))
        self.L.set_user_status(self.admin, u["user_id"], "disabled")
        row = self._audit_rows(1)[0]
        self.assertEqual((row["action"], row["user_id"], row["outcome"]), ("set_user_status", self.admin, "completed"))
        self.assertEqual(row["detail"], u["user_id"] + ":active->disabled")

    def test_list_users_filters_and_never_shows_tokens(self):
        u = self._new_user(status="pending", display_name="Pat")
        rows = self.L.list_users(self.admin, status="pending")
        self.assertEqual([(r["user_id"], r["display_name"], r["status"]) for r in rows], [(u["user_id"], "Pat", "pending")])
        self.assertEqual(set(rows[0]), {"user_id", "role", "status", "display_name", "origin"})
        self.assertNotIn(u["token"], str(self.L.list_users(self.admin)))

    def test_display_name_is_validated(self):
        for bad in ("", "   ", "x" * 61, 12, ["a"]):
            with self.assertRaises(ValidationError): self._new_user(display_name=bad)

    def test_bootstrap_admin_creates_once_and_is_repeatable(self):
        tok = "bootstrap-token-0123456789"
        r1, r2 = self.L.bootstrap_admin(tok), self.L.bootstrap_admin(tok)
        self.assertEqual((r1["created"], r2["created"], r1["user_id"] == r2["user_id"]), (True, False, True))
        self.assertEqual(self.L.whoami(self.L.authenticate(tok))["role"], "admin")

    def test_changing_the_bootstrap_token_revokes_the_old_one(self):
        old, new = "old-bootstrap-token-0123456", "new-bootstrap-token-0123456"
        self.L.bootstrap_admin(old)
        other = self.L.admin_create_user(self.admin, "admin")          # an ordinary admin, not a bootstrap one
        self.assertEqual(self.L.bootstrap_admin(new)["revoked"], 1)
        with self.assertRaises(Unauthenticated): self.L.authenticate(old)
        self.assertTrue(self.L.authenticate(new)); self.assertTrue(self.L.authenticate(other["token"]))

    def test_bootstrap_admin_can_recover_a_locked_out_admin(self):
        tok = "bootstrap-token-0123456789"; uid = self.L.bootstrap_admin(tok)["user_id"]
        self.L.set_user_status(self.admin, uid, "disabled")
        with self.assertRaises(Unauthenticated): self.L.authenticate(tok)
        self.L.bootstrap_admin(tok)
        self.assertEqual(self.L.authenticate(tok), uid)

    def test_bootstrap_refuses_short_tokens_and_non_admin_tokens(self):
        self._new_user(token="holder-token-0123456789")
        with self.assertRaises(ValidationError): self.L.bootstrap_admin("holder-token-0123456789")
        with self.assertRaises(ValidationError): self.L.bootstrap_admin("short")

    def test_old_database_is_upgraded_in_place(self):
        path = tempfile.mktemp(suffix=".db"); c = sqlite3.connect(path)
        c.execute("CREATE TABLE users(id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, role TEXT NOT NULL "
                  "DEFAULT 'holder' CHECK (role IN ('admin','holder','auditor')))")
        c.execute("INSERT INTO users VALUES('u1','h1','admin')"); c.execute("INSERT INTO users VALUES('u2','h2','holder')")
        c.commit(); c.close()
        Ledger(path); Ledger(path)                                         # second open must not fail either
        c = sqlite3.connect(path)
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
        rows = dict(c.execute("SELECT id, status || ':' || origin FROM users").fetchall()); c.close()
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(path + suffix): os.remove(path + suffix)
        self.assertTrue({"status", "display_name", "origin"} <= cols)
        self.assertEqual(rows, {"u1": "active:bootstrap", "u2": "active:signup"})


class HttpTests(unittest.TestCase):
    """Tests through the real HTTP server (a second layer of defence: the API itself, not just ledger.py)."""
    @classmethod
    def setUpClass(cls):
        cls.path = tempfile.mktemp(suffix=".db")
        os.environ["LEDGER_DB"] = cls.path           # must be set before server.py is imported
        import server
        cls.srv = server
        cls.httpd = server.Server(("127.0.0.1", 0), server.H)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(cls.path + suffix): os.remove(cls.path + suffix)

    def call(self, method, path, data=None, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r: return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            body = e.read(); e.close()
            return e.code, body, e.headers

    def test_health_is_public_and_ok(self):
        status, body, _ = self.call("GET", "/health")
        self.assertEqual((status, json.loads(body)), (200, {"status": "ok"}))

    def test_ready_reports_database_ok(self):
        status, body, _ = self.call("GET", "/ready")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"status": "ready", "checks": {"database": "ok"}})

    def test_ready_returns_503_without_leaking_details(self):
        led, good = self.srv.L, self.srv.L.path
        led.path = "/nonexistent-folder/secret-name.db"          # make the database unreachable
        try: status, body, _ = self.call("GET", "/ready")
        finally: led.path = good
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body), {"status": "not_ready", "checks": {"database": "error"}})
        self.assertNotIn(b"nonexistent", body); self.assertNotIn(b"secret-name", body)

    def test_health_stays_ok_when_database_is_down(self):
        led, good = self.srv.L, self.srv.L.path
        led.path = "/nonexistent-folder/x.db"
        try: status, _, _ = self.call("GET", "/health")
        finally: led.path = good
        self.assertEqual(status, 200)                            # liveness must not depend on the database

    def test_dashboard_has_security_headers(self):
        status, _, headers = self.call("GET", "/")
        self.assertEqual(status, 200)
        csp = headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'none'", csp); self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_protected_route_without_token_is_401(self):
        status, body, _ = self.call("GET", "/accounts")
        self.assertEqual((status, json.loads(body)["error"]), (401, "unauthenticated"))

    def test_bad_json_is_400_not_500(self):
        token = self.srv.L.create_user("admin")["token"]
        status, _, _ = self.call("POST", "/deposits", b"{bad", {"Authorization": "Bearer " + token, "Idempotency-Key": "k1"})
        self.assertEqual(status, 400)


    def jcall(self, method, path, body=None, token=None, key=None):
        headers = {"Content-Type": "application/json"}
        if token: headers["Authorization"] = "Bearer " + token
        if key: headers["Idempotency-Key"] = key
        status, raw, _ = self.call(method, path, json.dumps(body).encode() if body is not None else None, headers)
        return status, json.loads(raw or b"{}")

    def _signup(self, mode, name):
        old, self.srv.ONBOARDING = self.srv.ONBOARDING, mode
        try: return self.jcall("POST", "/users", {"display_name": name})
        finally: self.srv.ONBOARDING = old

    def test_manual_onboarding_signup_waits_for_admin_approval(self):
        admin = self.srv.L.create_user("admin")["token"]
        status, new = self._signup("manual", "Pat")
        self.assertEqual((status, new["status"]), (201, "pending"))
        self.assertEqual(self.jcall("GET", "/me", token=new["token"])[1]["status"], "pending")
        self.assertEqual(self.jcall("POST", "/accounts", {"currency": "USD"}, new["token"])[0], 403)
        _, pending = self.jcall("GET", "/admin/users?status=pending", token=admin)
        self.assertIn(new["user_id"], [u["user_id"] for u in pending])
        self.assertEqual(self.jcall("POST", f"/admin/users/{new['user_id']}/status", {"status": "active"}, admin)[0], 200)
        self.assertEqual(self.jcall("POST", "/accounts", {"currency": "USD"}, new["token"])[0], 201)

    def test_auto_onboarding_signup_is_active_at_once(self):
        status, new = self._signup("auto", "Sam")
        self.assertEqual((status, new["status"]), (201, "active"))
        self.assertEqual(self.jcall("POST", "/accounts", {"currency": "USD"}, new["token"])[0], 201)

    def test_user_admin_endpoints_need_the_admin_role(self):
        holder, other = self.srv.L.create_user("holder"), self.srv.L.create_user("holder")
        self.assertEqual(self.jcall("GET", "/admin/users", token=holder["token"])[0], 403)
        self.assertEqual(self.jcall("POST", f"/admin/users/{other['user_id']}/status", {"status": "disabled"}, holder["token"])[0], 403)
        self.assertEqual(self.jcall("GET", "/admin/users")[0], 401)

    def test_disabled_user_gets_401_over_http(self):
        admin, user = self.srv.L.create_user("admin")["token"], self.srv.L.create_user("holder")
        self.assertEqual(self.jcall("GET", "/me", token=user["token"])[0], 200)
        self.assertEqual(self.jcall("POST", f"/admin/users/{user['user_id']}/status", {"status": "disabled"}, admin)[0], 200)
        self.assertEqual(self.jcall("GET", "/me", token=user["token"])[0], 401)
        self.assertEqual(self.jcall("GET", "/accounts", token=user["token"])[0], 401)

    def test_signup_rejects_a_bad_display_name(self):
        self.assertEqual(self._signup("auto", "x" * 100)[0], 400)

class BootstrapScriptTests(unittest.TestCase):
    """bootstrap_admin.py run as a real command, the way an operator would run it."""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bootstrap_admin.py")

    def setUp(self): self.db = tempfile.mktemp(suffix=".db")
    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(self.db + suffix): os.remove(self.db + suffix)

    def run_script(self, **env):
        e = {k: v for k, v in os.environ.items() if k != "ADMIN_TOKEN"}
        e["LEDGER_DB"] = self.db; e.update(env)
        return subprocess.run([sys.executable, self.script], env=e, capture_output=True, text=True, timeout=60)

    def test_first_run_prints_a_generated_token_once(self):
        r = self.run_script(); self.assertEqual(r.returncode, 0)
        token = r.stdout.strip().splitlines()[-1]
        led = Ledger(self.db); self.assertEqual(led.whoami(led.authenticate(token))["role"], "admin")
        again = self.run_script()
        self.assertEqual(again.returncode, 0); self.assertIn("already exists", again.stdout)
        self.assertNotIn(token, again.stdout + again.stderr)

    def test_token_from_environment_is_used_but_never_printed(self):
        tok = "env-admin-token-0123456789"; r = self.run_script(ADMIN_TOKEN=tok)
        self.assertEqual(r.returncode, 0); self.assertNotIn(tok, r.stdout + r.stderr)
        led = Ledger(self.db); self.assertEqual(led.whoami(led.authenticate(tok))["role"], "admin")

    def test_a_short_admin_token_is_rejected(self):
        self.assertNotEqual(self.run_script(ADMIN_TOKEN="short").returncode, 0)


if __name__ == "__main__": unittest.main(verbosity=1)
