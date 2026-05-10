# current_progress_run_full_eval_v2.md — live status

**Active step:** H — running 31 scenarios end-to-end (skip MCP/scenario1).

**Plan checkpoints**

- [x] A. Install `@gair/sii-cli` Node CLI; `which sii-bridge` returns a path; same line in Dockerfile.
- [x] B. `progress/azure_overlay.env` written and gitignored.
- [x] C. SDK smoke-test round-trip with GPT-5 succeeds.
- [x] D. `MCP/scenario2` produces a fresh `meta_eval.json` with non-empty `agent_output`.
- [x] E. `agent-infra/sandbox` container running and reachable from this container.
- [x] F. `scripts/run_one_each.sh` exists; dry-run lists 32 invocations; `--only` works.
- [x] G. `scripts/show_chat_history.py` exists; transcripts written.
- [ ] H. All scenarios run; `progress/summary.md` lists every one.

**Right now:** sweep `20260510-fullsweep2` running in background (driver task `brsgyfkcn`). Monitor `b5gdxrol4` reports each scenario start/finish. Backend/scenario1 in progress as of 07:23.

**Resume instructions if interrupted:**

```bash
set -a; source progress/azure_overlay.env; set +a
# 1. Make sure proxy is up
pgrep -f azure_proxy.py || python3 scripts/azure_proxy.py >/tmp/azure-proxy.log 2>&1 &
# 2. Make sure sandbox container is up (only needed for Frontend/Game)
docker ps --filter name=agencybench-sandbox --format '{{.Names}}' | grep -q . || \
  docker run -d --rm --name agencybench-sandbox -p 8080:8080 ghcr.io/agent-infra/sandbox:latest
# 3. Resume the sweep — driver is idempotent, skips scenarios that
#    already produced a meta_eval.json under gpt-5/.
RUN_ID=20260510-fullsweep2 PER_SCENARIO_TIMEOUT=2400 scripts/run_one_each.sh
# 4. Aggregate & generate transcripts at the end:
python3 scripts/aggregate_summary.py --run-id 20260510-fullsweep2 --transcripts
```
