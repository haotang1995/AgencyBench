# Plan: Verify the AgencyBench-v2 harness, wire Azure GPT-5, and run one attempt of each scenario

**Topic slug:** `run_full_eval_v2`

**User goals (the only three):**

1. **Verify the harness works in this Docker.** Refine `Dockerfile` if needed.
2. **Wire up GPT-5 via the Azure-hosted OAI-compatible proxy** in `prv_oai_example/.env_oai` (base URL `https://dwip-openai-ehe0b4f3cdctbfbp.westus2-01.azurewebsites.net/v1`, key `super-secret-key-i-chose`, optional `X-API-Key` header).
3. **Run one attempt of each of the 32 AgencyBench-v2 scenarios** using Azure GPT-5 as the agent under test, then surface the chat + tool history per scenario.

Explicitly **not** in scope: multi-attempt repeats, the full-coverage paper sweep, `--visualize` mode, MCP/scenario1's GitHub-write rollout (skip if no scratch repo).

---

## 1. What I learned from the repo (frozen facts)

- `find AgencyBench-v2 -name eval_task.py | wc -l` → **32** scenarios across Backend (3), Code (9), Frontend (3), Game (10), Research (5), MCP (2).
- The Frontend (3) + Game (10) = **13** scenarios call `client.browser.get_info()` / `playwright.chromium.connect_over_cdp(...)` — they require a running `ghcr.io/agent-infra/sandbox:latest` container reachable at `SANDBOX_BASE_URL` (default `http://localhost:8080`). Verified by `grep -l SANDBOX_BASE_URL`.
- 16 scenarios use a text LLM-as-judge (`EVAL_TEXT_API_KEY`); 13 use a vision judge (`EVAL_VISION_PROVIDER` / `VISION_MODEL`); MCP/scenario1 needs `MCP_GITHUB_TOKEN` + a writable GitHub repo.
- `eval_task.py` is identical in shape across scenarios: argparse with `--env`, `--description`, `--start-subtask`, `--eval-only`, `--visualize`. It loads `.env`, builds an `EnvConfig`, and (unless `--eval-only`) drives the agent rollout via `sii_agent_sdk`.
- `sii_agent_sdk` (Python) does **not** call any model directly — it spawns a Node.js child process called `sii-bridge`. Search order: `$SII_BRIDGE_PATH`, then `<sdk>/../bridge/dist/index.js`, then `which sii-bridge`. None of these currently exist in the container.
- `npm view @gair/sii-cli` → version 0.0.74, owned by `snowy2002@sjtu.edu.cn` (the same maintainer as the Python SDK), exposes the binaries `sii`, `sii-bridge`, `sii-cli`. **This is the missing piece.**
- `validate_auth_config` in `sii_agent_sdk/query.py` says:
  - `USE_OPENAI` requires only `SII_OPENAI_BASE_URL` + (`SII_OPENAI_API_KEY` or `OPENAI_API_KEY`). **No SII login.**
  - `USE_OPENAI_WITH_SII_TOOLS` (the default in MCP/scenario2) additionally requires `SII_USERNAME` + `SII_PASSWORD`. We don't have those, so we'll override `SII_AUTH_TYPE=USE_OPENAI` everywhere.
- The Azure proxy works (verified): `gpt-4.1-mini` and `gpt-5-mini` both responded to a vanilla `POST /chat/completions`. `gpt-5*` returns its tokens under `reasoning_tokens` so the harness must allow enough `max_completion_tokens`.

## 2. Suspected harness gaps (to fix or rule out)

1. **`@gair/sii-cli` Node CLI not installed.** Required by the Python SDK to start the bridge. Fix: add `npm install -g @gair/sii-cli` to the Dockerfile and install it in the live container. **High confidence this is needed.**
2. **NPM cache permissions.** `npm` complains about root-owned `/root/.npm/_cacache` for the `sandbox` user. The Dockerfile installs other npm globals as root in an earlier `RUN` so we can chain the install in the same RUN. For the live container we'll use `--cache /tmp/npm-cache`.
3. **Playwright Chromium binary.** Frontend/Game evals call `connect_over_cdp(...)` (uses the *remote* sandbox Chromium) for non-visualize runs. We don't expect to need a local Chromium. Will only patch if a smoke run says otherwise.
4. **`X-API-Key` header.** The proxy's `.env_oai` sets both `OPENAI_API_KEY=...` and `X_API_KEY=...`. The proxy already accepted bearer-only `curl` requests, so we'll start without injecting `X-API-Key` and only add it if a 401/403 surfaces.
5. **`sandbox` container reachability for Frontend/Game.** Resolved: `/var/run/docker.sock` is mounted (mode `srw-rw----`, group `adm` which `sandbox` belongs to) and `docker ps` works — host docker is fully accessible. Step E will pull `ghcr.io/agent-infra/sandbox:latest` and run it; only open question is whether to use `--network=host` or a published-port + host-IP from this container, decided at run time.

## 3. Decisions

- **Target model:** `gpt-5` (or `gpt-5-mini` for cost). Default `gpt-5`; switch to `gpt-5-mini` if rate-limited.
- **Judge models:** all three (target / text-judge / vision-judge) come through the same Azure proxy. The evaluator's "qwen" branch is misnamed — it's a plain `openai.OpenAI(api_key=..., base_url=...)` chat-completions client with `image_url` data-URL blocks, so it accepts any OpenAI-compatible endpoint. Verified: the Azure proxy returned valid responses to image-input prompts on `gpt-4.1`, `gpt-4o`, and `gpt-5`. Plan: `EVAL_TEXT_MODEL=gpt-4.1-mini` (cheap text judge), `EVAL_VISION_PROVIDER=qwen` + `VISION_MODEL=gpt-4.1` + `QWEN_VISION_BASE_URL`/`QWEN_VISION_API_KEY` pointing at the Azure proxy. **No `GOOGLE_API_KEY` needed**, vision-rubric points are scored normally.
- **Scope cap:** `MAX_SUBTASK_ATTEMPTS=1`, `SUBTASK_ATTEMPT_LIMIT=1`, `SII_MAX_TURNS=120` (down from 1000). One attempt per subtask, ≤ ~120 tool calls per subtask. This bounds spend to roughly 32 × 5 × 120k ≈ ~20M target-model tokens worst case; in practice most scenarios will exit far earlier.
- **Skip list:** `MCP/scenario1` (needs a GitHub PAT + scratch repo; out of scope unless user provides). The driver script accepts `--skip MCP/scenario1`.

## 4. Plan steps

Each step gets its own commit + an entry in `progress_run_full_eval_v2.md` with verification output.

### Step A — Patch the Dockerfile to install `@gair/sii-cli`
- Add the install in the same `RUN` block that already sets up other npm CLIs (`@google/gemini-cli`, `@openai/codex`, `@github/copilot`).
- Also install live in the running container (`npm install -g --cache /tmp/npm-cache @gair/sii-cli`) so we don't have to rebuild before testing.
- **Verify:** `which sii-bridge` returns a path; `sii-bridge --help 2>&1 | head` exits without `BridgeNotFoundError`.

### Step B — Build a single Azure-proxy overlay env file
- Create `progress/azure_overlay.env` (gitignored — contains the API key). Contents:
  ```
  SII_AGENT_API_KEY=<key from .env_oai>
  SII_AGENT_API_BASE_URL=https://dwip-...azurewebsites.net/v1
  SII_TARGET_MODEL=gpt-5
  SII_AUTH_TYPE=USE_OPENAI
  SII_SYSTEM_PROMPT=You are a helpful assistant.
  SII_MAX_TURNS=120
  MAX_SUBTASK_ATTEMPTS=1
  SUBTASK_ATTEMPT_LIMIT=1
  SII_USERNAME=
  SII_PASSWORD=
  CONDA_ENV_NAME=
  EVAL_TEXT_API_KEY=<same key>
  EVAL_TEXT_API_BASE_URL=<same base url>
  EVAL_TEXT_MODEL=gpt-4.1-mini
  EVAL_VISION_PROVIDER=qwen
  VISION_MODEL=gpt-4.1
  QWEN_VISION_BASE_URL=<same base url>
  QWEN_VISION_API_KEY=<same key>
  OPENAI_API_KEY=<same key>
  OPENAI_BASE_URL=<same base url>
  ```
- **Verify:** a Python one-liner sources the file, prints the resolved values, and confirms no `<…>` placeholders remain.

### Step C — Smoke-test the bridge with the simplest possible request
- Write a 30-line Python script that builds `SiiAgentOptions(auth_type="USE_OPENAI", model="gpt-5", env={...Azure proxy vars...})`, opens an `SDKAgentSession`, sends "list files in /tmp", and prints every message (including ToolUse/ToolResult).
- **Verify:** non-empty assistant text + at least one tool-use/tool-result block. If this fails, root-cause before touching any scenario.

### Step D — End-to-end run on one tiny non-sandbox scenario
- Pick `MCP/scenario2` (file reorganization, 5 subtasks, no sandbox, no GitHub).
- Override `.env` via the overlay; run `python eval_task.py` (no `--eval-only`).
- **Verify:** a fresh `meta_eval.json` is written under `MCP/scenario2/<model_slug>/...`, contains 5 subtasks, each with at least one attempt and a non-empty `agent_output`. Print a chat+tool transcript from one subtask as proof.

### Step E — Stand up the agent-infra sandbox (only if needed)
- For Frontend (3) + Game (10) scenarios: pull and run `ghcr.io/agent-infra/sandbox:latest` on `:8080`. If the AgencyBench container can't see `localhost:8080`, document the host-network workaround.
- **Verify:** `curl -fsS http://localhost:8080/v1/sandbox` (or whatever endpoint the SDK probes) returns 200; one Frontend smoke run reaches the playwright `connect_over_cdp` call without error.

### Step F — Build the per-scenario driver `scripts/run_one_each.sh`
- Iterates the 32 scenarios.
- For each: copies the scenario's `.env` to `<scenario>/.env.run`, overlays `progress/azure_overlay.env`, runs `python eval_task.py --env .env.run`, streams stdout/stderr to `progress/runs/<timestamp>/<capability>_<scenario>.log`.
- Honors `--skip <capability/scenario>` (default: `MCP/scenario1`).
- Honors `--only <capability/scenario>` for one-off reruns.
- Idempotent: skips a scenario whose `<scenario>/<model_slug>/meta_eval.json` already exists, unless `--force`.
- **Verify:** `--dry-run` prints the 31 (or 32) commands in the right order with the right `--env`. `--only MCP/scenario2` runs that one and writes its log file.

### Step G — Chat & tool-history extractor
- Build `scripts/show_chat_history.py` that, for any `meta_eval.json`, prints per subtask:
  - subtask name, score, rubric pass/total, failed points
  - For each attempt: a clean conversation transcript with assistant text blocks, `[TOOL CALL] name(args)` lines, and `[TOOL RESULT] ...` blocks (truncated by length).
- Run it across every produced `meta_eval.json` and dump per-scenario transcripts into `progress/transcripts/<capability>_<scenario>.md`.
- **Verify:** sampling 3 transcripts (one Backend, one Game, one Research) shows realistic agent behavior (commands, files written, deliverables).

### Step H — Summary report
- Aggregate `meta_eval.json` files into `progress/summary.json` and `progress/summary.md` with one row per scenario: model, score, total_points, attempts, # tool calls, runtime, log path, transcript path.
- Update `Dockerfile` if Step A/E required changes (it almost certainly did for the bridge).

## 5. Risks / unknowns

- **Bridge model-routing.** Even with `auth_type=USE_OPENAI`, the bridge may format requests in a way the Azure proxy doesn't accept (e.g. dropping `n` is fine; sending fields like `parallel_tool_calls` may not be). We'll see when Step C runs; fixes will go in `progress/progress_run_full_eval_v2.md` and may require either passing extra `env` vars to the bridge or downshifting to `gpt-4.1-mini` which is more permissive.
- **Vision evaluator.** Resolved: the "qwen" provider branch is a generic OpenAI-compatible vision client, so the Azure proxy works for vision judging too (verified end-to-end). No external Google dependency.
- **`MCP/scenario1`.** Skipped by default. If user provides a PAT + scratch repo, drop `--skip MCP/scenario1` from the driver invocation.
- **Sandbox container.** If the docker daemon is unavailable from inside our container (no `/var/run/docker.sock` mount), Frontend + Game scenarios will fail at the agent-infra connection step. Their `meta_eval.json` will still be written (the SDK gracefully fails the rubric) but the chat history will be short and dominated by the connection error. We'll document this rather than block.
- **Spend.** With `SII_MAX_TURNS=120`, `MAX_SUBTASK_ATTEMPTS=1`, GPT-5 input pricing, this run is on the order of low-tens of USD on Azure. Acceptable.

## 6. File conventions

- `progress/plan_run_full_eval_v2.md` — this file (source of truth for the plan).
- `progress/progress_run_full_eval_v2.md` — permanent log of every attempt incl. failures.
- `progress/current_progress_run_full_eval_v2.md` — live status of the active step.
- `progress/azure_overlay.env` — Azure proxy credentials (gitignore-protected).
- `progress/runs/<timestamp>/...` — per-scenario stdout logs.
- `progress/transcripts/<capability>_<scenario>.md` — extracted chat + tool history.
- `progress/summary.{json,md}` — final aggregated scoreboard.
- `scripts/run_one_each.sh`, `scripts/show_chat_history.py` — driver + extractor.

Commits use topic-prefixed messages (`feat:`, `fix:`, `docs:`, `chore:`).

## 7. Definition of done

- [ ] Step A: `which sii-bridge` returns a path inside the container; same change is in `Dockerfile`.
- [ ] Step C: a smoke `SDKAgentSession` round trip with GPT-5 via the Azure proxy returns at least one assistant text block + at least one tool call.
- [ ] Step D: `MCP/scenario2` produces a fresh `meta_eval.json` whose `agent_output` length is non-zero and visibly looks like Claude's reference run.
- [ ] Step F: the driver runs every non-skipped scenario; for each, either a `meta_eval.json` exists or a clearly-explained failure entry is in `progress_run_full_eval_v2.md`.
- [ ] Step G: a chat+tool-history transcript is generated for every scenario that has a non-empty `agent_output`.
- [ ] Step H: `progress/summary.md` lists all 32 scenarios with score (or "skipped"/"failed: <reason>") and links to its transcript and log.
- [ ] `Dockerfile` reflects every environment change actually needed (no drift).
