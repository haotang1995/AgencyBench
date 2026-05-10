#!/usr/bin/env python3
"""Pretty-print the chat + tool-call history from a meta_eval.json.

Usage:
    scripts/show_chat_history.py path/to/meta_eval.json [--out path.md]
    scripts/show_chat_history.py path/to/meta_eval.json [--all]   # don't truncate

The agent_output that eval_task.py captures is a single big string per
attempt, with a fairly consistent shape:

    <assistant text>
    🔧 Tool result: <stdout>
    Command: ...
    Stdout: ...
    Stderr: ...
    Exit Code: ...
    🔧 工具调用 / 名称: ... / 参数: { ... }
    ...

This script splits on the obvious markers (`🔧`, `Command:`, `Stdout:`,
`================...`) and rebuilds a cleaner transcript:

    [ASSISTANT] <text>
    [TOOL CALL] name(args)
    [TOOL RESULT] stdout (truncated)
    ...
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ASSISTANT_HDR = re.compile(r"={70,}\s*\n\s*[💬🤖]\s*AI\s*回复.*?\n={70,}", re.UNICODE)
TOOL_RESULT_HDR = re.compile(r"─{30,}\s*\n\s*[✅❌]\s*工具执行结果.*?\n─{30,}", re.UNICODE)
TOOL_CALL_PREFIX = "🔧 工具调用"
TOOL_RESULT_PREFIX = "🔧 Tool result:"


def _truncate(s: str, n: int = 2000) -> str:
    s = s.rstrip()
    return s if len(s) <= n else s[:n] + f"\n…(+{len(s)-n} chars)"


def parse_agent_output(raw: str, max_block: int = 2000) -> list[str]:
    """Return a list of formatted lines for the transcript."""
    out: list[str] = []
    if not raw:
        return out

    # Quick path: if no decorators, return as a single assistant text block.
    if "🔧" not in raw and "工具" not in raw and "AI 回复" not in raw:
        out.append(f"[ASSISTANT TEXT]\n{_truncate(raw, max_block)}")
        return out

    # Walk the string looking for the big "================ AI 回复" headers.
    blocks = ASSISTANT_HDR.split(raw)
    if blocks and blocks[0].strip():
        # Anything before the first AI-reply header is preamble (status).
        out.append(f"[PRELUDE]\n{_truncate(blocks[0].strip(), max_block)}")
    for blk in blocks[1:]:
        # A block can contain several "tool call" sub-sections delimited by `--------------------------------------------------------------------------------`
        sub = blk.strip()
        if not sub:
            continue
        # Split by the dashed section separator that eval_task.py emits.
        sub_parts = re.split(r"\n-{60,}\n", sub)
        for part in sub_parts:
            part = part.strip()
            if not part:
                continue
            if part.startswith(TOOL_CALL_PREFIX) or "🧰 名称:" in part:
                # Extract name + args
                name = re.search(r"🧰\s*名称:\s*(\S+)", part)
                args = re.search(r"📋\s*参数:\s*(\{.*?\}|\[.*?\])", part, re.S)
                args_str = args.group(1).strip() if args else "{}"
                out.append(
                    f"[TOOL CALL] {name.group(1) if name else '?'}({_truncate(args_str, max_block)})"
                )
            elif part.startswith("📝") or "📝 文本内容:" in part:
                txt = re.sub(r"^.*?📝\s*文本内容:\s*", "", part, count=1, flags=re.S).strip()
                if txt.startswith(TOOL_RESULT_PREFIX):
                    out.append(f"[TOOL RESULT]\n{_truncate(txt[len(TOOL_RESULT_PREFIX):].strip(), max_block)}")
                else:
                    out.append(f"[ASSISTANT TEXT]\n{_truncate(txt, max_block)}")
            else:
                out.append(f"[ASSISTANT BLOCK]\n{_truncate(part, max_block)}")

    # Pull out the explicit tool-result envelopes too.
    for m in TOOL_RESULT_HDR.split(raw)[1:]:
        body = re.sub(r"^.*?(结果:|Result:)\s*", "", m, count=1, flags=re.S).split("\n----")[0].strip()
        if body and not any(body[:120] in x for x in out):
            out.append(f"[TOOL RESULT]\n{_truncate(body, max_block)}")
    return out


def render_attempt(attempt: dict, max_block: int, parent_name: str = "?") -> str:
    lines: list[str] = []
    sub = attempt.get("subtask", parent_name)
    idx = attempt.get("attempt_index", "?")
    score = attempt.get("score")
    rubric = attempt.get("rubric") or {}
    failed = ", ".join(rubric.get("failed_points") or []) or "(none)"
    pass_count = rubric.get("pass_count")
    total = rubric.get("total_points")
    text_result = attempt.get("text_result") or {}
    vision_result = attempt.get("vision_result") or {}
    status_str = attempt.get("status")
    if status_str in ("pass", "fail", "retry"):
        # Frontend/Game schema
        lines.append(
            f"### {sub} attempt {idx}  —  status={status_str}  text={text_result.get('score')}  vision={vision_result.get('score')}"
        )
        reasons = []
        if text_result.get('reason'): reasons.append(f"text: {text_result['reason']}")
        if vision_result.get('reason'): reasons.append(f"vision: {vision_result['reason']}")
        if reasons:
            lines.append("")
            for r in reasons:
                lines.append(f"_{_truncate(r, 600)}_")
    elif score is None and "success" in attempt:
        # MCP-style schema: pass/fail per attempt instead of numeric rubric.
        success = attempt.get("success")
        validator = attempt.get("validator_message") or ""
        lines.append(
            f"### {sub} attempt {idx}  —  success={success}  validator: {validator}"
        )
    else:
        lines.append(
            f"### {sub} attempt {idx}  —  score={score} ({pass_count}/{total})  failed: {failed}"
        )
    lines.append("")
    body = (
        attempt.get("agent_output")
        or attempt.get("assistant_response_excerpt")
        or attempt.get("assistant_text")
        or ""
    )
    blocks = parse_agent_output(body, max_block=max_block)

    # Frontend/Game scenarios store agent_messages as a list of dicts.
    agent_msgs = attempt.get("agent_messages") or []
    if isinstance(agent_msgs, list):
        for m in agent_msgs:
            if not isinstance(m, dict):
                continue
            mt = m.get("type")
            if mt == "assistant":
                # nested content blocks
                for c in m.get("content") or []:
                    if isinstance(c, dict):
                        if c.get("type") == "text" and c.get("text"):
                            blocks.append(f"[ASSISTANT TEXT]\n{_truncate(c['text'], max_block)}")
                        elif c.get("type") in ("tool_use", "tool_call"):
                            args = c.get("input") or {}
                            blocks.append(f"[TOOL CALL] {c.get('name')}({_truncate(json.dumps(args, ensure_ascii=False), max_block)})")
            elif mt == "tool_result":
                content = m.get("content")
                if isinstance(content, (list, dict)):
                    content = json.dumps(content, ensure_ascii=False)
                if content:
                    blocks.append(f"[TOOL RESULT]\n{_truncate(str(content), max_block)}")

    if not blocks:
        lines.append("_no agent_output_")
    else:
        for b in blocks:
            lines.append(b)
            lines.append("")
    cmds = attempt.get("commands") or []
    if cmds:
        # `commands` is sometimes a list-of-dicts and sometimes a dict
        # keyed by command name.
        if isinstance(cmds, dict):
            iterable = list(cmds.values())
        else:
            iterable = list(cmds)
        lines.append("**evaluator commands:**")
        for c in iterable:
            if not isinstance(c, dict):
                lines.append(f"- {str(c)[:160]}")
                continue
            name = c.get("name", "?")
            ec = c.get("returncode")
            stderr = (c.get("stderr") or "").strip()
            lines.append(f"- {name}  exit={ec}  stderr={stderr[:120]!r}")
    fb = (attempt.get("feedback") or "").strip()
    if fb:
        lines.append("")
        lines.append("**simulated-user feedback:**")
        lines.append(_truncate(fb, max_block))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Render meta_eval.json as a transcript.")
    ap.add_argument("meta_eval", type=Path)
    ap.add_argument("--out", type=Path, default=None, help="write Markdown to this file")
    ap.add_argument("--all", action="store_true", help="do not truncate blocks")
    args = ap.parse_args()

    if not args.meta_eval.exists():
        print(f"missing {args.meta_eval}", file=sys.stderr)
        return 2

    data = json.loads(args.meta_eval.read_text(encoding="utf-8"))
    max_block = 10**6 if args.all else 2000
    chunks = []
    chunks.append(f"# Transcript — {args.meta_eval}\n")
    chunks.append(f"- model: `{data.get('model','?')}`")
    chunks.append(f"- scorer: `{data.get('scorer','?')}`")
    chunks.append(f"- max_attempts: {data.get('max_attempts','?')}")
    raw_sts = data.get("subtasks") or []
    if isinstance(raw_sts, dict):
        sts = []
        for name, st in raw_sts.items():
            if isinstance(st, dict):
                st = dict(st)
                st.setdefault("name", name)
                sts.append(st)
    else:
        sts = list(raw_sts)
    chunks.append(f"- subtasks: {len(sts)}")
    chunks.append("")
    for st in sts:
        if not isinstance(st, dict):
            continue
        chunks.append(f"## {st.get('name', st.get('subtask', '?'))}")
        if st.get("best_score") is not None:
            chunks.append(f"- best_score: {st.get('best_score')}")
        if st.get("final_score") is not None:
            chunks.append(f"- final_score: {st.get('final_score')}")
        if st.get("success") is not None:
            chunks.append(f"- success: {st.get('success')}")
        chunks.append("")
        for at in st.get("attempts") or []:
            chunks.append(render_attempt(at, max_block, parent_name=st.get('name', '?')))
            chunks.append("")
    md = "\n".join(chunks)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
        print(f"wrote {args.out} ({len(md):,} chars)")
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
