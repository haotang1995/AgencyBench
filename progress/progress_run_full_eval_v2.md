# progress_run_full_eval_v2.md — permanent log

This file is append-only. Every attempt (success or failure) goes here in chronological order.

---

## 2026-05-10 — Plan written

- Wrote `progress/plan_run_full_eval_v2.md`.
- Discovered the real harness blocker: `sii_agent_sdk` (Python) shells out to a Node binary `sii-bridge`. Not installed. Found it: `npm view @gair/sii-cli` → v0.0.74, exposes `sii`, `sii-bridge`, `sii-cli`.
- Verified the Azure OAI proxy works on `gpt-5-mini`, `gpt-4.1-mini`, and (with `image_url` payload) on `gpt-4.1`/`gpt-4o`/`gpt-5`. So vision-judge can run through the same proxy via `EVAL_VISION_PROVIDER=qwen`.
- Verified host docker accessible: `/var/run/docker.sock` mounted, `docker ps` shows 8 sibling containers running.
- Inventory frozen: 32 scenarios. 13 use sandbox (Frontend ×3 + Game ×10). 16 use text judge. 13 use vision judge. MCP/scenario1 needs a real GitHub PAT.

Status: plan ready, beginning Step A.

---

## 2026-05-10 — Step A: install @gair/sii-cli (DONE)

- `npm install -g --cache /tmp/npm-cache @gair/sii-cli` failed initially because `/usr/lib/node_modules` is root-owned and `/root/.npm` is root-owned (we run as `sandbox`). Retried with a per-user prefix: `env HOME=/home/sandbox npm config set prefix /home/sandbox/.npm-global && env HOME=/home/sandbox npm install -g --cache /tmp/npm-cache @gair/sii-cli` → 66 packages added cleanly.
- Verified: `which sii-bridge` → `/home/sandbox/.npm-global/bin/sii-bridge`; running it with no stdin exits with the expected `BRIDGE_ERROR: Input stream ended` (means the bridge runs but its stdin protocol got nothing).
- Patched `Dockerfile` to add `@gair/sii-cli` to the existing `npm install -g` line.
- Added `/home/sandbox/.npm-global/bin` to `~/.bashrc` PATH.

Commit: `feat: add @gair/sii-cli to Dockerfile + scaffold progress files`.

---

## 2026-05-10 — Step B: write azure_overlay.env (DONE)

- Wrote `progress/azure_overlay.env` with all `SII_AGENT_*`, `EVAL_TEXT_*`, `EVAL_VISION_*`, `OPENAI_*`, `X_API_KEY`, sandbox knobs (`MAX_SUBTASK_ATTEMPTS=1`, `SUBTASK_ATTEMPT_LIMIT=1`, `SII_MAX_TURNS=120`).
- Forced `SII_AUTH_TYPE=USE_OPENAI` so MCP/scenario2 doesn't demand SII login.
- Confirmed `git check-ignore` flags the file so the API key never lands in git.

---

## 2026-05-10 — Step C: SDK smoke test (DONE — but with two real harness fixes)

Three iterations were needed.

### C-1: smoke ran, said "Task completed" with 0 tool calls

`scripts/smoke_sdk.py` against `gpt-5`:
- bridge initialized, authenticated as USE_OPENAI, said "Agent ready (16 tools)".
- Then immediately: `[ASSISTANT TEXT] Task completed`, `tokens_used=0`, `time_elapsed=350ms`, no tool call. Same for `gpt-4.1`.

Cause: the SDK doesn't surface bridge stderr. Wrote `/tmp/bridge-shim.mjs` that loads the real bridge but tees stderr/console.log to `/tmp/sii-bridge.err`. Set `SII_BRIDGE_PATH=/tmp/bridge-shim.mjs`. Re-ran. Now bridge stderr revealed:

> `[ERROR] OpenAI API Error: 403 "Error: Invalid API Key"`

The Azure proxy at `…/v1` requires *both* `Authorization: Bearer <k>` and an `X-API-Key: <k>` header (verified with curl). The bridge's OpenAI client only sends the bearer.

Worse: `detectAzureEndpoint` in the bridge bundle (line 137447) treats any URL containing the substring `azure` as **real** Azure OpenAI — it then mangles the URL to `<base>/openai/deployments/<model>?api-version=...` and uses the `api-key` header. Our proxy is only OAI-compat, not real-Azure, so this would fail anyway.

### C-2: built a localhost reverse proxy (`scripts/azure_proxy.py`)

- Listens on `http://127.0.0.1:7333`, forwards `/v1/...` to the upstream Azure-hosted proxy.
- Adds `X-API-Key: <key>` to every forwarded request.
- The hostname `127.0.0.1` does NOT match the bridge's `"azure"` substring heuristic, so the bridge treats it as plain OpenAI.

First attempt 404'd (`/v1/v1/...`) because the upstream URL already had `/v1` and we appended the request path which also had `/v1`. Fix: strip a trailing `/v1` from `UPSTREAM`.

Updated `progress/azure_overlay.env` to point all base URLs at `http://127.0.0.1:7333/v1`.

### C-3: smoke ran, but bridge sent `max_tokens=100000` and gpt-4.1 capped at 32768 (gpt-5 rejected `max_tokens` entirely)

The bridge bundle hardcodes `maxOutputTokens: 1e5` (line 196738). Two upstream errors:
- gpt-4.1: `400 max_tokens is too large: 100000. This model supports at most 32768 completion tokens.`
- gpt-5: `400 Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.`

Solution: extended `azure_proxy.py` with `_rewrite_chat_body` which, on `POST /chat/completions`, renames `max_tokens` → `max_completion_tokens` and clamps to 32768. Verified via curl: gpt-5 with `max_tokens=100000` now succeeds through the proxy.

### Final smoke result — works

```
[TOOL CALL] run_shell_command({'command': 'ls -la /tmp', ...})
[ASSISTANT TEXT] 🔧 Tool result: total 80\n...
[ASSISTANT TEXT] I see a typical /tmp with multiple sandboxed sii-smoke-* working directories...
[smoke] DONE — assistant_text_blocks=2 tool_calls=1 tool_results=0
```

Bridge stderr: `[AgentService] Execution completed: 1 turns, 20887ms, 1 tool calls`. GPT-5 used 6176 tokens via the proxy. Healthy.

Status: success.
Next: Step D — run `MCP/scenario2` end-to-end through `python eval_task.py`.

---

## 2026-05-10 — Step D: MCP/scenario2 end-to-end (DONE)

First attempt failed at `EnvConfig.from_env`: `require("SII_USERNAME")` rejected the empty stubs in the overlay. Fix: changed the overlay to set `SII_USERNAME=unused-azure-overlay` / `SII_PASSWORD=unused-azure-overlay` (USE_OPENAI auth ignores them, but the validator needs non-empty strings).

Second attempt ran cleanly. Wall-clock ≈ 6 minutes from start to meta_eval.json. The agent (GPT-5) hit the bridge's shell sandbox at one point — it tried `find … | while … $(dirname …)` which is rejected ("Command substitution using $(), <(), or >() is not allowed for security reasons") — then adapted with `find -print0 | while read -d ''` and parameter expansion. All 5 subtasks pass:

- subtask1 (build workspace_v2 shell): success — "workspace_v2 directory skeleton exists."
- subtask2 (move Python files): success — "Python files relocated into correct dev_bundle folders."
- subtask3 (CSV migration): success — "CSV files split between legacy and active targets correctly."
- subtask4 (markdown rename): success — "All markdown files moved and renamed with parent prefixes."
- subtask5 (cleanup): success — "Legacy desktop/ tree successfully deleted."

`meta_eval.json` schema for MCP scenarios uses `success`/`validator_message`/`assistant_response_excerpt` rather than the rubric/agent_output keys other scenarios use; extended `scripts/show_chat_history.py` to handle both schemas.

---

## 2026-05-10 — Step E: agent-infra sandbox container (DONE)

- `docker pull ghcr.io/agent-infra/sandbox:latest` succeeded.
- `docker run -d --rm --name agencybench-sandbox -p 8080:8080 ghcr.io/agent-infra/sandbox:latest` started cleanly; healthcheck flipped to "healthy" within ~10s.
- From inside our container: `curl http://172.17.0.1:8080/` → 200; `http://172.17.0.10:8080/` (sandbox container's bridge IP) → 200; `localhost:8080` → connection refused (expected — `localhost` inside our container is *our* loopback, not the host's).
- Updated `progress/azure_overlay.env` to `SANDBOX_BASE_URL=http://172.17.0.1:8080` (the docker-bridge gateway, resilient to the sandbox container restarting and getting a different bridge IP).

---

## 2026-05-10 — Steps F & G: driver + extractor (DONE)

- `scripts/run_one_each.sh` dry-runs cleanly: lists 32 scenarios in order, MCP/scenario1 skipped by default. Supports `--only`, `--skip`, `--force`, `--run-id`. Computes the same `model_slug` `eval_task.py` does (`gpt-5` → `gpt-5`) so it can short-circuit on existing `meta_eval.json`.
- `scripts/show_chat_history.py` tested on Backend/scenario1's reference run (14 kB markdown transcript) and on MCP/scenario2's gpt-5 run (5 kB transcript covering all 5 subtasks). Handles both meta_eval.json schemas (rubric vs MCP).

Status: ready for Step H — run the full sweep.

---

## 2026-05-10 — Step H: run the full sweep (IN PROGRESS)

Starting `scripts/run_one_each.sh` with the defaults (skip MCP/scenario1) plus a 60-minute hard timeout per scenario. Observing in background.

### H-1: first sweep failed silently — discovered the missing SDK kwarg

`run_id=20260510-fullsweep` ran instantly (0–4s per scenario) and wrote bogus `meta_eval.json` files showing 0 scores everywhere. Bridge log revealed:

> `[AGENT] Failed to initialize SII session: SiiAgentOptions.__init__() got an unexpected keyword argument 'enable_data_upload'`

10 scenarios pass `enable_data_upload=False` to `SiiAgentOptions(...)` but the installed `sii-agent-sdk==0.1.5` does not have that field. The agent never started; the eval scored everything 0; subtasks reported "No rule to make target" because the agent never wrote anything.

**Two related fixes** (both needed because the venv is root-owned and we cannot upgrade the SDK in place):

1. `scripts/sitecustomize.py` monkey-patches `SiiAgentOptions.__init__` to drop kwargs that the dataclass does not define. The driver exports `PYTHONPATH=$ROOT/scripts` so this file is picked up before any scenario imports the SDK.
2. Backend/scenario2 ships with `--description default="/description.json"` (absolute, broken). Driver now passes `--description description.json` to every scenario explicitly.

Cleaned up the bad `gpt-5/` directories (Backend/{1,3}, Code/{1,2}); kept the one real success (`MCP/scenario2/gpt-5`).

### H-2: alias gzy/claude judge models

Pre-emptive proxy patch: Research/scenario4 and Research/scenario5 invoke an internal subprocess with `--judge_model gzy/claude-4-sonnet` hardcoded. The Azure proxy returns 404 for that model. Added `_MODEL_ALIASES` to `azure_proxy.py` mapping `gzy/claude-*` and `claude-*` → `gpt-4.1`. Verified with curl.

### H-3: sweep `20260510-fullsweep2` running

Sweep restarted at 07:17. Backend/scenario1 in progress as of 07:24 — 1 of 5 subtasks completed (`Execution completed: 5 turns, 175784ms`), agent on subtask2 turn 6 actively writing C++ source files.

Monitor `b5gdxrol4` watching the driver output for `[run]/[done]/[skip]` events. Monitor `b65s4f1e8` watching for new `meta_eval.json` files (and re-aggregating `progress/summary.{json,md}` whenever one appears).


