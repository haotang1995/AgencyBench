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

