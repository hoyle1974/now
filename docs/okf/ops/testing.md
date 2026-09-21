---
type: Runbook
title: Testing
description: How to run the test suites.
tags: [tests]
timestamp: 2026-09-21T03:00:00Z
---
Tests only run against the Firestore **emulator** (needs Java and firebase-tools; `pip install -r requirements-dev.txt`); all Python tests live in `tests/`; `conftest.py` refuses otherwise.
```bash
scripts/test.sh                    # python (server + firestore layer)
node --test tests_js/*.test.js     # client modules (sync, freshness, due, fields, reorder, service-worker routing, ...)
scripts/e2e.sh                     # engine vs. the running app + emulator (sign-in gate off via tests_js/e2e_server.py, emulator-only, outside app/ so it never ships)
```
See [stack](../architecture/stack.md).
