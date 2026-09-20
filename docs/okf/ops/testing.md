---
type: Runbook
title: Testing
description: How to run the test suites.
tags: [tests]
timestamp: 2026-09-19T12:00:00Z
---
Tests only run against the Firestore **emulator** (needs Java and firebase-tools); `conftest.py` refuses otherwise.
```bash
scripts/test.sh                    # python (server + firestore layer)
node --test tests_js/*.test.js     # client sync engine, trash, attachments helpers
scripts/e2e.sh                     # engine vs. the running app + emulator
```
See [stack](../architecture/stack.md).
