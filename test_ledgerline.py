import os, tempfile, sqlite3, threading, unittest
from ledger import *

class T(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".db"); self.L = Ledger(self.path)
        self.alice = self.L.create_user()["user_id"]; self.bob = self.L.create_user()["user_id"]
        self.a = self.L.create_account(self.alice, "USD")["account_id"]
        self.b = self.L.create_account(self.bob, "USD")["account_id"]
    def tearDown(self): os.path.exists(self.path) and os.remove(self.path)
    def bal(self, u, a): return self.L.get_account(u, a)["balance"]

    def test_basic_flow_balances(self):
        self.L.deposit(self.alice, "d1", self.a, 1000)
        self.L.transfer(self.alice, "t1", self.a, self.b, 300)
        self.L.withdraw(self.bob, "w1", self.b, 100)
        self.assertEqual((self.bal(self.alice, self.a), self.bal(self.bob, self.b)), (700, 200))
        self.assertTrue(self.L.reconcile()["ok"])

    def test_idempotent_replay_returns_same_result_once(self):
        r1 = self.L.deposit(self.alice, "k", self.a, 500)
        r2 = self.L.deposit(self.alice, "k", self.a, 500)
        self.assertEqual(r1["transaction_id"], r2["transaction_id"]); self.assertTrue(r2["replayed"])
        self.assertEqual(self.bal(self.alice, self.a), 500)

    def test_key_reuse_with_different_payload_rejected(self):
        self.L.deposit(self.alice, "k", self.a, 500)
        with self.assertRaises(IdempotencyConflict): self.L.deposit(self.alice, "k", self.a, 600)

    def test_concurrent_duplicate_requests_pay_once(self):
        self.L.deposit(self.alice, "seed", self.a, 1000)
        res = []
        def go(): res.append(self.L.transfer(self.alice, "same", self.a, self.b, 100)["transaction_id"])
        ts = [threading.Thread(target=go) for _ in range(20)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(len(set(res)), 1)
        self.assertEqual(self.bal(self.bob, self.b), 100)

    def test_concurrent_withdrawals_cannot_double_spend(self):
        self.L.deposit(self.alice, "seed", self.a, 100)
        ok, fail = [], []
        def go(i):
            try: self.L.withdraw(self.alice, f"w{i}", self.a, 100); ok.append(i)
            except InsufficientFunds: fail.append(i)
        ts = [threading.Thread(target=go, args=(i,)) for i in range(15)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual((len(ok), len(fail)), (1, 14))
        self.assertEqual(self.bal(self.alice, self.a), 0); self.assertTrue(self.L.reconcile()["ok"])

    def test_cannot_move_money_from_someone_elses_account(self):
        self.L.deposit(self.bob, "s", self.b, 500)
        with self.assertRaises(Forbidden): self.L.transfer(self.alice, "x", self.b, self.a, 100)
        with self.assertRaises(Forbidden): self.L.get_account(self.alice, self.b)
        self.assertEqual(self.bal(self.bob, self.b), 500)

    def test_overdraft_and_bad_amounts_rejected(self):
        with self.assertRaises(InsufficientFunds): self.L.withdraw(self.alice, "o", self.a, 1)
        for bad in (0, -5, 1.5, "10", True):
            with self.assertRaises(ValidationError): self.L.deposit(self.alice, "b", self.a, bad)

    def test_currency_mismatch_and_self_transfer(self):
        eur = self.L.create_account(self.bob, "EUR")["account_id"]
        self.L.deposit(self.alice, "s", self.a, 100)
        with self.assertRaises(ValidationError): self.L.transfer(self.alice, "m", self.a, eur, 10)
        with self.assertRaises(ValidationError): self.L.transfer(self.alice, "s2", self.a, self.a, 10)

    def test_failed_transfer_leaves_no_partial_state(self):
        self.L.deposit(self.alice, "s", self.a, 50)
        with self.assertRaises(InsufficientFunds): self.L.transfer(self.alice, "f", self.a, self.b, 80)
        self.assertEqual((self.bal(self.alice, self.a), self.bal(self.bob, self.b)), (50, 0))
        self.assertTrue(self.L.reconcile()["ok"])

    def test_ledger_is_immutable_and_tampering_detected(self):
        self.L.deposit(self.alice, "s", self.a, 50)
        c = sqlite3.connect(self.path)
        for sql in ("UPDATE entries SET amount=999", "DELETE FROM entries", "DELETE FROM audit_log"):
            with self.assertRaises(sqlite3.DatabaseError): c.execute(sql)
        c.execute("UPDATE accounts SET balance=9999 WHERE id=?", (self.a,)); c.commit(); c.close()
        self.assertFalse(self.L.reconcile()["ok"])   # tampered cached balance is caught

    def test_rejected_attempts_are_audited(self):
        with self.assertRaises(InsufficientFunds): self.L.withdraw(self.alice, "z", self.a, 10)
        c = sqlite3.connect(self.path)
        self.assertEqual(c.execute("SELECT outcome FROM audit_log").fetchone()[0], "rejected:insufficient_funds")

    def test_bad_token(self):
        with self.assertRaises(Unauthenticated): self.L.authenticate("nope")

if __name__ == "__main__": unittest.main(verbosity=2)
