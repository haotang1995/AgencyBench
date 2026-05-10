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
