#!/bin/bash
# Bring a fresh GCP/Firebase project (e.g. one made with zilch-gcp) to a working
# deployment of this app. Idempotent: every step checks before it changes anything.
#
#   scripts/init.sh --dry-run    # print what would change, change nothing
#   scripts/init.sh              # ask once, then do it
#   scripts/init.sh --push       # also set up push reminders (Scheduler job, IAM)
#   scripts/init.sh --widget     # also create the lock screen widget token (Secret Manager)
#   scripts/init.sh --calendar   # also create the private calendar feed (scripts/setup-calendar.sh)
# Cost guards (image cleanup policy + monthly budget alert, scripts/setup-cost-guards.sh) always run.
#
# Prerequisites: gcloud and firebase logged in; a project with billing and a Firestore
# database (zilch creates both); a Firebase project on it (console: "Add Firebase").
# Settings come from scripts/lib/config.sh; ALLOWED_EMAILS from the environment,
# .now.env, or a prompt. Finish with scripts/doctor.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib/config.sh

DRY=0; PUSH=0; WIDGET=0; CALENDAR=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --push) PUSH=1 ;;
    --widget) WIDGET=1 ;;
    --calendar) CALENDAR=1 ;;
    *) echo "usage: $0 [--dry-run] [--push] [--widget] [--calendar]" >&2; exit 2 ;;
  esac
done

say()  { printf '\n== %s\n' "$*"; }
run()  { if [ "$DRY" = 1 ]; then printf '   [dry-run] %s\n' "$*"; else "$@"; fi; }

HOSTING_SITE="${HOSTING_SITE:-$(_cfg .now.env HOSTING_SITE)}"
HOSTING_SITE="${HOSTING_SITE:-$(_cfg .zilch.config app_name)}"
HOSTING_SITE="${HOSTING_SITE:-$SERVICE}"
ALLOWED_EMAILS="${ALLOWED_EMAILS:-${ALLOWED_EMAIL:-$(_cfg .now.env ALLOWED_EMAILS)}}"
ALLOWED_EMAILS="${ALLOWED_EMAILS:-$(_cfg .now.env ALLOWED_EMAIL)}"

echo "project=$PROJECT region=$REGION service=$SERVICE hosting site=$HOSTING_SITE"
if [ -z "$ALLOWED_EMAILS" ]; then
  if [ "$DRY" = 1 ]; then ALLOWED_EMAILS="(you@example.com)"
  else read -r -p "Google accounts allowed to sign in (first is the owner, separate with ;): " ALLOWED_EMAILS; fi
fi
[ -n "$ALLOWED_EMAILS" ] || { echo "ALLOWED_EMAILS is required" >&2; exit 1; }
export ALLOWED_EMAILS

if [ "$DRY" = 0 ]; then
  read -r -p "This changes project $PROJECT (Firebase app, Hosting, Cloud Run, bucket). Continue? [y/N] " yn
  [ "$yn" = y ] || { echo "aborted"; exit 1; }
fi

say "1/6 Firebase web app and client config (web/config.js)"
if [ -f web/config.js ]; then
  echo "   web/config.js exists, leaving it (delete it to regenerate)"
else
  app_id="$(firebase apps:list WEB --project "$PROJECT" --json 2>/dev/null \
    | python3 -c 'import json,sys; a=json.load(sys.stdin).get("result",[]); print(a[0]["appId"] if a else "")' || true)"
  if [ -z "$app_id" ]; then
    run firebase apps:create WEB "$SERVICE-web" --project "$PROJECT"
    app_id="$(firebase apps:list WEB --project "$PROJECT" --json 2>/dev/null \
      | python3 -c 'import json,sys; a=json.load(sys.stdin).get("result",[]); print(a[0]["appId"] if a else "")' || true)"
  fi
  if [ -n "$app_id" ]; then
    if [ "$DRY" = 1 ]; then echo "   [dry-run] write web/config.js from app $app_id"; else
      firebase apps:sdkconfig WEB "$app_id" --project "$PROJECT" 2>/dev/null | python3 -c '
import json, sys
raw = sys.stdin.read()
c = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
site = sys.argv[1]
cfg = {k: c.get(k, "") for k in ("apiKey", "authDomain", "projectId", "messagingSenderId", "appId")}
body = ",\n".join(f"    {k}: {json.dumps(v)}" for k, v in cfg.items())
open("web/config.js", "w").write("window.NOW_CONFIG = {\n  firebase: {\n" + body + ",\n  },\n  hostingDomain: %s,\n};\n" % json.dumps(site + ".web.app"))
' "$HOSTING_SITE"
      echo "   wrote web/config.js"
    fi
  else
    echo "   could not create/find a Firebase web app; copy web/config.example.js to web/config.js by hand" >&2
  fi
fi

say "2/6 .firebaserc and firebase.json (Hosting site + Cloud Run rewrite)"
if [ "$DRY" = 1 ]; then echo "   [dry-run] point .firebaserc at $PROJECT; hosting site $HOSTING_SITE -> service $SERVICE ($REGION)"; else
  python3 - "$PROJECT" "$HOSTING_SITE" "$SERVICE" "$REGION" <<'PY'
import json, sys
project, site, service, region = sys.argv[1:]
json.dump({"projects": {"default": project}}, open(".firebaserc", "w")); open(".firebaserc", "a").write("\n")
cfg = json.load(open("firebase.json"))
h = cfg["hosting"]
h["site"] = site
h["rewrites"] = [{"source": "**", "run": {"serviceId": service, "region": region}}]
json.dump(cfg, open("firebase.json", "w"), indent=2); open("firebase.json", "a").write("\n")
PY
fi
if ! firebase hosting:sites:list --project "$PROJECT" 2>/dev/null | grep -q "[/ ]$HOSTING_SITE[ .│]"; then
  run firebase hosting:sites:create "$HOSTING_SITE" --project "$PROJECT"
fi

say "3/6 Firestore indexes"
run firebase deploy --only firestore:indexes --project "$PROJECT"

say "4/6 Cloud Run service (first deploy)"
run ./deploy.sh

say "5/6 Attachments bucket"
run scripts/create-bucket.sh
if [ "$PUSH" = 1 ]; then
  say "5b Push reminders"
  run scripts/setup-push.sh
fi

if [ "$WIDGET" = 1 ]; then
  say "5c Widget token (secret widget-token; unlocks only GET /todos/next)"
  if gcloud secrets describe widget-token --project "$PROJECT" >/dev/null 2>&1; then
    echo "   secret widget-token exists, keeping it"
  else
    if [ "$DRY" = 1 ]; then echo "   [dry-run] create secret widget-token from a random 24-byte token"; else
      openssl rand -hex 24 | tr -d '\n' | gcloud secrets create widget-token --project "$PROJECT" \
        --replication-policy automatic --data-file=-
    fi
  fi
  SA="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --format 'value(spec.template.spec.serviceAccountName)' 2>/dev/null || true)"
  SA="${SA:-$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)' 2>/dev/null)-compute@developer.gserviceaccount.com}"
  run gcloud secrets add-iam-policy-binding widget-token --project "$PROJECT" \
    --member "serviceAccount:${SA}" --role roles/secretmanager.secretAccessor
  run gcloud run services update "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --update-secrets WIDGET_TOKEN=widget-token:latest
  echo "   read the token to paste into Scriptable with:"
  echo "   gcloud secrets versions access latest --secret widget-token --project $PROJECT"
fi

if [ "$CALENDAR" = 1 ]; then
  say "5d Calendar feed (secret calendar-token; unlocks only GET /calendar/<token>.ics)"
  run scripts/setup-calendar.sh
fi

say "5e Cost guards (Artifact Registry cleanup policy, monthly budget alert)"
run scripts/setup-cost-guards.sh || echo "   cost guards incomplete (see above); rerun scripts/setup-cost-guards.sh" >&2

say "6/6 Firebase Hosting (serves the app on $HOSTING_SITE.web.app)"
run firebase deploy --only hosting --project "$PROJECT"

cat <<MSG

Done. Two console steps cannot be scripted:
  1. Firebase console > Authentication > Sign-in method: enable Google.
  2. Authentication > Settings > Authorized domains: make sure ${HOSTING_SITE}.web.app is listed.
Then run scripts/doctor.sh. Optional: WIDGET_TOKEN for the lock screen widget (docs/okf/ops/widget.md).
MSG
