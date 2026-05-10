#!/usr/bin/env python3
"""Step C smoke test: open an SII agent session against Azure GPT-5 via the
OAI-compat proxy, ask it to inspect /tmp, print every event we receive."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from sii_agent_sdk import (
    AssistantMessage,
    SiiAgentOptions,
    SiiAgentSession,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

PROMPT = (
    "List the files at the top level of /tmp using a shell tool, then in one "
    "sentence describe what you see. Stop after that."
)


def _truncate(s: str, n: int = 400) -> str:
    s = s.replace("\n", "\\n")
    return s if len(s) <= n else s[:n] + f"…(+{len(s)-n} chars)"


async def main() -> int:
    base_url = os.environ["SII_AGENT_API_BASE_URL"]
    api_key = os.environ["SII_AGENT_API_KEY"]
    model = os.environ.get("SII_TARGET_MODEL", "gpt-5")

    env = {
        "OPENAI_API_KEY": api_key,
        "OPENAI_BASE_URL": base_url,
        "SII_OPENAI_API_KEY": api_key,
        "SII_OPENAI_BASE_URL": base_url,
        "SII_OPENAI_MODEL": model,
    }

    workdir = Path(tempfile.mkdtemp(prefix="sii-smoke-"))
    print(f"[smoke] cwd={workdir}  model={model}  base={base_url}")

    options = SiiAgentOptions(
        system_prompt="You are a helpful assistant.",
        max_turns=8,
        auth_type="USE_OPENAI",
        cwd=str(workdir),
        yolo=True,
        allowed_tools=[],
        model=model,
        env=env,
        log_events=False,
    )

    session = SiiAgentSession(base_options=options)

    n_assistant_text = 0
    n_tool_call = 0
    n_tool_result = 0
    async for msg in session.run(PROMPT):
        cls = type(msg).__name__
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    n_assistant_text += 1
                    print(f"[ASSISTANT TEXT] {_truncate(block.text)}")
                elif isinstance(block, ToolUseBlock):
                    n_tool_call += 1
                    print(f"[TOOL CALL] {block.name}({_truncate(str(block.input), 200)})")
                else:
                    print(f"[ASSISTANT BLOCK {type(block).__name__}] {_truncate(str(block))}")
        elif isinstance(msg, ToolResultBlock):
            n_tool_result += 1
            print(f"[TOOL RESULT] {_truncate(str(msg.content) if msg.content else '<empty>', 300)}")
        else:
            print(f"[{cls}] {_truncate(str(msg))}")

    print()
    print(f"[smoke] DONE — assistant_text_blocks={n_assistant_text} tool_calls={n_tool_call} tool_results={n_tool_result}")
    return 0 if (n_assistant_text > 0) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
