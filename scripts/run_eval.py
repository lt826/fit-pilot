"""第7步全量评测：三路检索对比 + 任务/混合题(Agent链路) + 强裁判模型。

与第2步评测的差异：
- 检索对比扩为三路：vector / bm25 / hybrid
- task/mixed 题纳入：走完整 FitnessCoach 链路，在临时数据库副本上执行
  （写入类操作不污染真实训练数据）
- 裁判换 judge_model（glm-4.7，失败降级回 chat_model），消除同源偏差
- 出处命中支持多可接受文档列 acceptable_docs（e014 口径修正）

输出：控制台汇总 + docs/eval-report.md + data/eval/last_run.json（逐题明细）
"""

import csv
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.llm import get_llm_client  # noqa: E402
from app.rag.pipeline import RAGPipeline  # noqa: E402
from app.rag.retriever import HybridRetriever  # noqa: E402

import app.db.database as db_mod  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_CSV = PROJECT_ROOT / "data" / "eval" / "eval_set.csv"
REPORT_MD = PROJECT_ROOT / "docs" / "eval-report.md"
DETAIL_JSON = PROJECT_ROOT / "data" / "eval" / "last_run.json"

COL_ID = "id(编号)"
COL_Q = "question(问题)"
COL_REF = "reference_answer(参考答案)"
COL_SRC = "source_doc(来源文档)"
COL_TYPE = "type(题型)"
COL_ACC = "acceptable_docs(可接受出处)"

MODES = ["vector", "bm25", "hybrid"]


def load_eval() -> list[dict]:
    with EVAL_CSV.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    valid = {"knowledge", "task", "mixed", "reject"}
    bad = [r.get(COL_ID, "?") for r in rows if (None in r) or (r.get(COL_TYPE) not in valid)]
    if bad:
        sys.exit(f"评测集字段异常: {bad}")
    return rows


def judge(question: str, reference: str, answer: str) -> bool:
    """强模型二元判定，judge_model 失败自动降级回生成模型。"""
    prompt = f"""你是评测员。判断【模型回答】是否正确覆盖了【参考答案】的关键事实要点。
只输出"是"或"否"两个字。允许表述和顺序差异，但出现事实错误或关键要点缺失判"否"。

【问题】{question}
【参考答案】{reference}
【模型回答】{answer}"""
    client = get_llm_client()
    for model in (get_settings().judge_model, get_settings().chat_model):
        try:
            resp = client.chat.completions.create(
                model=model, temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            return (resp.choices[0].message.content or "").strip().startswith("是")
        except Exception:  # noqa: BLE001 —— 裁判模型不可用则降级
            continue
    return False


def run_retrieval_mode(mode: str, rows: list[dict], pipe: RAGPipeline,
                       details: list) -> dict:
    n_k = n_r = hit1 = hit5 = 0
    reject_refused = false_refusal = 0
    judged_total = judged_ok = 0

    for i, row in enumerate(rows, 1):
        q, typ = row[COL_Q], row[COL_TYPE]
        results = pipe.retriever.retrieve(q, k=5, mode=mode)
        doc_paths = [r.chunk.doc_path for r in results]
        # 多可接受出处：任一命中即算（无该列则退回单出处）
        accept = [d for d in (row.get(COL_ACC) or row[COL_SRC]).split(";") if d]

        r_hit1 = r_hit5 = None
        if typ == "knowledge":
            r_hit1 = doc_paths[0] in accept if doc_paths else False
            r_hit5 = bool(set(accept) & set(doc_paths))

        ans = pipe.answer(q, k=5, mode=mode, results=results)

        judged = None
        if typ == "knowledge":
            n_k += 1
            hit1 += bool(r_hit1)
            hit5 += bool(r_hit5)
            if ans.refused:
                false_refusal += 1
            else:
                judged = judge(q, row[COL_REF], ans.answer)
                judged_total += 1
                judged_ok += judged
        else:
            n_r += 1
            reject_refused += ans.refused

        details.append({"id": row[COL_ID], "mode": mode, "type": typ, "question": q,
                        "hit@1": r_hit1, "hit@5": r_hit5, "refused": ans.refused,
                        "gated": ans.gated, "judged_correct": judged,
                        "system_answer": ans.answer[:200],
                        "expected_docs": accept, "retrieved_docs": doc_paths})
        if i % 25 == 0:
            print(f"  [{mode}] {i}/{len(rows)} ...")

    return {"mode": mode, "knowledge_n": n_k, "reject_n": n_r,
            "hit@1": hit1 / n_k, "hit@5": hit5 / n_k,
            "reject_refusal": reject_refused / n_r,
            "false_refusal": false_refusal / n_k,
            "answer_acc": judged_ok / judged_total if judged_total else None}


def run_agent_rows(rows: list[dict], details: list) -> dict:
    """task/mixed 走完整 Agent 链路；临时库副本执行，记录类操作不污染真实数据。"""
    from app.agent.graph import FitnessCoach

    orig_db = db_mod.DB_PATH
    tmp_db = orig_db.with_name("_eval_tmp.db")
    shutil.copy(orig_db, tmp_db)
    db_mod.DB_PATH = tmp_db
    try:
        per_type: dict[str, dict] = {}
        for i, row in enumerate(rows, 1):
            q, typ = row[COL_Q], row[COL_TYPE]
            coach = FitnessCoach()  # 独立会话，避免评测题之间上下文串扰
            r = coach.chat(q)
            judged = judge(q, row[COL_REF], r.answer)
            agg = per_type.setdefault(typ, {"n": 0, "ok": 0})
            agg["n"] += 1
            agg["ok"] += judged
            details.append({"id": row[COL_ID], "mode": "agent", "type": typ,
                            "question": q, "route": r.route, "hit@1": None,
                            "refused": False, "judged_correct": judged,
                            "tools": [t["tool"] for t in r.tool_trace],
                            "system_answer": r.answer[:200]})
            if i % 5 == 0:
                print(f"  [agent] {i}/{len(rows)} ...")
        return per_type
    finally:
        db_mod.DB_PATH = orig_db
        tmp_db.unlink(missing_ok=True)


def fmt_pct(x) -> str:
    return f"{x * 100:.1f}%" if x is not None else "-"


def write_report(stats: list[dict], agent_stats: dict, elapsed: float) -> None:
    s = get_settings()
    lines = [
        "# FitPilot 评测报告（第 7 步：全量评测）",
        "",
        f"- 日期：{datetime.now():%Y-%m-%d %H:%M}",
        f"- 生成模型：{s.chat_model} / 裁判模型：{s.judge_model}（失败降级 {s.chat_model}）",
        f"- 评测集：knowledge {stats[0]['knowledge_n']} + reject {stats[0]['reject_n']}"
        f" + task/mixed {sum(v['n'] for v in agent_stats.values())} 条",
        f"- 闸门阈值：top1 向量分 < {s.rag_refuse_threshold} 直接拒答",
        f"- 总耗时：{elapsed / 60:.1f} 分钟；逐题明细见 data/eval/last_run.json",
        "",
        "## 检索策略对比（知识/拒答题）",
        "",
        "| 指标 | " + " | ".join(x["mode"] for x in stats) + " |",
        "|---|" + "---|" * len(stats),
    ]
    for label, key in [("Hit@1（可接受出处排第1）", "hit@1"), ("Hit@5", "hit@5"),
                       ("拒答召回", "reject_refusal"), ("知识题误拒率", "false_refusal"),
                       ("答案正确率（裁判判定）", "answer_acc")]:
        lines.append(f"| {label} | " + " | ".join(fmt_pct(x[key]) for x in stats) + " |")

    lines += ["", "## Agent 链路（task / mixed 题）", "",
              "| 题型 | 题数 | 正确率 |", "|---|---|---|"]
    for typ, agg in sorted(agent_stats.items()):
        lines.append(f"| {typ} | {agg['n']} | {fmt_pct(agg['ok'] / agg['n'])} |")
    lines += [
        "",
        "说明：task/mixed 在临时数据库副本上执行完整 LangGraph 链路（不污染真实训练记录）；",
        "判定由裁判模型对照参考要点二元评判。出处命中支持多可接受文档（e014 口径修订）。",
        "",
        "## 已知局限",
        "",
        "- 知识题中约 160 条由语料章节自动生成（标题即问题），天然偏向『检索词与标题重合』，",
        "  Hit 指标相对真实用户口语提问可能偏乐观；拒答与混合题为手工设计",
        f"- 裁判模型与生成模型同厂商（{s.judge_model} vs {s.chat_model}），同源偏差减弱但未消除",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告已写入 {REPORT_MD}")


def main() -> None:
    t0 = time.time()
    rows = load_eval()
    retrieval_rows = [r for r in rows if r[COL_TYPE] in ("knowledge", "reject")]
    agent_rows = [r for r in rows if r[COL_TYPE] in ("task", "mixed")]
    print(f"评测集：检索类 {len(retrieval_rows)} + Agent类 {len(agent_rows)}")

    pipe = RAGPipeline()
    details: list[dict] = []
    stats = [run_retrieval_mode(m, retrieval_rows, pipe, details) for m in MODES]
    agent_stats = run_agent_rows(agent_rows, details)

    DETAIL_JSON.write_text(json.dumps(details, ensure_ascii=False, indent=1),
                           encoding="utf-8")

    print("\n===== 汇总 =====")
    for x in stats:
        print(f"{x['mode']:<8} hit@1={fmt_pct(x['hit@1'])} hit@5={fmt_pct(x['hit@5'])} "
              f"拒答召回={fmt_pct(x['reject_refusal'])} 误拒={fmt_pct(x['false_refusal'])} "
              f"正确率={fmt_pct(x['answer_acc'])}")
    for typ, agg in sorted(agent_stats.items()):
        print(f"agent/{typ}  {agg['ok']}/{agg['n']} = {fmt_pct(agg['ok'] / agg['n'])}")

    write_report(stats, agent_stats, time.time() - t0)
    print(f"总耗时 {(time.time() - t0) / 60:.1f} 分钟")


if __name__ == "__main__":
    main()
