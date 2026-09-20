#!/bin/sh
# Post-commit reminder: warn when code changed but docs/okf/ did not.
# Never blocks (post-commit can't); output only. Called from .git/hooks/post-commit.
CHANGED=$(git diff --name-only HEAD~1 HEAD 2>/dev/null || git show --name-only --pretty=format: HEAD 2>/dev/null)
[ -z "$CHANGED" ] && exit 0
echo "$CHANGED" | grep -q '^docs/okf/' && exit 0
CODE=$(echo "$CHANGED" | grep -E '^(app/|web/|scripts/|deploy\.sh|Dockerfile|firebase\.json|firestore\.)' | grep -v '^scripts/okf-reminder\.sh$')
[ -z "$CODE" ] && exit 0
echo "" >&2
echo "OKF reminder: this commit changed code but not docs/okf/." >&2
echo "If it was a major change (behaviour, data model, API, sync, deploy, testing), update the bundle and log.md." >&2
exit 0
