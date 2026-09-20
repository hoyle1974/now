# Sourced by deploy.sh and scripts/*.sh. Resolves, in this order of precedence:
#   environment  >  .now.env  >  .zilch.config  >  gcloud config
#
#   PROJECT  GCP project id      (.zilch.config: gcp_project_id)
#   REGION   Cloud Run region    (.zilch.config: gcp_region, default us-central1)
#   SERVICE  Cloud Run service   (.zilch.config: app_name)
#
# .now.env holds this app's own overrides (KEY=value lines, git-ignored; see
# .now.env.example). It exists because zilch names the service after app_name,
# while an app deployed earlier may already run under a different name.
# Files are parsed, never executed.

NOW_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# _cfg FILE KEY -> the last KEY=value in FILE (empty if none)
_cfg() {
  [ -f "$NOW_ROOT/$1" ] || return 0
  sed -n "s/^$2=//p" "$NOW_ROOT/$1" | tail -n 1 | sed 's/[[:space:]]*$//; s/^"\(.*\)"$/\1/'
}

PROJECT="${PROJECT:-$(_cfg .now.env PROJECT)}"
PROJECT="${PROJECT:-$(_cfg .zilch.config gcp_project_id)}"
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
REGION="${REGION:-$(_cfg .now.env REGION)}"
REGION="${REGION:-$(_cfg .zilch.config gcp_region)}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-$(_cfg .now.env SERVICE)}"
SERVICE="${SERVICE:-$(_cfg .zilch.config app_name)}"

if [ -z "$PROJECT" ] || [ -z "$SERVICE" ]; then
  echo "error: cannot work out the project and service." >&2
  echo "  Run zilch (writes .zilch.config), or copy .now.env.example to .now.env," >&2
  echo "  or export PROJECT=... SERVICE=..." >&2
  exit 1
fi
export PROJECT REGION SERVICE
