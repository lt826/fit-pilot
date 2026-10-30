"""第7步全量评测：三路检索对比 + 任务/混合题(Agent链路) + 强裁判模型。

与第2步评测的差异：
- 检索对比扩为三路：vector / bm25 / hybrid
- task/mixed 题纳入：走完整 FitnessCoach 链路，在临时数据库副本上执行
- 裁判换 judge_model（glm-4.7，失败降级回 chat_model），消除同源偏差
- 出处命中支持多可接受文档列 acceptable_docs（e014 口径修正）

工程韧性（首轮全量评测被一次 API 网络错误整体炸掉后补齐）：
- 逐题断点落盘 data/eval/_checkpoint.jsonl，崩溃/中断后重跑自动续传
- 单题异常记录后继续，不中断全局；全部完成后才写正式产物并清除断点

输出：控制台汇总 + docs/eval-report.md + data/eval/last_run.json（逐题明细）
"""

import csv
import json
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.llm import get_llm_client  # noqa: E402
from app.rag.pipeline import RAGPipeline  # noqa: E402

import app.db.database as db_mod  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_CSV = PROJECT_ROOT / "data" / "eval" / "eval_set.csv"
REPORT_MD = PROJECT_ROOT / "docs" / "eval-report.md"
DETAIL_JSON = PROJECT_ROOT / "data" / "eval" / "last_run.json"
CHECKPOINT = PROJECT_ROOT / "data" / "eval" / "_checkpoint.jsonl"

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
    """强模型二元判定，带重试与降级（judge_model → chat_model）。

    思考型裁判（glm-4.7）关思考：判卷只需二元结论，思考 9 秒纯属浪费；
    关掉后 ~4s。extra_body 不被支持时自动去掉重试。
    """
    prompt = f"""你是评测员。判断【模型回答】是否正确覆盖了【参考答案】的关键事实要点。
只输出"是"或"否"两个字。允许表述和顺序差异，但出现事实错误或关键要点缺失判"否"。

【问题】{question}
【参考答案】{reference}
【模型回答】{answer}"""
    client = get_llm_client()
    for model in (get_settings().judge_model, get_settings().chat_model):
        for extra in ({"thinking": {"type": "disabled"}}, None):
            try:
                kwargs = dict(model=model, temperature=0,
                              messages=[{"role": "user", "content": prompt}])
                if extra:
                    kwargs["extra_body"] = extra
                resp = client.chat.completions.create(**kwargs)
                return (resp.choices[0].message.content or "").strip().startswith("是")
            except Exception:  # noqa: BLE001 —— 参数不支持则去掉重试，失败则降级模型
                continue
    return False


class Checkpointer:
    """逐题落盘断点：崩溃后重跑按 (id, mode) 跳过已完成的题。"""

    def __init__(self) -> None:
        self.details: list[dict] = []
        self.done: set[tuple] = set()
        if CHECKPOINT.exists():
            with CHECKPOINT.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    self.details.append(d)
                    self.done.add((d["id"], d["mode"]))
            print(f"断点续跑：已有 {len(self.done)} 条结果")
        self._fh = CHECKPOINT.open("a", encoding="utf-8")
        self._lock = threading.Lock()  # 并发评测下多线程同时落盘

    def add(self, detail: dict) -> None:
        with self._lock:
            self.details.append(detail)
            self.done.add((detail["id"], detail["mode"]))
            self._fh.write(json.dumps(detail, ensure_ascii=False) + "\n")
            self._fh.flush()

    def close(self) -> None:
        self._fh.close()

    def clear(self) -> None:
        self._fh.close()
        CHECKPOINT.unlink(missing_ok=True)


def run_retrieval_mode(mode: str, rows: list[dict], pipe: RAGPipeline,
                       ck: Checkpointer, workers: int | None = None) -> dict:
    """检索类题目并发执行：裁判与生成都偏 IO，多线程提吞吐。

    检索组件线程安全：Qdrant 客户端与 BM25 只读、jieba 分词无状态。
    并发度经 EVAL_WORKERS 环境变量调整：默认 4；跑 hybrid 时建议 2——
    embedding 免费档限流紧，并发过高会触发"降级到BM25"污染该组结果（实测教训）。
    """
    if workers is None:
        workers = int(os.environ.get("EVAL_WORKERS", "4"))
    todo = [r for r in rows if (r[COL_ID], mode) not in ck.done]
    done_before = len(rows) - len(todo)
    if done_before:
        print(f"  [{mode}] 断点续跑跳过 {done_before} 题")

    def work(row: dict) -> dict:
        q, typ = row[COL_Q], row[COL_TYPE]
        try:
            results = pipe.retriever.retrieve(q, k=5, mode=mode)
            doc_paths = [r.chunk.doc_path for r in results]
            accept = [d for d in (row.get(COL_ACC) or row[COL_SRC]).split(";") if d]

            r_hit1 = r_hit5 = None
            if typ == "knowledge":
                r_hit1 = doc_paths[0] in accept if doc_paths else False
                r_hit5 = bool(set(accept) & set(doc_paths))

            ans = pipe.answer(q, k=5, mode=mode, results=results)

            judged = None
            if typ == "knowledge" and not ans.refused:
                judged = judge(q, row[COL_REF], ans.answer)

            return {"id": row[COL_ID], "mode": mode, "type": typ, "question": q,
                    "hit@1": r_hit1, "hit@5": r_hit5, "refused": ans.refused,
                    "gated": ans.gated, "judged_correct": judged,
                    "system_answer": ans.answer[:200],
                    "expected_docs": accept, "retrieved_docs": doc_paths}
        except Exception as exc:  # noqa: BLE001 —— 单题失败记录后继续
            return {"id": row[COL_ID], "mode": mode, "type": typ, "question": q,
                    "hit@1": None, "hit@5": None, "refused": None,
                    "error": f"{exc.__class__.__name__}: {exc}"}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(work, r) for r in todo]
        for n, fut in enumerate(as_completed(futures), 1):
            ck.add(fut.result())
            if n % 25 == 0:
                print(f"  [{mode}] {done_before + n}/{len(rows)} ...")

    # 指标从明细推导（而非运行时计数），断点续跑后依然正确
    rows_m = [d for d in ck.details if d["mode"] == mode and "error" not in d]
    k_rows = [d for d in rows_m if d["type"] == "knowledge"]
    r_rows = [d for d in rows_m if d["type"] == "reject"]
    judged_rows = [d for d in k_rows if d.get("judged_correct") is not None]

    def rate(num, den):
        return num / den if den else None

    return {"mode": mode, "knowledge_n": len(k_rows), "reject_n": len(r_rows),
            "hit@1": rate(sum(bool(d["hit@1"]) for d in k_rows), len(k_rows)),
            "hit@5": rate(sum(bool(d["hit@5"]) for d in k_rows), len(k_rows)),
            "reject_refusal": rate(sum(bool(d["refused"]) for d in r_rows), len(r_rows)),
            "false_refusal": rate(sum(bool(d["refused"]) for d in k_rows), len(k_rows)),
            "answer_acc": rate(sum(bool(d["judged_correct"]) for d in judged_rows),
                               len(judged_rows))}


def run_agent_rows(rows: list[dict], ck: Checkpointer) -> dict:
    from app.agent.graph import FitnessCoach

    orig_db = db_mod.DB_PATH
    tmp_db = orig_db.with_name("_eval_tmp.db")
    shutil.copy(orig_db, tmp_db)
    db_mod.DB_PATH = tmp_db
    try:
        for row in rows:
            if (row[COL_ID], "agent") in ck.done:
                continue
            q, typ = row[COL_Q], row[COL_TYPE]
            try:
                coach = FitnessCoach()  # 独立会话，避免评测题之间上下文串扰
                r = coach.chat(q)
                judged = judge(q, row[COL_REF], r.answer)
                ck.add({"id": row[COL_ID], "mode": "agent", "type": typ,
                        "question": q, "route": r.route, "hit@1": None,
                        "refused": False, "judged_correct": judged,
                        "tools": [t["tool"] for t in r.tool_trace],
                        "system_answer": r.answer[:200]})
            except Exception as exc:  # noqa: BLE001
                ck.add({"id": row[COL_ID], "mode": "agent", "type": typ,
                        "question": q, "refused": None,
                        "error": f"{exc.__class__.__name__}: {exc}"})
            done_n = sum(1 for d in ck.details if d["mode"] == "agent")
            print(f"  [agent] {done_n}/{len(rows)} ...")

        per_type: dict[str, dict] = {}
        for d in ck.details:
            if d["mode"] == "agent" and "error" not in d:
                agg = per_type.setdefault(d["type"], {"n": 0, "ok": 0})
                agg["n"] += 1
                agg["ok"] += bool(d.get("judged_correct"))
        return per_type
    finally:
        db_mod.DB_PATH = orig_db
        # Windows 下 SQLite 连接要等 GC 才释放文件句柄，直接删必 PermissionError
        # （首轮全量评测因此崩在收尾、结果全丢）。先回收连接再删，失败重试。
        import gc
        gc.collect()
        for attempt in range(3):
            try:
                tmp_db.unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(1 + attempt)


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

    ck = Checkpointer()
    try:
        pipe = RAGPipeline()
        stats = [run_retrieval_mode(m, retrieval_rows, pipe, ck) for m in MODES]
        agent_stats = run_agent_rows(agent_rows, ck)
    finally:
        ck.close()

    DETAIL_JSON.write_text(json.dumps(ck.details, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    ck.clear()  # 全部完成，清除断点（下次评测从零开始）

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
