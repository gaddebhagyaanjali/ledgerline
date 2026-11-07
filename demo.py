"""Live demo against a running server.  Usage: python demo.py [BASE_URL]
Shows: accounts, deposit, idempotent retry, double-spend protection, authorisation, reconcile."""
import json, sys, urllib.request, urllib.error
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")

def call(method, path, body=None, token=None, key=None, admin=None):
    h = {"Content-Type": "application/json"}
    if token: h["Authorization"] = "Bearer " + token
    if key: h["Idempotency-Key"] = key
    if admin: h["X-Admin-Key"] = admin
    req = urllib.request.Request(BASE + path, method=method, headers=h,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req) as r: return r.status, json.load(r)
    except urllib.error.HTTPError as e: return e.code, json.load(e)

def step(title, res):
    print(f"\n>>> {title}\n    HTTP {res[0]}  {json.dumps(res[1])}")
    input("    [press Enter]") if sys.stdin.isatty() else None
    return res[1]

alice = step("1. Create user Alice", call("POST", "/users"))
bob = step("2. Create user Bob", call("POST", "/users"))
a = step("3. Alice opens a USD account", call("POST", "/accounts", {"currency": "USD"}, alice["token"]))["account_id"]
b = step("4. Bob opens a USD account", call("POST", "/accounts", {"currency": "USD"}, bob["token"]))["account_id"]
step("5. Alice deposits $100.00 (10000 cents)", call("POST", "/deposits", {"account_id": a, "amount": 10000}, alice["token"], "dep-1"))
step("6. SAME request again (network retry) -> replayed, NOT paid twice", call("POST", "/deposits", {"account_id": a, "amount": 10000}, alice["token"], "dep-1"))
step("7. Same key, different amount -> rejected", call("POST", "/deposits", {"account_id": a, "amount": 99999}, alice["token"], "dep-1"))
step("8. Alice balance is still 10000", call("GET", f"/accounts/{a}", token=alice["token"]))
step("9. Alice transfers $30.00 to Bob", call("POST", "/transfers", {"from": a, "to": b, "amount": 3000}, alice["token"], "tr-1"))
step("10. Alice tries to withdraw more than she has -> rejected", call("POST", "/withdrawals", {"account_id": a, "amount": 999999}, alice["token"], "wd-1"))
step("11. Bob tries to move Alice's money -> forbidden", call("POST", "/transfers", {"from": a, "to": b, "amount": 100}, bob["token"], "evil-1"))
step("12. Alice's statement (every entry traceable)", call("GET", f"/accounts/{a}/entries", token=alice["token"]))
step("13. Reconcile: prove the books balance", call("GET", "/reconcile", admin="admin"))
