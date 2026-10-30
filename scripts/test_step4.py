"""第4步验收：单进程连续 7 个场景，覆盖路由四分支 + 追问改写 + 混合链路 + 记忆 + 拒答。

用法: .venv/Scripts/python.exe scripts/test_step4.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.graph import FitnessCoach  # noqa: E402
from app.db.database import get_conn  # noqa: E402

SCENARIOS = [
    ("①闲聊", "你好，你能帮我做什么？"),
    ("②知识", "新手一周练几次比较好？"),
    ("③追问(改写)", "那每次练多长时间呢？"),  # 指代上轮，测 query 改写
    ("④任务", "帮我记录今天卧推60公斤4组每组8次"),
    ("⑤混合(招牌)", "我这周练了几次腿？会不会太频繁？"),
    ("⑥画像抽取", "对了，我的目标是增肌，不过腰有点旧伤"),
    ("⑦域外拒答", "Python爬虫怎么写？"),
]


def main() -> None:
    coach = FitnessCoach()
    for label, query in SCENARIOS:
        r = coach.chat(query)
        tools = ",".join(t["tool"] for t in r.tool_trace) or "-"
        cite = f" 引用{len(r.citations)}条" if r.citations else ""
        print(f"\n{label} → 路线={r.route} 工具={tools}{cite}")
        print(f"  答: {r.answer[:180]}{'...' if len(r.answer) > 180 else ''}")

    print("\n===== 落库验证 =====")
    with get_conn() as conn:
        prof = dict(conn.execute("SELECT goal,injuries FROM user_profile WHERE id=1").fetchone())
        n_train = conn.execute("SELECT COUNT(*) FROM training_logs").fetchone()[0]
    print(f"user_profile: goal={prof['goal']!r} injuries={prof['injuries']!r}")
    print(f"training_logs 共 {n_train} 条")


if __name__ == "__main__":
    main()
