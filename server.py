"""Thin HTTP/JSON layer over Ledger.   python server.py
Env: PORT (8000), LEDGER_DB, ADMIN_TOKEN (>=16 chars; creates the admin user), SEED_DEMO=1 (demo data)."""
import base64, hashlib, json, os, re, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from ledger import Ledger, LedgerError, ValidationError

L = Ledger(os.environ.get("LEDGER_DB", "ledgerline.db"))
MAX_BODY = 16 * 1024

def _load_page():
    html = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html"), "rb").read()
    js = re.search(rb"<script>(.*?)</script>", html, re.S).group(1)
    digest = base64.b64encode(hashlib.sha256(js).digest()).decode()
    csp = ("default-src 'none'; script-src 'sha256-%s'; style-src 'unsafe-inline'; connect-src 'self'; "
           "base-uri 'none'; form-action 'none'; frame-ancestors 'none'" % digest)
    return html, csp
PAGE, PAGE_CSP = _load_page()

def bootstrap():
    tok = os.environ.get("ADMIN_TOKEN", "")
    if not tok:
        print("WARNING: ADMIN_TOKEN not set: no administrator exists, deposits are impossible."); return
    if len(tok) < 16:
        sys.exit("ADMIN_TOKEN must be at least 16 characters")
    admin_id = L.ensure_user(tok, "admin")
    if os.environ.get("SEED_DEMO") == "1":
        L.seed_demo(admin_id); print("Demo data seeded (demo-alice-token, demo-bob-token, demo-auditor-token).")

class H(BaseHTTPRequestHandler):
    def _send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def _send_page(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.send_header("Content-Security-Policy", PAGE_CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(PAGE)

    def _body(self):
        try: n = int(self.headers.get("Content-Length") or 0)
        except ValueError: raise ValidationError("bad Content-Length")
        if n < 0 or n > MAX_BODY: raise ValidationError("request body too large")
        try: body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError: raise ValidationError("invalid JSON")
        if not isinstance(body, dict): raise ValidationError("JSON body must be an object")
        return body

    def _user(self):
        auth = self.headers.get("Authorization", "")
        return L.authenticate(auth[7:] if auth.startswith("Bearer ") else None)

    def _handle(self, method):
        try:
            sp = urlsplit(self.path); p = sp.path
            if method == "GET" and p in ("/", "/index.html"):
                return self._send_page()
            if method == "POST" and p == "/users":          # public signup: account holders only
                return self._send(201, L.create_user("holder"))
            u = self._user()
            key = self.headers.get("Idempotency-Key")
            if method == "GET" and p == "/me":
                return self._send(200, L.whoami(u))
            if method == "POST" and p == "/admin/users":
                return self._send(201, L.admin_create_user(u, self._body().get("role")))
            if method == "POST" and p == "/accounts":
                return self._send(201, L.create_account(u, self._body().get("currency")))
            if method == "GET" and p == "/accounts":
                return self._send(200, L.list_accounts(u))
            if method == "POST" and p == "/deposits":
                b = self._body(); return self._send(201, L.deposit(u, key, b.get("account_id"), b.get("amount")))
            if method == "POST" and p == "/withdrawals":
                b = self._body(); return self._send(201, L.withdraw(u, key, b.get("account_id"), b.get("amount")))
            if method == "POST" and p == "/transfers":
                b = self._body(); return self._send(201, L.transfer(u, key, b.get("from"), b.get("to"), b.get("amount")))
            if method == "GET" and p == "/audit":
                lim = parse_qs(sp.query).get("limit", ["100"])[0]
                if not lim.isdigit(): raise ValidationError("limit must be a number")
                return self._send(200, L.audit_entries(u, int(lim)))
            if method == "GET" and p == "/reconcile":
                return self._send(200, L.reconcile(u))
            m = re.fullmatch(r"/accounts/(\w+)(/entries)?", p)
            if method == "GET" and m:
                return self._send(200, L.statement(u, m[1]) if m[2] else L.get_account(u, m[1]))
            self._send(404, {"error": "not_found"})
        except LedgerError as e:
            self._send(e.status, {"error": e.code, "message": str(e)})
        except Exception:
            self._send(500, {"error": "internal_error"})

    def do_GET(self): self._handle("GET")
    def do_POST(self): self._handle("POST")
    def log_message(self, *a): pass

if __name__ == "__main__":
    bootstrap()
    port = int(os.environ.get("PORT", 8000))
    print(f"LedgerLine on port {port}")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
