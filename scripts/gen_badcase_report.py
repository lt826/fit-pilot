"""第7步⑤：badcase 分析报告生成。

读取 data/eval/last_run.json 逐题明细，按失败模式归因分类：
- 检索未命中（hybrid 模式 hit@1 为假）
- 知识题误拒 / 拒答题漏拒
- 答案判定不通过（裁判判否：检索对了但答错 = 生成问题）
- Agent 题失败（工具没调对 / 综合错误）

输出 docs/badcase-report.md（含每类案例明细与修复方向）。
用法: .venv/Scripts/python.exe scripts/gen_badcase_report.py
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DETAIL = PROJECT_ROOT / "data" / "eval" / "last_run.json"
OUT = PROJECT_ROOT / "docs" / "badcase-report.md"

FIX_HINTS = {
    "检索未命中": "候选修复：查询改写/同义词扩展、调 RRF 候选数 k_each、语料补充该主题",
    "知识题误拒": "候选修复：下调闸门阈值或改用 rerank 分数做闸门信号",
    "拒答题漏拒": "候选修复：上调闸门阈值；检查该题检索分数分布",
    "生成质量（答非所问/要点缺失）": "候选修复：加强 prompt 要点覆盖要求、增大 k、引入 rerank 重排",
    "Agent工具/综合失败": "候选修复：工具描述精确化、混合链路合成 prompt 加强要点核对",
    "判定存疑（裁判误判可能）": "人工复核：参考答案要点是否过严/过宽",
}


def main() -> None:
    rows = json.load(DETAIL.open(encoding="utf-8"))
    cases = defaultdict(list)

    for r in rows:
        rid, q = r["id"], r["question"]
        ans = (r.get("system_answer") or "").replace("\n", " ")[:90]
        if r["type"] in ("knowledge", "reject"):
            if r["type"] == "knowledge":
                if r.get("refused"):
                    cases["知识题误拒"].append(
                        (rid, q, r.get("mode"), f"误拒：{ans}", r.get("gated")))
                elif r.get("hit@1") is False and r["mode"] == "hybrid":
                    got = "、".join((r.get("retrieved_docs") or [])[:3])
                    cases["检索未命中"].append(
                        (rid, q, r["mode"], f"检索到: {got}", False))
                elif r.get("judged_correct") is False:
                    cases["生成质量（答非所问/要点缺失）"].append(
                        (rid, q, r["mode"], f"检索命中但判否。答: {ans}", False))
            else:  # reject
                if not r.get("refused"):
                    cases["拒答题漏拒"].append(
                        (rid, q, r["mode"], f"应拒未拒。答: {ans}", False))
        else:  # task / mixed（agent 链路）
            if r.get("judged_correct") is False:
                tools = "、".join(r.get("tools") or []) or "未调工具"
                cases["Agent工具/综合失败"].append(
                    (rid, q, r.get("route"), f"工具: {tools}。答: {ans}", False))

    total_fail = sum(len(v) for v in cases.values())
    lines = [
        "# FitPilot Badcase 分析报告",
        "",
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}",
        f"- 数据源：data/eval/last_run.json（全量评测逐题明细）",
        f"- 失败样本总数：{total_fail}",
        "",
        "## 失败分布",
        "",
        "| 归因类别 | 数量 | 占评测集比例 |", "|---|---|---|",
    ]
    n_all = len({r["id"] for r in rows})
    for cat, items in sorted(cases.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"| {cat} | {len(items)} | {len(items)/n_all*100:.1f}% |")

    lines += ["", "## 案例明细", ""]
    for cat, items in sorted(cases.items(), key=lambda kv: -len(kv[1])):
        lines += [f"### {cat}（{len(items)} 例）", "", FIX_HINTS.get(cat, ""), ""]
        for rid, q, mode, note, gated in items[:20]:
            g = "【闸门拦截】" if gated else ""
            lines.append(f"- **{rid}** [{mode}] {q}")
            lines.append(f"  - {g}{note}")
        lines.append("")

    lines += [
        "---", "",
        "## 说明",
        "",
        "- 检索未命中只统计 hybrid 模式（最终上线路径）",
        "- 『检索命中但判否』与『裁判误判』的边界由人工复核补充（抽样 5 例即可）",
        "- 修复后重跑 scripts/run_eval.py 更新本报告，形成 发现→归因→修复→复测 闭环",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"失败分布: { {k: len(v) for k, v in cases.items()} }")
    print(f"报告已写入 {OUT}")


if __name__ == "__main__":
    main()
