#!/bin/bash
# Read-only "is this deployment still free?" check. The #1 rule of this project is zero GCP
# cost (docs/okf/principles.md), so any finding here is printed LOUDLY and the exit code is 1.
# Runs automatically at the end of deploy.sh and as part of scripts/doctor.sh; safe any time.
#
#   scripts/cost-check.sh
set -uo pipefail
cd "$(dirname "$0")/.."
source scripts/lib/config.sh   # PROJECT, REGION, SERVICE

# never let gcloud prompt (e.g. to enable an API): stdin is empty, so any prompt answers no
gcloud() { command gcloud "$@" </dev/null; }

bad=0; near=0
ok()   { printf '  OK    %s\n' "$*"; }
near() { printf '  WARN  %s\n' "$*"; near=$((near + 1)); }
loud() { bad=$((bad + 1)); printf '\n!!!!!!!!  COST RISK  !!!!!!!!\n!!  %s\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n\n' "$*"; }

echo "cost check: project=$PROJECT service=$SERVICE (rule #1: nothing may bill)"

# --- Cloud Run: request-based billing, scale to zero, one instance max
svc="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format=json 2>/dev/null)"
if [ -z "$svc" ]; then
  near "cannot read Cloud Run service $SERVICE (not deployed, or no access)"
else
  jq_() { python3 -c "import json,sys;d=json.load(sys.stdin);a=d['spec']['template']['metadata'].get('annotations',{});print($1)" <<<"$svc"; }
  [ "$(jq_ "a.get('run.googleapis.com/cpu-throttling','')")" = "true" ] \
    && ok "CPU throttled between requests (request-based billing)" \
    || loud "ALWAYS-ON CPU: billed 24/7, about \$30/month. Fix: gcloud run services update $SERVICE --cpu-throttling"
  min="$(jq_ "a.get('autoscaling.knative.dev/minScale','0')")"
  [ "$min" = "0" ] && ok "min instances 0" || loud "MIN INSTANCES = $min: idle instances are billed. Fix: gcloud run services update $SERVICE --min-instances 0"
  max="$(jq_ "a.get('autoscaling.knative.dev/maxScale','')")"
  { [ "$max" = "1" ] || [ -n "$max" ] && [ "$max" -le 1 ] 2>/dev/null; } && ok "max instances 1" \
    || loud "MAX INSTANCES = ${max:-unset (default 100)}: a traffic spike could bill. Fix: gcloud run services update $SERVICE --max-instances 1"
fi

# --- Artifact Registry: free tier is 0.5 GiB
# Sum the real image sizes: the repository's own "size" stat lags behind deletions by a day or more
# and once read 2.9 GB for 5 images of 70 MB.
mb="$(gcloud artifacts docker images list "${REGION}-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy" --format='value(metadata.imageSizeBytes)' 2>/dev/null \
  | awk '{s+=$1} END {if (NR>0) printf "%d", s/1048576}')"
if [ -n "$mb" ]; then
  if [ "$mb" -gt 512 ]; then
    loud "ARTIFACT REGISTRY IS ${mb} MB, OVER THE 512 MB FREE TIER (about \$0.10/GB-month over). Cleanup: scripts/setup-cost-guards.sh, then delete old images by hand: gcloud artifacts docker images list ${REGION}-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy"
  elif [ "$mb" -gt 300 ]; then near "Artifact Registry ${mb} MB of the 512 MB free tier"
  else ok "Artifact Registry ${mb} MB of 512 MB free"; fi
else
  near "could not read the Artifact Registry size"
fi

# --- Things that are never free-tier friendly
n="$(gcloud compute instances list --project "$PROJECT" --format='value(name)' 2>/dev/null | wc -l | tr -d ' ')"
[ "$n" = "0" ] && ok "no Compute Engine VMs" || loud "$n Compute Engine VM(s) exist: they bill. gcloud compute instances list --project $PROJECT"
n="$(gcloud compute addresses list --project "$PROJECT" --format='value(name)' 2>/dev/null | wc -l | tr -d ' ')"
[ "$n" = "0" ] && ok "no reserved IPs" || loud "$n reserved IP address(es) exist: unused ones bill"
n="$(gcloud sql instances list --project "$PROJECT" --format='value(name)' 2>/dev/null | wc -l | tr -d ' ')"
[ "$n" = "0" ] && ok "no Cloud SQL instances" || loud "$n Cloud SQL instance(s) exist: they bill around the clock"
n="$(gcloud scheduler jobs list --project "$PROJECT" --location "$REGION" --format='value(name)' 2>/dev/null | wc -l | tr -d ' ')"
[ "$n" -le 3 ] && ok "Cloud Scheduler jobs $n of 3 free" || loud "$n Cloud Scheduler jobs: only 3 are free (\$0.10 each after)"
# every bucket must be in a free-tier region (us-central1/us-east1/us-west1)
gcloud storage buckets list --project "$PROJECT" --format='value(name,location)' 2>/dev/null | while read -r b l; do
  case "$l" in US-CENTRAL1|US-EAST1|US-WEST1) ;; *) echo "BADBUCKET $b $l";; esac
done | grep -q . && loud "a Cloud Storage bucket is outside the free-tier regions (only us-central1, us-east1, us-west1 get 5 GB free)" || ok "buckets in free-tier regions"

# --- Budget: must alert at about $1
ACCOUNT="$(gcloud billing projects describe "$PROJECT" --format='value(billingAccountName)' 2>/dev/null | sed 's|billingAccounts/||')"
if [ -n "$ACCOUNT" ]; then
  gcloud billing budgets list --billing-account "$ACCOUNT" --format='value(displayName)' 2>/dev/null | grep -q "${SERVICE} monthly budget" \
    && ok "budget alert exists" || near "no '${SERVICE} monthly budget' alert (scripts/setup-cost-guards.sh)"
fi

# --- Firestore free quota (50k reads / 20k writes / 20k deletes per day): warn at 50%
tok="$(gcloud auth print-access-token 2>/dev/null)"
if [ -n "$tok" ]; then
  end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  start="$(date -u -v-24H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)"
  for pair in read_count:50000 write_count:20000 delete_count:20000; do
    m="${pair%%:*}"; lim="${pair##*:}"
    tot="$(curl -s -H "Authorization: Bearer $tok" -G "https://monitoring.googleapis.com/v3/projects/$PROJECT/timeSeries" \
      --data-urlencode "filter=metric.type=\"firestore.googleapis.com/document/$m\"" \
      --data-urlencode "interval.startTime=$start" --data-urlencode "interval.endTime=$end" \
      --data-urlencode "aggregation.alignmentPeriod=86400s" --data-urlencode "aggregation.perSeriesAligner=ALIGN_SUM" \
      --data-urlencode "aggregation.crossSeriesReducer=REDUCE_SUM" \
      | python3 -c "import json,sys;d=json.load(sys.stdin);print(sum(int(p['value'].get('int64Value',0)) for s in d.get('timeSeries',[]) for p in s['points']))" 2>/dev/null)"
    [ -z "$tot" ] && continue
    if [ "$tot" -ge "$lim" ]; then loud "FIRESTORE ${m/_count/s} ${tot}/day EXCEEDS the free quota of $lim"
    elif [ "$tot" -ge $((lim / 2)) ]; then near "Firestore ${m/_count/s} ${tot}/day is over 50% of the free quota ($lim)"
    else ok "Firestore ${m/_count/s} ${tot}/day of $lim free"; fi
  done
fi

echo
if [ "$bad" -gt 0 ]; then
  printf '########  %d COST RISK(S): THIS DEPLOYMENT MAY BE BILLING  ########\n' "$bad"; exit 1
fi
[ "$near" -gt 0 ] && echo "cost check: free, with $near warning(s)" || echo "cost check: all free"
