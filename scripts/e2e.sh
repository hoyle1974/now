#!/bin/bash
# Boots the app against the Firestore emulator (never production) and runs the
# sync-engine end-to-end script against it.
cd "$(dirname "$0")/.." || exit 1
exec firebase emulators:exec --only firestore --project demo-now-test '
  GOOGLE_CLOUD_PROJECT=demo-now-test SHARING_ENABLED=1 ALLOWED_EMAILS="e2e@example.com;e2e-kid@example.com" \
    .venv/bin/uvicorn tests_js.e2e_server:app --port 8081 >/tmp/now-e2e.log 2>&1 &
  PID=$!
  for i in $(seq 1 40); do curl -sf localhost:8081/health >/dev/null && break; sleep 0.5; done
  BASE=http://localhost:8081 node tests_js/e2e.js && BASE=http://localhost:8081 node tests_js/e2e-share.js
  STATUS=$?
  kill $PID
  exit $STATUS
'
