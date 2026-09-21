---
type: Runbook
title: Testing
description: How to run the test suites.
tags: [tests]
timestamp: 2026-09-21T16:00:00Z
---
Tests only run against the Firestore **emulator** (needs Java and firebase-tools; `pip install -r requirements-dev.txt`); all Python tests live in `tests/`; `conftest.py` refuses otherwise.
```bash
scripts/test.sh                    # python (server + firestore layer)
node --test tests_js/*.test.js     # client modules (sync, freshness, due, fields, reorder, service-worker routing, ...)
scripts/e2e.sh                     # engine vs. the running app + emulator (sign-in gate off via tests_js/e2e_server.py, emulator-only, outside app/ so it never ships)
```
See [stack](../architecture/stack.md).

`tests/test_item_types.py` covers the type registry and every guard; it also fails when `web/types-data.js` is stale (regenerate with `python scripts/gen_types.py`).

**Shared rule fixtures.** `tests/fixtures/tree_rules.json` lists trees with the expected `clearable` (what Clear completed deletes) and `blocked` ids. `tests/test_tree_rules.py` runs it against the server (`db.clear_completed`, `db.get_tree`) and `tests_js/tree-rules.test.js` against the client mirrors (`Sync.clearableIds`, `Fields.isBlocked`), so the two implementations cannot drift. To change either rule, change the fixture and both implementations. The client copies exist so the rules work offline; the fixture is the contract.
