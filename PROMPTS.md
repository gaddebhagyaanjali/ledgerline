# PROMPTS.md: how I used AI, and where I caught it

> Replace the bracketed parts with your real experience. Only keep entries that actually happened.

## Tool used
Claude (Anthropic) in the chat interface.

## How I directed it
1. **Initial prompt:** I pasted the LedgerLine brief. [Paste your own prompt text here.]
2. **My follow-ups:** [e.g. "run it in VS Code", "how do I deploy", "what are the marking criteria" ...]
3. **Changes I asked for after reading the output:** [e.g. security review once I saw the marking scheme.]

## Where the AI was wrong or unsafe, and what I did
| What went wrong | How I noticed | What I did |
|---|---|---|
| It told me to run `python ...`, which does not exist on macOS | Terminal said `zsh: command not found: python` | Used `python3` |
| Git instructions skipped setting identity | The first commit failed: "Author identity unknown" (seen in the VS Code git log) | Ran `git config --global user.name/user.email`, re-committed |
| The first version had a default admin key (`"admin"`), and any user could deposit into their own account | [Your own notes: e.g. on reviewing security against the marking scheme, a judge could guess it] | Replaced with real roles: admin token from env (no default, 16+ chars), admin-only deposits, auditor role |
| No cap on amounts or request size | Reviewed against "what can a judge break" | Added `MAX_AMOUNT`, a 16 KB body limit, and tests |
| [Add anything else you personally caught] | | |

## What I verified myself
- Ran 22 tests locally; ran `demo.py` against my local server and the deployed URL.
- [Add: read ledger.py and can explain the locking, the idempotency flow and the reconcile query.]

## What I would not trust the AI on without checking
Concurrency claims (I check them with the thread tests), deployment settings, and anything touching security defaults.
