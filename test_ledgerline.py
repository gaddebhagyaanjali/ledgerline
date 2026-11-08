import os, tempfile, sqlite3, threading, unittest
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

if __name__ == "__main__": unittest.main(verbosity=1)
