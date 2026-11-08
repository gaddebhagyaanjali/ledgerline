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
- **What I asked:** I asked Claude to check my build against the evaluation and rejection rules.
- **What the tool produced:** Claude ran its own attack test on the running server, with 60 requests at once. The server used Python's default settings.
- **What was wrong:** In that test, 3 requests were dropped with "Connection reset". No money was affected, but a judge's burst test would look like failures.
- **What I did instead:** Claude raised the server's connection queue from 5 to 256. I applied the change, ran my 22 tests and pushed it. A new 200-request test dropped none, and the books still balanced. Commit `0a09067`.

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
- **What I did instead:** I checked the account statements, which list every entry, and ran Reconcile, which said the books balance. The transactions were all correct.

## What I checked myself
- I ran 22 automated tests and the 17-step demo script on my own computer, and they passed.

## What I would not trust the AI on without checking
Concurrency claims (I check them with the thread tests), deployment settings, and anything touching security defaults.
