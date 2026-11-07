"""Thin HTTP/JSON layer over Ledger. Run: python server.py  (port 8000)"""
import json, os, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ledger import Ledger, LedgerError, ValidationError

L = Ledger(os.environ.get("LEDGER_DB", "ledgerline.db"))
ADMIN_KEY = os.environ.get("ADMIN_KEY", "admin")

class H(BaseHTTPRequestHandler):
    def _send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try: return json.loads(self.rfile.read(n) or b"{}")
        except ValueError: raise ValidationError("invalid JSON")

    def _user(self):
        auth = self.headers.get("Authorization", "")
        return L.authenticate(auth[7:] if auth.startswith("Bearer ") else None)

    def _handle(self, method):
        try:
            p = self.path.split("?")[0]
            if method == "POST" and p == "/users":
                return self._send(201, L.create_user())
            if method == "GET" and p == "/reconcile":
                if self.headers.get("X-Admin-Key") != ADMIN_KEY:
                    return self._send(403, {"error": "forbidden"})
                return self._send(200, L.reconcile())
            u = self._user()
            key = self.headers.get("Idempotency-Key")
            if method == "POST" and p == "/accounts":
                return self._send(201, L.create_account(u, self._body().get("currency")))
            if method == "POST" and p == "/deposits":
                b = self._body(); return self._send(201, L.deposit(u, key, b.get("account_id"), b.get("amount")))
            if method == "POST" and p == "/withdrawals":
                b = self._body(); return self._send(201, L.withdraw(u, key, b.get("account_id"), b.get("amount")))
            if method == "POST" and p == "/transfers":
                b = self._body(); return self._send(201, L.transfer(u, key, b.get("from"), b.get("to"), b.get("amount")))
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
    port = int(os.environ.get("PORT", 8000))
    print(f"LedgerLine on port {port}")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
