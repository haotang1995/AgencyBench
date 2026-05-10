# current_progress_run_full_eval_v2.md — live status

**Active step:** A — install `@gair/sii-cli` and patch `Dockerfile`.

**Plan checkpoints**

- [ ] A. Install `@gair/sii-cli` Node CLI; `which sii-bridge` returns a path; same line in Dockerfile.
- [ ] B. `progress/azure_overlay.env` written and gitignored.
- [ ] C. SDK smoke-test round-trip with GPT-5 succeeds.
- [ ] D. `MCP/scenario2` produces a fresh `meta_eval.json` with non-empty `agent_output`.
- [ ] E. `agent-infra/sandbox` container running and reachable from this container.
- [ ] F. `scripts/run_one_each.sh` exists; dry-run lists 32 invocations; `--only` works.
- [ ] G. `scripts/show_chat_history.py` exists; transcripts written.
- [ ] H. All scenarios run; `progress/summary.md` lists every one.

**Right now:** running `npm install -g --cache /tmp/npm-cache @gair/sii-cli`.
