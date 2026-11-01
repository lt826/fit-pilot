"""生成 LoRA SFT 训练集（sharegpt 格式，LLaMA-Factory 直接可用）。

数据策略：每个知识库 chunk 用 glm-4-flash 生成 4 个问法变体的一问一答样本
（直接改写 / 口语化 / 场景化 / 追问式），教微调模型把领域知识内化成
教练风格回答——这是同基座三组对比（直接答 / LoRA / LoRA+RAG）中
LoRA 组的训练数据，与 RAG 组共用同一份知识源，保证对比公平。

断点续跑：逐 chunk 落盘 checkpoint，重跑自动跳过已完成 chunk
（评测脚本踩过的坑：批量任务不落盘 = 一次中断全部重付）。
用法：python scripts/gen_sft_data.py [--test 3] [--workers 8]
"""

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.llm import chat_stream
from app.rag.chunker import load_corpus

OUT_DIR = PROJECT_ROOT / "data" / "sft"
CHECKPOINT = OUT_DIR / "_sft_checkpoint.jsonl"
OUTPUT = OUT_DIR / "fitpilot_sft.jsonl"

_PROMPT = """你是健身知识问答数据标注员。下面给你一个健身知识条目，基于它生成 4 个"一问一答"训练样本。

要求：
1. 六种问法各不相同：①换个说法直接问 ②口语化打字风格（像真人在聊天框里随便问问）③带个人场景的问法（例如"我每天加班只能晚上练，……"）④追问细节式 ⑤误区辨析式（"听说XX是真的吗？"）⑥二选一对比式（"A和B哪个更适合我？"）
2. 答案严格基于给定内容，可重新组织语言、可分点，但禁止编造内容之外的事实或数字
3. 答案用专业又亲切的健身教练口吻，50~200 字
4. 答案里禁止出现"资料""上文""根据给定内容"这类字眼
5. 只输出 JSON 数组，格式 [{{"q":"...","a":"..."}},...]，不要输出其他任何内容

【知识条目】
类别：{category}
{content}"""

# 答案里带这些词说明模型在"引用资料"而不是在"当教练"，这类样本教会模型说媒婆话
_META_WORDS = ("资料", "上文", "给定内容", "条目", "知识库")


def parse_pairs(raw: str) -> list[dict]:
    """从模型输出里抢救 JSON 数组：先整体解析，失败则逐个抽 {...}。"""
    raw = raw.strip()
    if "```" in raw:  # 剥掉 markdown 代码围栏
        raw = re.sub(r"```(?:json)?|```", "", raw)
    start, end = raw.find("["), raw.rfind("]")
    if start != -1 and end > start:
        try:
            data = json.loads(raw[start : end + 1])
            if isinstance(data, list):
                return [p for p in data if isinstance(p, dict) and "q" in p and "a" in p]
        except json.JSONDecodeError:
            pass
    fallback = []
    for s in re.findall(r"\{[^{}]+\}", raw):
        try:
            obj = json.loads(s)
            if isinstance(obj, dict) and "q" in obj and "a" in obj:
                fallback.append(obj)
        except json.JSONDecodeError:
            continue
    return fallback


def gen_for_chunk(chunk, temperature: float = 0.7) -> list[dict]:
    prompt = _PROMPT.format(category=chunk.category, content=chunk.text)
    for attempt in range(3):
        raw = chat_stream(
            [{"role": "user", "content": prompt}], temperature=temperature,
        )
        pairs = parse_pairs(raw)
        if pairs:
            return pairs
    return []


def valid(pair: dict) -> bool:
    q, a = str(pair.get("q", "")), str(pair.get("a", ""))
    return 5 <= len(q) <= 80 and 40 <= len(a) <= 400 and not any(w in a for w in _META_WORDS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", type=int, default=0, help="只跑前 N 个 chunk 验证质量")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    chunks = load_corpus()
    if args.test:
        chunks = chunks[: args.test]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done = set()
    if CHECKPOINT.exists():
        for line in CHECKPOINT.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["chunk_id"])
    todo = [c for c in chunks if c.chunk_id not in done]
    print(f"chunk 总数 {len(chunks)}，已完成 {len(done)}，待生成 {len(todo)}")

    ckpt = CHECKPOINT.open("a", encoding="utf-8")
    ok = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(gen_for_chunk, c): c for c in todo}
        for fut in as_completed(futs):
            c = futs[fut]
            try:
                pairs = [p for p in fut.result() if valid(p)]
            except Exception as e:  # noqa: BLE001 —— 单 chunk 失败不炸全局
                print(f"  ✗ {c.source}: {e}")
                pairs = []
            if pairs:
                ckpt.write(json.dumps({"chunk_id": c.chunk_id, "source": c.source,
                                       "category": c.category, "pairs": pairs},
                                      ensure_ascii=False) + "\n")
                ckpt.flush()
                ok += 1
            else:
                fail += 1
            print(f"  [{ok + fail}/{len(todo)}] {c.source} → {len(pairs)} 条")

    ckpt.close()

    # ---- 汇总：checkpoint → 去重 → 最终训练集 ----
    seen, samples = set(), []
    for line in CHECKPOINT.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        for p in rec["pairs"]:
            key = re.sub(r"\s+", "", p["q"])
            if key in seen:
                continue
            seen.add(key)
            samples.append({"conversations": [
                {"from": "human", "value": p["q"]},
                {"from": "gpt", "value": p["a"]},
            ], "source": rec["source"]})

    OUTPUT.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in samples),
                      encoding="utf-8")
    # LLaMA-Factory 数据集注册片段，拷到服务器 dataset_info.json 里即用
    (OUT_DIR / "dataset_info.json").write_text(json.dumps({
        "fitpilot_sft": {
            "file_name": "fitpilot_sft.jsonl",
            "formatting": "sharegpt",
            "columns": {"messages": "conversations"},
        }
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n完成：chunk 成功 {ok} 失败 {fail}；去重后样本 {len(samples)} 条")
    print(f"训练集 → {OUTPUT}")
    print(f"注册片段 → {OUT_DIR / 'dataset_info.json'}")


if __name__ == "__main__":
    main()
