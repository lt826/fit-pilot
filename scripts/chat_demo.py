"""完整助手演示：LangGraph 路由 + 工具 + RAG + 记忆（第4步验收入口）。

用法:
  .venv/Scripts/python.exe scripts/chat_demo.py 我这周练了几次腿会不会太频繁
  .venv/Scripts/python.exe scripts/chat_demo.py    # 交互模式（多轮记忆生效）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.graph import FitnessCoach  # noqa: E402

ROUTE_CN = {"chat": "闲聊", "knowledge": "知识问答", "task": "任务执行", "mixed": "混合(工具+检索)"}


def show(coach: FitnessCoach, query: str) -> None:
    print(f"\n用户: {query}")
    result = coach.chat(query)
    print(f"[路线: {ROUTE_CN.get(result.route, result.route)}]")
    for t in result.tool_trace:
        print(f"  ⚙ {t['tool']}({t['args']})")
    if result.citations:
        print(f"  📚 引用: {'; '.join(result.citations)}")
    print(f"助手: {result.answer}")


def main() -> None:
    print("加载中（分词器/向量库首次加载稍慢）...")
    coach = FitnessCoach()
    if len(sys.argv) > 1:
        show(coach, " ".join(sys.argv[1:]))
        return
    print("FitPilot 完整模式（多轮记忆已启用），输入 q 退出")
    while True:
        try:
            query = input("\n用户> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not query or query.lower() in {"q", "quit", "exit"}:
            break
        show(coach, query)


if __name__ == "__main__":
    main()
