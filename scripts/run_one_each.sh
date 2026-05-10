#!/bin/bash
# scripts/run_one_each.sh — run one attempt of each AgencyBench-v2 scenario.
#
# Usage:
#   scripts/run_one_each.sh                          # run all (skip MCP/scenario1)
#   scripts/run_one_each.sh --dry-run                # print the planned commands
#   scripts/run_one_each.sh --only Backend/scenario1
#   scripts/run_one_each.sh --skip Backend/scenario1 --skip Game/scenario10
#   scripts/run_one_each.sh --force                  # rerun even if meta_eval.json exists
#
# For each scenario:
#   1. Generate <scenario>/.env.run via scripts/make_env_run.sh
#   2. Run `python eval_task.py --env .env.run` with a timeout
#   3. Stream stdout+stderr to progress/runs/<run_id>/<capability>_<scenario>.log
#   4. Optionally skip if a meta_eval.json already exists for the chosen model

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OVERLAY="${OVERLAY:-$ROOT/progress/azure_overlay.env}"
PER_SCENARIO_TIMEOUT="${PER_SCENARIO_TIMEOUT:-3600}"   # 60 min/scenario hard cap
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
LOGDIR="$ROOT/progress/runs/$RUN_ID"
DRY_RUN=0
FORCE=0
ONLY=()
SKIP=("MCP/scenario1")   # default: needs a real GitHub PAT

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --force)   FORCE=1 ;;
    --only)    shift; ONLY+=("$1") ;;
    --skip)    shift; SKIP+=("$1") ;;
    --run-id)  shift; RUN_ID="$1"; LOGDIR="$ROOT/progress/runs/$RUN_ID" ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

mkdir -p "$LOGDIR"
SUMMARY="$LOGDIR/summary.tsv"
[ -f "$SUMMARY" ] || printf "scenario\tstatus\texit_code\tsecs\tlog\tmeta_eval\n" > "$SUMMARY"

[ -f "$OVERLAY" ] || { echo "missing $OVERLAY" >&2; exit 2; }

# Read SII_TARGET_MODEL from the overlay so we can compute the model_slug
# subdirectory each scenario writes into.
TARGET_MODEL="$(grep -E '^SII_TARGET_MODEL=' "$OVERLAY" | tail -1 | cut -d= -f2- | tr -d "\"'")"
[ -n "$TARGET_MODEL" ] || { echo "SII_TARGET_MODEL not set in overlay" >&2; exit 2; }
MODEL_SLUG="$(python3 -c "
import re,sys
raw=sys.argv[1].strip().rsplit('/',1)[-1]
slug=''.join(c if c.isalnum() or c in '-._' else '_' for c in raw).strip('._-') or 'model'
print(slug)
" "$TARGET_MODEL")"
echo "[run_one_each] run_id=$RUN_ID model=$TARGET_MODEL slug=$MODEL_SLUG logdir=$LOGDIR"

scenarios=()
for d in "$ROOT/AgencyBench-v2"/{Backend,Code,Frontend,Game,Research,MCP}/scenario*; do
  [ -d "$d" ] || continue
  cap_sc="${d#$ROOT/AgencyBench-v2/}"
  scenarios+=("$cap_sc")
done

contains() { local n="$1"; shift; for x in "$@"; do [ "$x" = "$n" ] && return 0; done; return 1; }

run_one() {
  local cap_sc="$1"
  local d="$ROOT/AgencyBench-v2/$cap_sc"
  local cap="${cap_sc%%/*}"
  local sc="${cap_sc##*/}"
  local logfile="$LOGDIR/${cap}_${sc}.log"
  local metafile="$d/$MODEL_SLUG/meta_eval.json"

  if [ ${#ONLY[@]} -gt 0 ] && ! contains "$cap_sc" "${ONLY[@]}"; then
    return 0
  fi
  if contains "$cap_sc" "${SKIP[@]}"; then
    echo "[skip] $cap_sc (in --skip list)"
    printf "%s\tskipped\t-\t-\t-\t-\n" "$cap_sc" >> "$SUMMARY"
    return 0
  fi
  if [ "$FORCE" -eq 0 ] && [ -f "$metafile" ]; then
    echo "[exists] $cap_sc (use --force to rerun)"
    printf "%s\texists\t-\t-\t%s\t%s\n" "$cap_sc" "$logfile" "$metafile" >> "$SUMMARY"
    return 0
  fi

  echo "[run] $cap_sc -> $logfile"
  if [ "$DRY_RUN" -eq 1 ]; then
    return 0
  fi

  "$ROOT/scripts/make_env_run.sh" "$d" >/dev/null

  local started=$(date +%s)
  set +e
  (
    cd "$d"
    export PATH="/home/sandbox/.npm-global/bin:$PATH"
    export SII_BRIDGE_PATH="${SII_BRIDGE_PATH:-/tmp/bridge-shim.mjs}"
    export SII_BRIDGE_LOGFILE="$LOGDIR/${cap}_${sc}.bridge.err"
    : > "$SII_BRIDGE_LOGFILE"
    timeout "$PER_SCENARIO_TIMEOUT" python3 eval_task.py --env .env.run
  ) > "$logfile" 2>&1
  local ec=$?
  set -e
  local elapsed=$(( $(date +%s) - started ))

  local status="failed"
  [ $ec -eq 0 ] && status="ok"
  [ $ec -eq 124 ] && status="timeout"
  [ -f "$metafile" ] && status="${status}+meta"

  printf "%s\t%s\t%d\t%d\t%s\t%s\n" "$cap_sc" "$status" "$ec" "$elapsed" "$logfile" "${metafile:--}" >> "$SUMMARY"
  echo "[done] $cap_sc status=$status ec=$ec elapsed=${elapsed}s"
}

for s in "${scenarios[@]}"; do
  run_one "$s" || true
done

echo "[run_one_each] all done. summary: $SUMMARY"
