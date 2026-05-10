#!/bin/bash
# make_env_run.sh <scenario_dir>
#
# Produces <scenario_dir>/.env.run = scenario .env + progress/azure_overlay.env
# (overlay last, so its values override the placeholders in the bundled .env).
set -euo pipefail
SCENARIO="${1:?usage: make_env_run.sh <scenario_dir>}"
OVERLAY="${OVERLAY:-/workspace/progress/azure_overlay.env}"
[ -f "$SCENARIO/.env" ] || { echo "missing $SCENARIO/.env" >&2; exit 2; }
[ -f "$OVERLAY" ]      || { echo "missing $OVERLAY" >&2; exit 2; }

{
  echo "# AUTO-GENERATED — scenario .env first, then overlay (overrides)"
  cat "$SCENARIO/.env"
  echo
  echo "# --- overlay ---"
  cat "$OVERLAY"
} > "$SCENARIO/.env.run"
echo "wrote $SCENARIO/.env.run"
