"""第7步④：同基座三组对比评测（底座 Qwen2.5-3B-Instruct，vLLM 服务）。

A组 base     ：基座直接答（同款人设提示词，无检索）
B组 lora     ：LoRA 适配器直接答
C组 lora_rag ：FitPilot RAG 管线 + LoRA 生成（检索增强）

评测口径：
- knowledge 题：智谱强裁判（glm-4.7，与被测模型分通道）二元判定正确性
- reject 题：以"【无法回答】"结构化标记判定拒答（确定性，不经裁判），
  考察"知道自己不知道"——A/B 组无检索兜底，幻觉抑制全靠模型自身

三组各自独立进程运行（避免 CHAT_BASE_URL 环境切换互相污染），
共用断点文件按 (id, group) 续跑；全部跑完 --report 汇总出报告。

用法：
  python scripts/eval_finetune.py --group base
  python scripts/eval_finetune.py --group lora
  CHAT_BASE_URL=http://127.0.0.1:18800/v1 CHAT_API_KEY=local \\
  CHAT_MODEL=fitpilot-lora python scripts/eval_finetune.py --group lora_rag
  CHAT_BASE_URL=... CHAT_MODEL=qwen-base python scripts/eval_finetune.py --group base_rag
  python scripts/eval_finetune.py --report
"""

import argparse
import csv
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import OpenAI  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_CSV = PROJECT_ROOT / "data" / "eval" / "eval_set.csv"
REPORT_MD = PROJECT_ROOT / "docs" / "ft-compare-report.md"
CHECKPOINT = PROJECT_ROOT / "data" / "eval" / "_ft_checkpoint.jsonl"

COL_ID = "id(编号)"
COL_Q = "question(问题)"
COL_REF = "reference_answer(参考答案)"
COL_TYPE = "type(题型)"

GROUPS = {"base": "Qwen2.5-3B 基座直接答", "lora": "LoRA 微调后直接答",
          "base_rag": "Qwen2.5-3B 基座 + RAG", "lora_rag": "LoRA + RAG 检索增强"}

# A/B 组人设：与 RAG 生成器同源的教练口吻 + 同款结构化拒答标记，
# 保证三组"会不会拒答"的口径一致，A/B 不因提示词劣势被冤枉
DIRECT_PROMPT = """你是健身知识助手 FitPilot。用专业又亲切的教练口吻回答健身问题，
答案简洁、可分点，保留具体数字。
如果问题超出健身知识范围（医疗诊断、与健身无关等）或你没有把握，
回复必须以"【无法回答】"开头并说明原因，不要猜测或编造。"""

VLLM_BASE = os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:18800/v1")


def make_vllm_client() -> OpenAI:
    return OpenAI(api_key="local", base_url=VLLM_BASE)


def make_judge_client() -> OpenAI:
    """裁判固定走智谱主通道：与被测通道（可能已切到 vLLM）物理隔离。"""
    from app.core.config import get_settings
    s = get_settings()
    return OpenAI(api_key=s.zhipu_api_key, base_url=s.zhipu_base_url)


def direct_answer(client: OpenAI, model: str, question: str) -> str:
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model, temperature=0.3,
                messages=[{"role": "system", "content": DIRECT_PROMPT},
                          {"role": "user", "content": question}],
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception:  # noqa: BLE001 —— vLLM 偶发超时/队满，指数退避重试
            import time
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    return ""


def judge(judge_client: OpenAI, question: str, reference: str, answer: str) -> bool:
    from app.core.config import get_settings
    s = get_settings()
    prompt = f"""你是评测员。判断【模型回答】是否正确覆盖了【参考答案】的关键事实要点。
只输出"是"或"否"两个字。允许表述和顺序差异，但出现事实错误或关键要点缺失判"否"。

【问题】{question}
【参考答案】{reference}
【模型回答】{answer}"""
    for model in (s.judge_model, s.chat_model):
        for extra in ({"thinking": {"type": "disabled"}}, None):
            try:
                kwargs = dict(model=model, temperature=0,
                              messages=[{"role": "user", "content": prompt}])
                if extra:
                    kwargs["extra_body"] = extra
                resp = judge_client.chat.completions.create(**kwargs)
                return (resp.choices[0].message.content or "").strip().startswith("是")
            except Exception as exc:  # noqa: BLE001
                # 账号级致命错误（余额耗尽/资源包用尽）降级也没用，继续判只会
                # 全批静默 False 污染整组结果——必须立刻炸出来（实测教训：
                # 192 题被无声判 False，靠抽查明细才发现）
                if "RateLimitError" in type(exc).__name__ and (
                        "余额" in str(exc) or "资源包" in str(exc)):
                    raise RuntimeError(f"裁判通道致命错误: {exc}") from exc
                continue
    return False


class Checkpointer:
    """逐题落盘断点，按 (id, group) 续跑（沿用全量评测的工程约定）。"""

    def __init__(self) -> None:
        self.details: list[dict] = []
        self.done: set[tuple] = set()
        if CHECKPOINT.exists():
            for line in CHECKPOINT.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    d = json.loads(line)
                    self.details.append(d)
                    self.done.add((d["id"], d["group"]))
            print(f"断点续跑：已有 {len(self.done)} 条结果")
        self._fh = CHECKPOINT.open("a", encoding="utf-8")
        self._lock = threading.Lock()

    def add(self, detail: dict) -> None:
        with self._lock:
            self.details.append(detail)
            self.done.add((detail["id"], detail["group"]))
            self._fh.write(json.dumps(detail, ensure_ascii=False) + "\n")
            self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def load_rows() -> list[dict]:
    with EVAL_CSV.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r[COL_TYPE] in ("knowledge", "reject")]


def run_group(group: str, workers: int) -> None:
    rows = load_rows()
    jc = make_judge_client()
    ck = Checkpointer()
    vc = make_vllm_client() if group in ("base", "lora") else None
    model = {"base": "qwen-base", "lora": "fitpilot-lora"}.get(group)

    pipe = None
    if group in ("lora_rag", "base_rag"):
        # 组件健康预检：RAG 组的实验条件包含"向量检索可用"——静默降级到 BM25 会
        # 让闸门失效、改变实验条件，814 题白跑的实测教训（降级对生产是韧性、对评测是污染）
        from app.rag.retriever import HybridRetriever
        probe = HybridRetriever().retrieve("__健康探测__", k=1, mode="hybrid")
        if not probe or probe[0].vector_score is None:
            sys.exit("[中止] 向量检索当前处于降级状态(Qdrant/embedding 异常)，"
                     "RAG 组不满足实验条件——请先恢复组件后重跑")
        from app.rag.pipeline import RAGPipeline
        pipe = RAGPipeline()

    todo = [r for r in rows if (r[COL_ID], group) not in ck.done]
    print(f"[{group}] 共 {len(rows)} 题，待跑 {len(todo)}")

    def work(row: dict) -> dict:
        q, typ = row[COL_Q], row[COL_TYPE]
        base_detail = {"id": row[COL_ID], "group": group, "type": typ, "question": q}
        try:
            if group in ("lora_rag", "base_rag"):
                ans = pipe.answer(q, k=5, mode="hybrid")
                answer, refused = ans.answer, ans.refused
            else:
                answer = direct_answer(vc, model, q)
                refused = answer.startswith("【无法回答】")
            judged = None
            if typ == "knowledge" and not refused:
                judged = judge(jc, q, row[COL_REF], answer)
            return {**base_detail, "refused": refused, "judged_correct": judged,
                    "system_answer": answer[:300]}
        except Exception as exc:  # noqa: BLE001 —— 单题失败记录后继续
            return {**base_detail, "error": f"{exc.__class__.__name__}: {exc}"}

    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(work, r) for r in todo]
            for n, fut in enumerate(as_completed(futs), 1):
                ck.add(fut.result())
                if n % 25 == 0:
                    print(f"  [{group}] {n}/{len(todo)} ...")
    finally:
        ck.close()
    summarize(ck.details, [group])
    print(f"[{group}] 完成。记得最后跑 --report 汇总。")


def summarize(details: list[dict], groups: list[str]) -> dict[str, dict]:
    out = {}
    for g in groups:
        rows = [d for d in details if d["group"] == g and "error" not in d]
        k = [d for d in rows if d["type"] == "knowledge"]
        rj = [d for d in rows if d["type"] == "reject"]
        kj = [d for d in k if d.get("judged_correct") is not None]
        def rate(a, b):
            return a / b if b else None
        out[g] = {
            "knowledge_n": len(k), "reject_n": len(rj),
            "answer_acc": rate(sum(bool(d["judged_correct"]) for d in kj), len(kj)),
            "reject_refusal": rate(sum(bool(d["refused"]) for d in rj), len(rj)),
            "false_refusal": rate(sum(bool(d["refused"]) for d in k), len(k)),
        }
    return out


def write_report(details: list[dict]) -> None:
    from app.core.config import get_settings
    s = get_settings()
    stats = summarize(details, list(GROUPS))
    from datetime import datetime

    def pct(x):
        return f"{x * 100:.1f}%" if x is not None else "-"

    lines = [
        "# 微调三组对比报告（第7步④：LoRA 实验）",
        "",
        f"- 日期：{datetime.now():%Y-%m-%d %H:%M}",
        "- 底座：Qwen2.5-3B-Instruct（同一底座，唯一变量是 LoRA 与检索增强）",
        "- LoRA：rank 16 / alpha 32 / target all / 3 epochs，训练数据为知识库蒸馏 SFT 集",
        "- 服务：vLLM 单进程双模型名（qwen-base / fitpilot-lora），推理参数完全一致",
        f"- 裁判：{s.judge_model}（智谱主通道，与被测模型分通道）",
        "- 拒答判定：结构化标记【无法回答】（确定性，不经裁判）",
        "",
        "| 组别 | 知识题正确率 | 拒答题拒答率 | 知识题误拒率 |",
        "|---|---|---|---|",
    ]
    for g, label in GROUPS.items():
        st = stats[g]
        lines.append(f"| {label} | {pct(st['answer_acc'])} | {pct(st['reject_refusal'])} "
                     f"| {pct(st['false_refusal'])} |")
    lines += [
        "",
        "解读要点：",
        "- A→B 差值 = LoRA 知识内化的收益（无检索时的领域知识+口吻）",
        "- B→C 差值 = 检索增强在微调之上的增量（知识新鲜度+可溯源）",
        "- 拒答题三组对比 = 幻觉抑制来源分析（A 靠通用对齐，B 靠领域边界，C 靠闸门）",
        "",
        f"逐题明细：data/eval/_ft_checkpoint.jsonl",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告已写入 {REPORT_MD}")
    for g, label in GROUPS.items():
        st = stats[g]
        print(f"{label:<14} 正确率={pct(st['answer_acc'])} 拒答={pct(st['reject_refusal'])} "
              f"误拒={pct(st['false_refusal'])}")


def rejudge(group: str) -> None:
    """原位重判某组：保留已生成的答案，仅重新走裁判。

    用于裁判通道故障（如余额耗尽导致整批误判 False）后的修复——
    答案不重新生成，避免温度采样的不可复现性引入新变量。
    注意：判卷基于断点里截断到 300 字的答案存档，LoRA 组答案短，无损。
    """
    details = [json.loads(l) for l in
               CHECKPOINT.read_text(encoding="utf-8").splitlines() if l.strip()]
    jc = make_judge_client()
    with EVAL_CSV.open(encoding="utf-8-sig") as f:
        refs = {r[COL_ID]: r[COL_REF] for r in csv.DictReader(f)}
    rows = [d for d in details if d["group"] == group and d["type"] == "knowledge"
            and not d.get("refused") and "error" not in d]
    print(f"[{group}] 重判 {len(rows)} 题的裁判结果")
    for n, d in enumerate(rows, 1):
        d["judged_correct"] = judge(jc, d["question"], refs[d["id"]], d["system_answer"])
        if n % 25 == 0:
            print(f"  {n}/{len(rows)} ...")
    CHECKPOINT.write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in details) + "\n",
        encoding="utf-8")
    print("断点已原位更新，跑 --report 汇总")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", choices=list(GROUPS))
    ap.add_argument("--report", action="store_true", help="汇总已完成的组并出报告")
    ap.add_argument("--rejudge", metavar="GROUP", choices=list(GROUPS),
                    help="原位重判该组（答案保留，只重走裁判）")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    if args.report:
        details = [json.loads(l) for l in
                   CHECKPOINT.read_text(encoding="utf-8").splitlines() if l.strip()]
        write_report(details)
        return
    if args.rejudge:
        rejudge(args.rejudge)
        return
    if not args.group:
        ap.error("需要 --group / --rejudge / --report 之一")
    run_group(args.group, args.workers)


if __name__ == "__main__":
    main()
