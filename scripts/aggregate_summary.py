#!/usr/bin/env python3
"""Walk progress/runs/<run_id>/ + the per-scenario meta_eval.json files,
aggregate into progress/summary.{json,md}.

Usage:
    scripts/aggregate_summary.py --run-id 20260510-fullsweep2
    scripts/aggregate_summary.py --run-id 20260510-fullsweep2 --transcripts
    # --transcripts also runs scripts/show_chat_history.py for each
    # scenario that produced a meta_eval.json, writing markdown into
    # progress/transcripts/<run_id>/<capability>_<scenario>.md.

Output rows:
    capability   scenario   status  score  total  attempts  tool_calls  secs  log  meta  transcript
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path("/workspace")
SCENARIOS_ROOT = ROOT / "AgencyBench-v2"
RUNS_ROOT = ROOT / "progress" / "runs"
TRANSCRIPTS_ROOT = ROOT / "progress" / "transcripts"
EXTRACTOR = ROOT / "scripts" / "show_chat_history.py"


def _model_slug(s: str) -> str:
    raw = s.strip().rsplit("/", 1)[-1]
    return "".join(c if c.isalnum() or c in "-._" else "_" for c in raw).strip("._-") or "model"


def _read_summary_tsv(p: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not p.exists():
        return out
    rows = p.read_text(encoding="utf-8").splitlines()
    if not rows:
        return out
    header = rows[0].split("\t")
    for r in rows[1:]:
        cols = r.split("\t")
        if len(cols) != len(header):
            continue
        rec = dict(zip(header, cols))
        out[rec["scenario"]] = rec
    return out


def _summarize_meta(meta_path: Path) -> dict:
    """Return uniform fields for either meta_eval schema."""
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"json parse: {exc}"}

    out: dict = {"model": data.get("model")}
    # Some scenarios (Code/scenario6 family) use `final_score` instead of
    # per-subtask rubric scoring. Surface it directly.
    if "final_score" in data:
        out["final_score"] = data.get("final_score")
    raw_sts = data.get("subtasks") or []
    # Frontend/Game schema: subtasks is a dict keyed by name. Normalize.
    if isinstance(raw_sts, dict):
        sts = []
        for name, st in raw_sts.items():
            if isinstance(st, dict):
                st = dict(st)
                st.setdefault("name", name)
                sts.append(st)
    else:
        sts = list(raw_sts)
    out["subtasks"] = len(sts)

    score_sum = 0.0
    total_sum = 0.0
    pass_sum = 0
    pass_total = 0
    success_sum = 0
    attempts = 0
    chars = 0
    tool_call_count = 0

    for st in sts:
        if not isinstance(st, dict):
            continue
        ats = st.get("attempts") or []
        attempts += len(ats)
        for a in ats:
            if not isinstance(a, dict):
                continue
            ao = a.get("agent_output") or a.get("assistant_response_excerpt") or a.get("assistant_text") or ""
            # Frontend/Game per-attempt also has agent_messages list with tool-use events.
            agent_msgs = a.get("agent_messages") or []
            if isinstance(agent_msgs, list):
                for m in agent_msgs:
                    if isinstance(m, dict):
                        if m.get("type") in ("tool_use", "tool_call") or "tool_use_id" in m:
                            tool_call_count += 1
            if isinstance(ao, str):
                chars += len(ao)
                # Three forms of "agent ran a tool" we may see:
                #   1. rubric scenarios: `🔧 工具调用` header per call
                #   2. MCP excerpt:      `🔧 Tool result:` per call
                #   3. preformatted:     `[TOOL CALL]` per call
                tool_call_count += (
                    ao.count("🔧 工具调用")
                    + ao.count("🔧 Tool result:")
                    + ao.count("[TOOL CALL]")
                )
            rub = a.get("rubric") or {}
            if rub:
                pass_sum += int(rub.get("pass_count") or 0)
                pass_total += int(rub.get("total_points") or 0)
            sc = a.get("score")
            if isinstance(sc, (int, float)):
                score_sum += float(sc)
            if "success" in a:
                if a.get("success") is True:
                    success_sum += 1
                total_sum += 1
            # Frontend/Game per-attempt: text_result.score + vision_result.score
            tr = a.get("text_result") or {}
            vr = a.get("vision_result") or {}
            if isinstance(tr.get("score"), (int, float)):
                score_sum += float(tr["score"])
            if isinstance(vr.get("score"), (int, float)):
                score_sum += float(vr["score"])
            # Frontend/Game per-attempt status
            if a.get("status") in ("pass", "fail"):
                if a.get("status") == "pass":
                    success_sum += 1
                total_sum += 1

    out["attempts"] = attempts
    out["agent_output_chars"] = chars
    out["tool_call_count"] = tool_call_count
    out["pass_points"] = f"{pass_sum}/{pass_total}" if pass_total else None
    # Prefer per-subtask rubric score sum; fall back to final_score for
    # the Code/scenario6 schema; fall back to per-subtask best_score sum.
    if score_sum:
        out["score_total"] = score_sum
    elif out.get("final_score") is not None:
        out["score_total"] = float(out["final_score"])
    else:
        # Fall back to per-subtask scoring fields, in priority order:
        # final_score (Research/4-5), best_score (Backend/Code rubric).
        bs_sum = 0.0
        for st in sts:
            if not isinstance(st, dict):
                continue
            if isinstance(st.get("final_score"), (int, float)):
                bs_sum += float(st["final_score"])
            elif isinstance(st.get("best_score"), (int, float)):
                bs_sum += float(st["best_score"])
        out["score_total"] = bs_sum if bs_sum else None
    out["success_total"] = f"{success_sum}/{int(total_sum)}" if total_sum else None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--target-model", default="gpt-5")
    ap.add_argument("--transcripts", action="store_true",
                    help="also run scripts/show_chat_history.py for each scenario")
    args = ap.parse_args()

    slug = _model_slug(args.target_model)
    run_dir = RUNS_ROOT / args.run_id
    if not run_dir.exists():
        print(f"missing {run_dir}")
        return 2
    tsv = _read_summary_tsv(run_dir / "summary.tsv")
    transcript_dir = TRANSCRIPTS_ROOT / args.run_id

    rows: list[dict] = []
    for cap_dir in sorted(SCENARIOS_ROOT.iterdir()):
        if not cap_dir.is_dir() or cap_dir.name not in {"Backend", "Code", "Frontend", "Game", "Research", "MCP"}:
            continue
        for sc_dir in sorted(cap_dir.iterdir()):
            if not sc_dir.is_dir() or not sc_dir.name.startswith("scenario"):
                continue
            cap_sc = f"{cap_dir.name}/{sc_dir.name}"
            meta = sc_dir / slug / "meta_eval.json"
            log = run_dir / f"{cap_dir.name}_{sc_dir.name}.log"
            row = {
                "scenario": cap_sc,
                "status": (tsv.get(cap_sc) or {}).get("status", "missing"),
                "exit_code": (tsv.get(cap_sc) or {}).get("exit_code", "-"),
                "secs": (tsv.get(cap_sc) or {}).get("secs", "-"),
                "log": str(log) if log.exists() else "-",
                "meta_eval": str(meta) if meta.exists() else "-",
            }
            row.update(_summarize_meta(meta))
            if args.transcripts and meta.exists():
                t_path = transcript_dir / f"{cap_dir.name}_{sc_dir.name}.md"
                subprocess.run(
                    ["python3", str(EXTRACTOR), str(meta), "--out", str(t_path)],
                    check=False,
                )
                row["transcript"] = str(t_path)
            rows.append(row)

    out_dir = ROOT / "progress"
    (out_dir / "summary.json").write_text(
        json.dumps({"run_id": args.run_id, "rows": rows}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    md = ["# Run summary — `" + args.run_id + "`", ""]
    md.append(f"target model: `{args.target_model}` (slug: `{slug}`)")
    md.append("")
    md.append("| scenario | status | secs | subtasks | attempts | tool calls | output chars | pass | score | success | meta_eval |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        md.append("| {sc} | {st} | {se} | {nst} | {na} | {tc} | {ac:,} | {pp} | {sc2} | {ss} | {me} |".format(
            sc=r["scenario"],
            st=r.get("status", "-"),
            se=r.get("secs", "-"),
            nst=r.get("subtasks", "-"),
            na=r.get("attempts", "-"),
            tc=r.get("tool_call_count", "-"),
            ac=r.get("agent_output_chars", 0) or 0,
            pp=r.get("pass_points") or "-",
            sc2=r.get("score_total") or "-",
            ss=r.get("success_total") or "-",
            me="yes" if r.get("meta_eval") and r["meta_eval"] != "-" else "no",
        ))
    if args.transcripts:
        md.append("")
        md.append("## Transcripts")
        for r in rows:
            t = r.get("transcript")
            if t:
                md.append(f"- [{r['scenario']}]({Path(t).relative_to(ROOT/'progress')})")
    (out_dir / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote {out_dir/'summary.md'} and {out_dir/'summary.json'} ({len(rows)} scenarios)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
