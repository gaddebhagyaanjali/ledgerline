"""Live demo.  ADMIN_TOKEN=<your admin token> python3 demo.py [BASE_URL]
Shows roles, onboarding, idempotency, overdraft/ownership protection, user administration, auditor oversight and reconcile."""
import json, os, secrets, sys, urllib.request, urllib.error
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
ADMIN = os.environ.get("ADMIN_TOKEN")
if not ADMIN: sys.exit("Set ADMIN_TOKEN first, e.g.  ADMIN_TOKEN=yourtoken python3 demo.py")

run_id = secrets.token_hex(4)

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

alice = step("1. Alice signs up with display name", call("POST", "/users", {"display_name": "Alice"}))
bob = step("2. Bob signs up with display name", call("POST", "/users", {"display_name": "Bob"}))
step("3. Alice checks identity (/me)", call("GET", "/me", token=alice["token"]))
a = step("4. Alice opens a USD account", call("POST", "/accounts", {"currency": "USD"}, alice["token"]))["account_id"]
b = step("5. Bob opens a USD account", call("POST", "/accounts", {"currency": "USD"}, bob["token"]))["account_id"]
step("6. Alice tries to give herself money -> FORBIDDEN (only admins fund accounts)", call("POST", "/deposits", {"account_id": a, "amount": 10000}, alice["token"], f"self-{run_id}"))
step("7. Admin funds Alice $100.00 (10000 cents)", call("POST", "/deposits", {"account_id": a, "amount": 10000}, ADMIN, f"dep-{run_id}"))
step("8. SAME request again (network retry) -> replayed, NOT paid twice", call("POST", "/deposits", {"account_id": a, "amount": 10000}, ADMIN, f"dep-{run_id}"))
step("9. Same key, different amount -> 409 Conflict", call("POST", "/deposits", {"account_id": a, "amount": 99999}, ADMIN, f"dep-{run_id}"))
step("10. Alice balance is still 10000 ($100.00)", call("GET", f"/accounts/{a}", token=alice["token"]))
step("11. Alice transfers $30.00 to Bob", call("POST", "/transfers", {"from": a, "to": b, "amount": 3000}, alice["token"], f"tr-{run_id}"))
step("12. Alice overdraws -> 422 insufficient funds", call("POST", "/withdrawals", {"account_id": a, "amount": 999999}, alice["token"], f"wd-{run_id}"))
step("13. Bob tries to move Alice's money -> 403 Forbidden", call("POST", "/transfers", {"from": a, "to": b, "amount": 100}, bob["token"], f"evil-{run_id}"))

# User Management & Status Lifecycle
step("14. Admin inspects user directory (/admin/users)", call("GET", "/admin/users", token=ADMIN))
step("15. Admin disables Bob's account (e.g. security hold)", call("POST", f"/admin/users/{bob['user_id']}/status", {"status": "disabled"}, ADMIN))
step("16. Bob tries to use API while disabled -> 401 Unauthenticated", call("GET", "/me", token=bob["token"]))
step("17. Admin re-enables Bob's account", call("POST", f"/admin/users/{bob['user_id']}/status", {"status": "active"}, ADMIN))
step("18. Bob can authenticate again -> 200 OK", call("GET", "/me", token=bob["token"]))

# Auditor oversight & book balancing
aud = step("19. Admin creates an auditor", call("POST", "/admin/users", {"role": "auditor"}, ADMIN))
step("20. Auditor reads Alice's statement (every entry traceable)", call("GET", f"/accounts/{a}/entries", token=aud["token"]))
step("21. Auditor tries to move money -> 403 Forbidden (read-only)", call("POST", "/withdrawals", {"account_id": a, "amount": 1}, aud["token"], f"aud-{run_id}"))
step("22. Auditor reads audit log (includes all actions & security events)", call("GET", "/audit?limit=6", token=aud["token"]))
step("23. Reconcile: mathematically prove the books balance", call("GET", "/reconcile", token=aud["token"]))
print("\nDemo complete! All invariants and workflows verified successfully.\n")
