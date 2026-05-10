# Tasks

## Done (`run_full_eval_v2` topic)

Plan: `progress/plan_run_full_eval_v2.md`
Final report: `progress/FINAL_REPORT.md`
Runbook: `progress/HOWTO_run_full_eval_v2.md`

- [x] **Verify the AgencyBench-v2 harness runs in this Docker.** Discovered
      and fixed 9 separate gaps (missing `sii-bridge` npm CLI, Azure proxy
      X-API-Key header, bridge URL azure-detection heuristic, hardcoded
      `max_tokens`, missing SDK kwarg, missing javac/gh/litellm/pymongo,
      broken `--description` defaults and incompatibility with Frontend/Game
      argparse, `localhost:8080` unreachable from inside our container,
      `gzy/claude-4-sonnet` judge model alias).
- [x] **Wire GPT-5 via the Azure OAI-compat proxy** in `prv_oai_example/.env_oai`.
      Single overlay at `progress/azure_overlay.env`; target, text-judge,
      vision-judge all route through `http://127.0.0.1:7333/v1`.
- [x] **Run one attempt of each of the 32 scenarios.** 28 of 32 produced
      `meta_eval.json` plus chat + tool transcripts.
        - 28 transcripts at `progress/transcripts/20260510-fullsweep2/*.md`
        - 3 timed out at 60 min: Code/2, Code/3, Research/5
        - 1 skipped: MCP/scenario1 (needs GitHub PAT)
        - Sum of numeric scores ≈ 515.84
        - Perfect runs: Code/1, Code/6, Code/7, Frontend/3, Game/6, Game/8, MCP/2

## Potential follow-ups (not started)

- Retry the 3 timed-out scenarios with `PER_SCENARIO_TIMEOUT=10800` (3 hours).
- Stand up a real MongoDB at `127.0.0.1:27017` to unblock the remaining
  Code/scenario8 rubric points (currently 20.76/50).
- Provide `MCP_GITHUB_TOKEN` + a scratch GitHub repo to include MCP/scenario1.
- Investigate the GPT-5 "doubled workspace path" mistake on Game/{1,2,5,7,9}
  + Frontend/scenario2 (Chinese-prompt interpretation).
