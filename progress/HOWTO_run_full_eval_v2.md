# How to run AgencyBench-v2 in this Docker container

This is a paste-ready playbook for re-running AgencyBench-v2 against
**Azure GPT-5** (via the OAI-compat proxy in `prv_oai_example/.env_oai`).
All paths are relative to `/workspace`.

## Prerequisites (already set up by the Dockerfile in this branch)

- Python deps from `requirements.txt` installed in `/opt/agencybench-venv`.
- `@gair/sii-cli` installed globally so `sii-bridge` is on `$PATH`. (Add
  `npm install -g @gair/sii-cli` if you rebuild the container yourself.)
- `/var/run/docker.sock` mounted from the host so we can run the sibling
  `agent-infra/sandbox` container for Frontend + Game scenarios.

## One-time setup

### 1. Stage the Azure proxy credentials

The harness reads them from `progress/azure_overlay.env` (gitignored).
The current file points all base URLs at `http://127.0.0.1:7333/v1` — a
local reverse proxy we run in step 2.

If you need to change keys, edit `progress/azure_overlay.env` directly.
Key required fields:

```
SII_AGENT_API_KEY=<key>
SII_AGENT_API_BASE_URL=http://127.0.0.1:7333/v1
SII_TARGET_MODEL=gpt-5
SII_AUTH_TYPE=USE_OPENAI
SII_USERNAME=unused-azure-overlay
SII_PASSWORD=unused-azure-overlay
EVAL_TEXT_*  / VISION_MODEL  / QWEN_VISION_*  / OPENAI_*    point at the same proxy
SANDBOX_BASE_URL=http://172.17.0.1:8080   # docker bridge gateway, not localhost
```

### 2. Start the local OAI-compat proxy

```bash
set -a; source progress/azure_overlay.env; set +a
nohup python3 scripts/azure_proxy.py > /tmp/azure-proxy.log 2>&1 &
```

What this proxy does:

- Adds the `X-API-Key` header that the upstream Azure app requires
  (the SII bridge cannot send arbitrary headers itself).
- Lives at `http://127.0.0.1` so the bridge's URL-based "azure"
  detection (which would mangle the path) does not trigger.
- Rewrites `max_tokens` → `max_completion_tokens` and clamps to 32768
  (the bridge hardcodes `1e5`, which gpt-4.1 caps below and gpt-5
  refuses entirely).
- Aliases hardcoded judge model names like `gzy/claude-4-sonnet`
  (used by Research/scenario{4,5}) to a real deployment.

Smoke test:

```bash
set -a; source progress/azure_overlay.env; set +a
curl -sS -X POST http://127.0.0.1:7333/v1/chat/completions \
  -H "Authorization: Bearer $OPENAI_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"gpt-5","messages":[{"role":"user","content":"hi"}],"max_tokens":100000}' | head -c 300
```

### 3. Start the agent-infra sandbox container (only needed for Frontend + Game)

```bash
docker run -d --rm --security-opt seccomp=unconfined \
  --name agencybench-sandbox -p 8080:8080 \
  ghcr.io/agent-infra/sandbox:latest
# Wait until healthy:
docker ps --filter name=agencybench-sandbox --format '{{.Status}}'
# Reachable from inside our container:
curl -sS -o /dev/null -w '%{http_code}\n' http://172.17.0.1:8080/
```

If you skip this, the 13 scenarios in Frontend/ and Game/ will write a
`meta_eval.json` with errors (they need to drive the sandbox's Chromium
through `playwright.connect_over_cdp`). The other 19 scenarios are
unaffected.

### 4. Optional: bridge stderr logging

Patch the SII bridge wrapper to tee its `console.log` and `process.stderr`
to a file the SDK does not surface by default:

```bash
# /tmp/bridge-shim.mjs is committed at runtime; re-create if missing:
cat > /tmp/bridge-shim.mjs << 'EOF'
import fs from 'node:fs';
const out = fs.createWriteStream(process.env.SII_BRIDGE_LOGFILE || '/tmp/sii-bridge.err', { flags: 'a' });
const realWrite = process.stderr.write.bind(process.stderr);
process.stderr.write = (chunk, ...rest) => { try { out.write(chunk); } catch {} return realWrite(chunk, ...rest); };
const origLog = console.log;
console.log = (...args) => { try { out.write(args.map(String).join(' ') + '\n'); } catch {} origLog(...args); };
await import('/home/sandbox/.npm-global/lib/node_modules/@gair/sii-cli/bundle/bridge/index.js');
EOF
export SII_BRIDGE_PATH=/tmp/bridge-shim.mjs
```

The driver sets `SII_BRIDGE_PATH` automatically.

## Running

### Single scenario

```bash
scripts/run_one_each.sh --only MCP/scenario2
# log:        progress/runs/<run_id>/MCP_scenario2.log
# bridge log: progress/runs/<run_id>/MCP_scenario2.bridge.err
# meta_eval:  AgencyBench-v2/MCP/scenario2/gpt-5/meta_eval.json
```

### One attempt of every scenario

```bash
RUN_ID="$(date +%Y%m%d-%H%M%S)" PER_SCENARIO_TIMEOUT=2400 \
  scripts/run_one_each.sh
# defaults: skip MCP/scenario1 (needs a real GitHub PAT), 60-minute
# hard timeout per scenario, MAX_SUBTASK_ATTEMPTS=1, SII_MAX_TURNS=120.
```

Driver flags:

- `--dry-run` — print the planned invocations and exit.
- `--only <capability/scenario>` — run just one (repeatable).
- `--skip <capability/scenario>` — append to the skip list.
- `--force` — rerun even if the meta_eval.json already exists.
- `--run-id <id>` — name the output dir.

### Aggregating

After (or during) a run:

```bash
python3 scripts/aggregate_summary.py --run-id <id> --transcripts
# writes:
#   progress/summary.json
#   progress/summary.md         (one row per scenario)
#   progress/transcripts/<id>/<capability>_<scenario>.md
```

For a single-scenario transcript without re-aggregating:

```bash
python3 scripts/show_chat_history.py \
    AgencyBench-v2/MCP/scenario2/gpt-5/meta_eval.json \
    --out /tmp/mcp2.md
```

## What the harness fixes (vs. a stock checkout)

These are baked into our scripts/Dockerfile/proxy so the README flow
works end-to-end:

1. **Missing Node CLI.** `sii_agent_sdk` requires the `sii-bridge`
   binary from npm `@gair/sii-cli`; the upstream README does not
   mention this. We install it globally.
2. **Azure proxy auth.** The proxy needs both bearer + `X-API-Key`.
   We add it via the localhost reverse proxy.
3. **Azure URL heuristic.** The bridge mangles URLs containing
   `azure` to real-Azure protocol. We tunnel through `127.0.0.1` to
   avoid the trigger.
4. **`max_tokens` bridge default.** Bridge hardcodes `1e5`, breaks
   gpt-4.1 (32k cap) and gpt-5 (rejects `max_tokens` entirely).
   Proxy rewrites and clamps.
5. **`enable_data_upload` kwarg.** 10 scenarios pass a kwarg the
   installed sdk does not have. `scripts/sitecustomize.py`
   monkey-patches `SiiAgentOptions.__init__` to drop unknown kwargs.
6. **`SII_USERNAME`/`SII_PASSWORD` validators.** Several scenarios
   `require()` non-empty strings even when `SII_AUTH_TYPE=USE_OPENAI`
   makes them irrelevant. Overlay sets stub values.
7. **Hardcoded judge model.** Research/4 and Research/5 invoke a
   subprocess with `--judge_model gzy/claude-4-sonnet`; we alias it
   in the proxy to `gpt-4.1`.
8. **Backend/scenario2 description default.** That one scenario has
   `--description default="/description.json"` (absolute, broken).
   Driver passes `--description description.json` to every scenario.
9. **`SANDBOX_BASE_URL=localhost:8080`** unreachable from inside our
   container. Overlay uses `172.17.0.1:8080` (docker bridge gateway).

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `BridgeNotFoundError` | `@gair/sii-cli` not installed | `npm install -g @gair/sii-cli` (or rebuild container) |
| `403 Invalid API Key` in bridge log | `X-API-Key` not added | start `scripts/azure_proxy.py` |
| `400 max_tokens is too large` | proxy rewriter not active | restart `scripts/azure_proxy.py` |
| `unexpected keyword argument 'enable_data_upload'` | sitecustomize.py not on PYTHONPATH | driver sets it; if running by hand: `export PYTHONPATH=/workspace/scripts:$PYTHONPATH` |
| `FileNotFoundError: /description.json` | running `eval_task.py` without `--description description.json` (Backend/scenario2) | use the driver, or pass the flag |
| Frontend/Game scenarios all fail | sandbox container not running or not reachable at `172.17.0.1:8080` | `docker run -d --rm -p 8080:8080 ghcr.io/agent-infra/sandbox:latest` |
| Single scenario hung past 60min | bridge or upstream stalled | driver kills via `timeout`; re-run with `--only --force` |
