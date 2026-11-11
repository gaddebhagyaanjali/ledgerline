# PROMPTS.md: how I used AI, and where I caught it being wrong

Tool: Claude (Anthropic), in the chat interface. I kept this log as I worked.

## Entry 1: 2026-11-07
- **What I asked:** I gave Claude the LedgerLine problem and asked it to build a safe money system.
- **What the tool produced:** A working API with accounts, deposits, withdrawals and transfers.
- **What was wrong (authorisation):** Any logged-in user could deposit money into their own account, so anyone could create free money.
- **How it was found:** I pasted the marking rules and asked Claude to check its code against them. Claude found this problem, not me.
- **What I did instead:** Only admins can deposit now. I added three roles: admin, holder and auditor. Commit `b3a732b`. Test: `test_holders_cannot_print_money`.

## Entry 2: 2026-11-07
- **What I asked:** To check what a judge could break on the live system.
- **What the tool produced:** A `/reconcile` page protected by a default admin key, the word `admin`.
- **What was wrong (access control):** Anyone could guess that key.
- **What I did instead:** I removed the default key. The admin now logs in with a long secret token from a setting (`ADMIN_TOKEN`, at least 16 characters). I checked that `/reconcile` returns 403 for no token, for `admin`, and for an ordinary user. Commit `b3a732b`.

## Entry 3: 2026-11-07
- **What I asked:** Who can see the audit log of transactions?
- **What the tool produced:** An audit log table that can't be edited or deleted.
- **What was wrong (audit trail):** Nobody could read it. There was no page for it and no auditor role.
- **What I did instead:** I added a read-only auditor role and a `/audit` page that only auditors and admins can open. Holders get 403. Commit `b3a732b`. Test: `test_auditor_is_read_only_but_sees_everything`.

## Entry 4: 2026-11-08
- **What I asked:** To attack the running server with many requests at once.
- **What the tool produced:** A web server with Python's default settings.
- **What was wrong:** In a test with 60 requests at once, 3 were dropped with "Connection reset". No money was affected, but it looks like a failure.
- **What I did instead:** I raised the server's connection queue from 5 to 256. A new test with 200 requests dropped none, and the books still balanced. Commit `0a09067`.

## Entry 5: 2026-11-07
- **What I asked:** How to run the project in VS Code and save it to GitHub.
- **What the tool produced:** Commands using `python`, and git steps with no name or email.
- **What was wrong:** My Mac only has `python3`, so I got `command not found: python`. My first commit also failed with "Author identity unknown".
- **What I did instead:** I used `python3`, set my git name and email, and committed again.

## Entry 6: 2026-11-08
- **What I asked:** How to put my project on GitHub.
- **What the tool produced:** Advice to make the repo public.
- **What was wrong:** The assessment says not to make it public before the deadline.
- **What I did instead:** After I pasted the rules, Claude said its advice was wrong. I made the repo private and plan to ask my placement cell about public versus private.

## Entry 7: 2026-11-08
- **What I asked:** After one 5.00 transfer in the dashboard, the balances did not match what I expected, and I asked Claude why.
- **What the tool produced:** Claude guessed it was an extra transfer from my testing, then ran a clean test on its own copy: one 5.00 transfer, one resend, and the books balanced.
- **What was wrong:** Claude could not tell from my screenshot what had happened, so its first answer was only a guess.
- **What I did instead:** I ran Reconcile, which said the books balance. Claude's clean test, one 5.00 transfer plus one resend, also gave the right balances. I never saw what caused my first odd numbers, so I treat that as unexplained, probably an extra test transfer.

## Entry 8: 2026-11-08
- **What I asked:** I asked Claude for a full progress review and told it to check the real code instead of assuming things were done.
- **What the tool produced:** A report listing security gaps, then Claude re-checked each one against the code. It confirmed that failed logins and denied reads left no trace in the audit log.
- **What was wrong (audit trail):** Someone guessing tokens or probing other people's accounts left no record. Claude also admitted two of its own checks were sloppy (one printed "True" without testing anything) and redid them properly.
- **What I did instead:** I had Claude fix one issue at a time, with tests. Refused logins, reads and admin-page attempts are now audited. Five of the six new tests fail on the old code, which shows they test the fix. Commit `6e2f5aa`.

## Entry 9: 2026-11-09
- **What I asked:** I told Claude to stop an admin from minting money into their own account, and to explain, test and wait for my review.
- **What the tool produced:** It first reproduced the problem on the current code: an admin opened an account, funded it with 5,000.00 and withdrew it, and the books still balanced. While inspecting, it also found that an admin could deposit into the system account.
- **What was wrong (authorisation):** The first design let admins own accounts and let deposits land anywhere. One of Claude's own new tests was also wrong (it expected the wrong error for a missing account); the test run showed the mistake and Claude fixed the test, not the code.
- **What I did instead:** Admins and auditors can no longer open accounts, and deposits are refused unless the destination belongs to a holder. Four of the five new tests fail on the old code. An admin can still fund a second identity they control; I recorded that as a known gap in THREATS.md. Commit `15c292d`.

## Entry 10: 2026-11-10
- **What I asked:** Implement a secure first-administrator bootstrap process that handles both manual token specification and automatic generation without leaving stale credentials.
- **What the tool produced:** A standalone bootstrap script and `bootstrap_admin` ledger method.
- **What was wrong (credential management):** Initial implementation did not revoke older bootstrap administrators when `ADMIN_TOKEN` was updated, meaning an old administrator token remained valid after a password/secret rotation.
- **What I did instead:** Added logic in `bootstrap_admin()` to mark all older bootstrap accounts as `disabled` whenever a new token is bootstrapped. Also added validation ensuring tokens are at least 16 characters and generated tokens are output strictly once. 8 automated tests added. Commit `54c005a`.

## Entry 11: 2026-11-11
- **What I asked:** Add user onboarding workflows (`pending`, `active`, `disabled`), public registration with display names, and administrative user controls to approve or revoke users.
- **What the tool produced:** Database migration for user status, API endpoints `GET /admin/users` and `POST /admin/users/{id}/status`, and `ONBOARDING_MODE` (`auto` or `manual`).
- **What was wrong (user experience & security):** Newly registered pending users in manual mode received generic 401 unauthenticated errors instead of a clear pending approval state, and administrators could inadvertently disable their own account.
- **What I did instead:** Allowed pending users to call `/me` to inspect their status while blocking all financial operations with 403, prevented admins from disabling themselves, added comprehensive audit logging for all status changes, and built a User Management & Onboarding panel in `index.html`. Total automated tests expanded to 63. Commit `54c005a`.

## What I checked myself
- I ran all 63 automated tests and the 23-step demo script on my own computer, and they passed.

## What I would not trust the AI on without checking
Concurrency claims (I check them with the thread tests), deployment settings, and anything touching security defaults.
