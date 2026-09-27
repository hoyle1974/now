#!/bin/bash
# One-time setup for sharing between users (docs/okf/features/sharing.md): the Firestore
# TTL policy that expires per-member view state (users/{email}/view_state/{share_id},
# field expires_at, 90 days after the last collapse/expand). TTL deletes are free and
# only remove a member's fold state. Idempotent. Turning sharing on is separate:
# SHARING_ENABLED=1 ./deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib/config.sh

gcloud firestore fields ttls update expires_at --collection-group=view_state \
  --enable-ttl --database='(default)' --project "$PROJECT" --async
echo "TTL on view_state.expires_at requested (takes a few minutes to become active)."
