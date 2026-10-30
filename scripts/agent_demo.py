"""Agent 演示：命令行验证工具调用链路（第3步验收脚本）。

用法:
  .venv/Scripts/python.exe scripts/agent_demo.py 帮我记录今天深蹲100公斤5组每组5次
  .venv/Scripts/python.exe scripts/agent_demo.py    # 无参数进入交互模式
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.loop import ToolAgent  # noqa: E402


def show(agent: ToolAgent, query: str) -> None:
    print(f"\n用户: {query}")
    result = agent.run(query)
    for t in result.tool_trace:
        print(f"  ⚙ {t['tool']}({t['args']})")
        print(f"     → {t['result'][:120]}{'...' if len(t['result']) > 120 else ''}")
    print(f"助手: {result.answer}")


def main() -> None:
    agent = ToolAgent()
    if len(sys.argv) > 1:
        show(agent, " ".join(sys.argv[1:]))
        return
    print("Agent 交互模式（工具调用全程可见），输入 q 退出")
    while True:
        try:
            query = input("\n用户> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not query or query.lower() in {"q", "quit", "exit"}:
            break
        show(agent, query)


if __name__ == "__main__":
    main()
