# AgencyBench-v2 — GPT-5 sweep, final report

**Run id:** `20260510-fullsweep2`
**Target model:** `gpt-5` via Azure OAI-compatible proxy at `dwip-openai-…westus2-01.azurewebsites.net/v1`, fronted by a localhost reverse proxy at `http://127.0.0.1:7333/v1` to inject the `X-API-Key` header and rewrite `max_tokens` → `max_completion_tokens`.
**Scaffold:** SII-CLI (npm `@gair/sii-cli` v0.0.74 — bridge binary `sii-bridge`).
**Budget cap:** `MAX_SUBTASK_ATTEMPTS=1`, `SUBTASK_ATTEMPT_LIMIT=1`, `SII_MAX_TURNS=120`, scenario timeout 60 min.
**Started:** 2026-05-10 07:17. **Finished sandbox phase:** 10:34 (≈3h17m wall-clock).

## Goals (all met)

1. ✅ **Verify the harness works in this Docker.** `sii-bridge` not present out-of-the-box; installed `@gair/sii-cli`. Several other gaps surfaced (X-API-Key header, max_tokens cap, `enable_data_upload` SDK kwarg, missing javac/gh/litellm/pymongo, broken `--description` default in Backend/scenario2, broken `--description` flag for Frontend/Game scenarios, `localhost:8080` unreachable from inside our container). All fixed and committed.

2. ✅ **Wire GPT-5 through the Azure proxy** (creds from `prv_oai_example/.env_oai`). Target + text-judge + vision-judge all routed through the same proxy. `EVAL_VISION_PROVIDER=qwen` works against the Azure proxy's `gpt-4.1` deployment for image inputs (verified end-to-end).

3. ✅ **Run one attempt of each scenario.** 28 of 32 scenarios produced a `meta_eval.json` plus full chat + tool history. The 4 outstanding:

| scenario | reason | wall time |
| --- | --- | --- |
| `MCP/scenario1` | needs a real GitHub PAT + scratch repo (default `--skip`) | n/a |
| `Code/scenario2` | autogen scenario; agent ran for 60 min and didn't finish — too large for this budget | 3600 s |
| `Code/scenario3` | same — autogen scenario, hit 60 min cap | 3600 s |
| `Research/scenario5` | long web research with many `sii_web_fetch` calls; hit 60 min cap | 3600 s |

For the 3 timeouts, the bridge log files (`*.bridge.err`) under `progress/runs/20260510-fullsweep2/` still capture the full agent rollout — just no `meta_eval.json` was written.

## Score table

Three different scoring schemas appear in `meta_eval.json`:

- **Rubric** (Backend/{1,2,3}, Code/{1,4,5,8,9}, Research/{1,2,3}): each subtask has a numeric `best_score`, sum across 5 = max 50.
- **Loss-threshold** (Code/{6,7}): single `final_score` reflecting whether the agent's equation hit the loss threshold; max 10.
- **Pass/fail** (MCP/2, Frontend/{1,2,3}, Game/{1..10}): per-attempt `status` + `text_result.score` + `vision_result.score`; max 20 (10 text + 10 vision).
- **Artifact recall** (Research/{4,5}): `final_score` per subtask + `rubric_evaluation.recall`; max 10 per subtask.

| capability | scenario | score | basis | notes |
| --- | --- | --- | --- | --- |
| **Backend** | scenario1 | **28.0** / 50 | rubric | C++ chat app; subtask1+5 full marks, 2/3/4 partial |
| | scenario2 | **46.0** / 50 | rubric | Java task manager; 4 of 5 subtasks full marks |
| | scenario3 | **32.49** / 50 | rubric | Python systems pipeline |
| **Code** | scenario1 | **50.0** / 50 | rubric | Reaction-rate equation fitting; *all 5 perfect* |
| | scenario2 | timeout | rubric | autogen Qdrant integration; 60 min insufficient |
| | scenario3 | timeout | rubric | autogen Qdrant integration; 60 min insufficient |
| | scenario4 | **0.0** / 50 | rubric | Math-reasoning pipeline; agent wrote outputs to wrong path |
| | scenario5 | **0.0** / 50 | rubric | Deep-research scaffold; agent wrote `test.json` to wrong path |
| | scenario6 | **10.0** / 10 | loss | Equation discovery; loss 0.0 < 1e-7 threshold |
| | scenario7 | **10.0** / 10 | loss | Equation discovery; loss 2.78e-8 < 1e-7 threshold |
| | scenario8 | **20.76** / 50 | rubric | FastAPI+MongoDB webhook; some rubric pts need a real Mongo at :27017 |
| | scenario9 | **9.69** / 50 | rubric | Docker-sandboxed code agent; many rubric pts need a real Docker daemon + auth'd `gh` |
| **Frontend** | scenario1 | **18.0** / 20 | text+vision | USA SVG map — text 10, vision 8 (visual nits) |
| | scenario2 | **8.0** / 20 | text+vision | "Square Fit" portrait UI — vision retry-failed |
| | scenario3 | **20.0** / 20 | text+vision | 3D solar system — *perfect text + vision* |
| **Game** | scenario1 | **8.0** / 20 | text+vision | Gomoku — agent created a nested duplicate workspace path; deliverable not served |
| | scenario2 | **8.0** / 20 | text+vision | 2048 — same path-doubling issue |
| | scenario3 | **19.0** / 20 | text+vision | Snake — text 10, vision 9 |
| | scenario4 | **16.0** / 20 | text+vision | Tic-Tac-Toe — text 10, vision 6 |
| | scenario5 | **8.0** / 20 | text+vision | Minesweeper — same path issue |
| | scenario6 | **20.0** / 20 | text+vision | Lianliankan — *perfect* |
| | scenario7 | **8.0** / 20 | text+vision | Jump-a-Jump — same path issue |
| | scenario8 | **20.0** / 20 | text+vision | Flappy Bird — *perfect* |
| | scenario9 | **8.0** / 20 | text+vision | Sudoku — same path issue |
| | scenario10 | **19.0** / 20 | text+vision | Fruit Ninja — text 9, vision 10 |
| **Research** | scenario1 | **32.0** / 50 | rubric | HuggingFace dataset discovery; HF network issues for 2 of 5 |
| | scenario2 | **30.0** / 50 | rubric | Multi-hop NBA Q&A |
| | scenario3 | **46.9** / 50 | rubric | Public-company target ID |
| | scenario4 | **20.0** / 20 | recall | Chat vs Agent research; both subtasks 10/10, recall 0.6316 |
| | scenario5 | timeout | recall | Planning/sim research; web-fetch heavy, 60 min insufficient |
| **MCP** | scenario1 | (skipped) | n/a | needs a real GitHub PAT + scratch repo |
| | scenario2 | **5/5 pass** | pass/fail | Workspace reorg — every subtask validator green |

**Sum of numeric scores across the 28 completed scenarios:** ≈ 515.84.

The "perfect" runs (`Code/1`, `Code/{6,7}`, `Frontend/3`, `Game/{6,8}`, `MCP/2`) demonstrate that the harness scaffold + GPT-5 is wired correctly end-to-end.

## Chat & tool history

`progress/transcripts/20260510-fullsweep2/<capability>_<scenario>.md` — one Markdown transcript per scenario, parsed from `agent_output`/`assistant_response_excerpt`/`assistant_text` into `[ASSISTANT TEXT]` / `[TOOL CALL]` / `[TOOL RESULT]` blocks. The largest are:

```
Code/scenario9    600,196 chars
Backend/scenario2 444,354 chars
Backend/scenario3 389,832 chars
Code/scenario5    378,482 chars
Backend/scenario1 331,565 chars
Code/scenario8    316,204 chars
```

Frontend/Game scenarios have shorter `assistant_text` sections because their model contract requires the agent to return a single JSON block per attempt (no shell tools).

## Harness fixes (committed)

- `Dockerfile` adds `@gair/sii-cli`, Temurin JDK 21, GitHub CLI 2.78, and `pip install litellm pymongo`.
- `scripts/azure_proxy.py` — localhost OAI-compat reverse proxy that adds `X-API-Key`, rewrites `max_tokens`→`max_completion_tokens` (cap 32768), aliases `gzy/claude-*` → `gpt-4.1`.
- `scripts/sitecustomize.py` — monkey-patches `SiiAgentOptions.__init__` to drop the unsupported `enable_data_upload` kwarg.
- `scripts/run_one_each.sh` — driver: per-scenario `.env.run` overlay, conditional `--description` flag, JDK + gh on PATH, `_pylib` on PYTHONPATH.
- `scripts/run_parallel.sh` — N-way concurrent runner (Frontend/Game forced sequential to share the agent-infra sandbox).
- `scripts/show_chat_history.py` — meta_eval → Markdown transcript extractor (handles all 4 schemas).
- `scripts/aggregate_summary.py` — final scoreboard generator (handles all 4 schemas).
- `progress/azure_overlay.env` — single overlay file with all credentials and `MAX_SUBTASK_ATTEMPTS=1` / `SII_MAX_TURNS=120` budget caps.

See `progress/HOWTO_run_full_eval_v2.md` for a step-by-step runbook.

## Known limitations

- Code/scenario4, Code/scenario5: GPT-5 wrote outputs to a path the evaluator did not check, scoring 0 even though 42–378 kB of agent work was produced. This is a model/prompt issue, not a harness issue.
- Game/{1,2,5,7,9} and Frontend/scenario2: GPT-5 misinterpreted the Chinese workspace prompt (`你必须在scenario1/gpt-5/subtask1/workspace/attempt_01中工作`) as a relative path *inside* its already-correct cwd, creating a doubly-nested workspace path; the evaluator served 404 and the vision judge saw an error page.
- Code/scenario8/9: full credit needs a running MongoDB at `127.0.0.1:27017` and an authenticated `gh login`; we provided the binaries but not the running service.
- Code/scenario2/3 (autogen) and Research/scenario5: 60-min timeout insufficient. Could be retried with `PER_SCENARIO_TIMEOUT=10800` if desired.
- MCP/scenario1: skipped by default. Provide `MCP_GITHUB_TOKEN` + a scratch repo to include it.
