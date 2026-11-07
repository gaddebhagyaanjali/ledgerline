"""Live demo.  ADMIN_TOKEN=<your admin token> python3 demo.py [BASE_URL]
Shows roles, idempotency, overdraft/ownership protection, auditor oversight and reconcile."""
import json, os, sys, urllib.request, urllib.error
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
ADMIN = os.environ.get("ADMIN_TOKEN")
if not ADMIN: sys.exit("Set ADMIN_TOKEN first, e.g.  ADMIN_TOKEN=yourtoken python3 demo.py")

def call(method, path, body=None, token=None, key=None):
    h = {"Content-Type": "application/json"}
    if token: h["Authorization"] = "Bearer " + token
    if key: h["Idempotency-Key"] = key
    req = urllib.request.Request(BASE + path, method=method, headers=h,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req) as r: return r.status, json.load(r)
    except urllib.error.HTTPError as e: return e.code, json.load(e)

def step(title, res):
    print(f"\n>>> {title}\n    HTTP {res[0]}  {json.dumps(res[1])[:230]}")
    if sys.stdin.isatty(): input("    [press Enter]")
    return res[1]

alice = step("1. Alice signs up (public signup = account holder)", call("POST", "/users"))
bob = step("2. Bob signs up", call("POST", "/users"))
a = step("3. Alice opens a USD account", call("POST", "/accounts", {"currency": "USD"}, alice["token"]))["account_id"]
b = step("4. Bob opens a USD account", call("POST", "/accounts", {"currency": "USD"}, bob["token"]))["account_id"]
step("5. Alice tries to give herself money -> FORBIDDEN (only admins fund accounts)", call("POST", "/deposits", {"account_id": a, "amount": 10000}, alice["token"], "self-1"))
step("6. Admin funds Alice $100.00 (10000 cents)", call("POST", "/deposits", {"account_id": a, "amount": 10000}, ADMIN, "dep-1"))
step("7. SAME request again (network retry) -> replayed, NOT paid twice", call("POST", "/deposits", {"account_id": a, "amount": 10000}, ADMIN, "dep-1"))
step("8. Same key, different amount -> 409", call("POST", "/deposits", {"account_id": a, "amount": 99999}, ADMIN, "dep-1"))
step("9. Alice balance is still 10000", call("GET", f"/accounts/{a}", token=alice["token"]))
step("10. Alice transfers $30.00 to Bob", call("POST", "/transfers", {"from": a, "to": b, "amount": 3000}, alice["token"], "tr-1"))
step("11. Alice overdraws -> 422 insufficient funds", call("POST", "/withdrawals", {"account_id": a, "amount": 999999}, alice["token"], "wd-1"))
step("12. Bob tries to move Alice's money -> 403", call("POST", "/transfers", {"from": a, "to": b, "amount": 100}, bob["token"], "evil-1"))
aud = step("13. Admin creates an auditor", call("POST", "/admin/users", {"role": "auditor"}, ADMIN))
step("14. Auditor reads Alice's statement (every entry traceable)", call("GET", f"/accounts/{a}/entries", token=aud["token"]))
step("15. Auditor tries to move money -> 403 (read-only)", call("POST", "/withdrawals", {"account_id": a, "amount": 1}, aud["token"], "aud-1"))
step("16. Auditor reads the audit log (includes rejected attempts)", call("GET", "/audit?limit=5", token=aud["token"]))
step("17. Reconcile: prove the books balance", call("GET", "/reconcile", token=aud["token"]))
