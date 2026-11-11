"""First-administrator bootstrap.   python3 bootstrap_admin.py

* ADMIN_TOKEN set (16+ characters): make sure that administrator exists and is active, and revoke every
  older bootstrap administrator. The token is never printed.
* ADMIN_TOKEN not set: if the system has no active administrator yet, create one and print its token ONCE.
  If an administrator already exists, do nothing.
Uses the database named by LEDGER_DB (default ledgerline.db), the same as server.py."""
import os, secrets, sys
from ledger import Ledger


def main():
    ledger = Ledger(os.environ.get("LEDGER_DB", "ledgerline.db"))
    token = os.environ.get("ADMIN_TOKEN", "")
    if token:
        if len(token) < 16:
            sys.exit("ADMIN_TOKEN must be at least 16 characters")
        r = ledger.bootstrap_admin(token)
        print("Administrator", "created" if r["created"] else "already exists and is active",
              "| older bootstrap admins revoked:", r["revoked"], "| (token not shown)")
        return
    if ledger.has_active_admin():
        print("An administrator already exists. Nothing to do. (Set ADMIN_TOKEN to define or replace the bootstrap admin.)")
        return
    token = secrets.token_urlsafe(32)
    ledger.bootstrap_admin(token)
    print("First administrator created. Save this token now; it is shown only once:")
    print(token)


if __name__ == "__main__":
    main()
