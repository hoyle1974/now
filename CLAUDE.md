# now — project rules

## Keep the OKF bundle in sync (required)

`docs/okf/` is the curated knowledge base (Open Knowledge Format v0.1) and is checked in. Rules are in `docs/okf/index.md`; in short:

- After any **major change** (behaviour, data model, API route, sync protocol, deploy, testing, new feature), update the affected `docs/okf/` files **in the same commit** and bump their `timestamp`.
- Append a dated line to `docs/okf/log.md` for every update.
- New concept = new file with a `type` frontmatter field, linked from `docs/okf/index.md`.
- If the bundle disagrees with the code, the code wins: fix the bundle.
- Before committing, check whether the change needs an OKF update; if not, that is fine, but decide explicitly.
- `README.md` stays the human quick-start; do not duplicate detail there that belongs in the bundle.

## graphify

`graphify-out/` is git-ignored and rebuilt by a local post-commit hook (`graphify hook install` after a fresh clone). The hook covers code only; run `/graphify . --update` after doc or image changes. Consult the graph for codebase questions when it exists.

## OKF commit reminder

`scripts/okf-reminder.sh` (tracked) is called from a local `.git/hooks/post-commit` block marked `okf-reminder-start/end`, placed *above* graphify's block (which has early exits). It only prints a warning when a commit touches code but not `docs/okf/`. After a fresh clone, re-add that block (and run `graphify hook install`).
