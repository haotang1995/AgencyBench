#!/bin/bash
# scripts/run_parallel.sh — run multiple scenarios in parallel.
#
# Wraps scripts/run_one_each.sh by feeding it one --only at a time and
# running up to N invocations concurrently with xargs -P.
#
# Usage:
#   scripts/run_parallel.sh <run_id> <workers> [scenario...]
#
# If no scenarios are given, all scenarios are scheduled. The driver
# itself short-circuits any scenario whose meta_eval.json already
# exists, so this is safe to run alongside (or after) a sequential
# sweep that's already in flight — there's no need to coordinate.
#
# Frontend and Game scenarios share the agent-infra/sandbox container,
# so they're forced into a single worker pool to avoid races.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RUN_ID="${1:?run_id required}"
WORKERS="${2:?workers required}"
shift 2 || true

if [ $# -eq 0 ]; then
  scenarios=()
  for d in "$ROOT/AgencyBench-v2"/{Backend,Code,Frontend,Game,Research,MCP}/scenario*; do
    [ -d "$d" ] || continue
    s="${d#$ROOT/AgencyBench-v2/}"
    [ "$s" = "MCP/scenario1" ] && continue   # default skip
    scenarios+=("$s")
  done
else
  scenarios=("$@")
fi

# Split into "sandbox-using" and "rest"; sandbox-using runs serially.
sandbox=()
rest=()
for s in "${scenarios[@]}"; do
  case "$s" in
    Frontend/*|Game/*) sandbox+=("$s") ;;
    *)                 rest+=("$s") ;;
  esac
done

echo "[run_parallel] run_id=$RUN_ID workers=$WORKERS"
echo "[run_parallel] sandbox-serial: ${#sandbox[@]} scenarios"
echo "[run_parallel] non-sandbox parallel: ${#rest[@]} scenarios"

mkdir -p "$ROOT/progress/runs/$RUN_ID"

run_one() {
  local s="$1"
  RUN_ID="$RUN_ID" "$ROOT/scripts/run_one_each.sh" --run-id "$RUN_ID" --only "$s" \
    > "$ROOT/progress/runs/$RUN_ID/.parallel-${s//\//_}.driver.log" 2>&1
  echo "[parallel] finished $s"
}
export -f run_one
export RUN_ID ROOT

# Phase 1: non-sandbox scenarios in parallel, $WORKERS at a time.
if [ ${#rest[@]} -gt 0 ]; then
  printf '%s\n' "${rest[@]}" | xargs -P "$WORKERS" -I{} bash -c 'run_one "$@"' _ {}
fi

# Phase 2: sandbox scenarios sequentially.
for s in "${sandbox[@]}"; do
  run_one "$s"
done

echo "[run_parallel] all done"
