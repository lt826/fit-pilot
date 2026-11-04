"""评测集 v2 扩容：248 → ~391 题（微调四组重测用）。

扩的是两块短板（不是同质堆量）：
1. 口语化知识变体 +150：从现有 201 题均匀抽样，改写成"真人随手打字"问法，
   参考答案/出处继承原题——测检索与生成对问法变化的鲁棒性
2. 拒答题 +40：明确圈定健身之外的 10 个领域各 4 题——原拒答组仅 20 题，
   拒答率结论的置信区间宽达 ±25 点，是全实验最薄弱处

注意：新拒答题领域刻意避开"医疗/营养/身体"——知识库的 special/nutrition
类目覆盖部分医疗问题，踩进去就不是拒答题而是知识题了。
用法：python scripts/expand_eval_v2.py [--dry]
"""

import argparse
import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.llm import chat_stream

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_CSV = PROJECT_ROOT / "data" / "eval" / "eval_set.csv"

COL_ID = "id(编号)"
COL_Q = "question(问题)"
COL_REF = "reference_answer(参考答案)"
COL_SRC = "source_doc(来源文档)"
COL_TYPE = "type(题型)"
COL_NOTES = "notes(备注)"
COL_ACC = "acceptable_docs(可接受出处)"

N_VARIANTS = 150
N_REJECT_PER_DOMAIN = 4

# 领域刻意选与健身知识库零交集的；标注领域便于事后审查
REJECT_DOMAINS = ["编程与电脑", "数学题", "历史地理", "股票基金理财", "明星娱乐八卦",
                  "游戏攻略", "法律咨询", "汽车保养维修", "签证出国旅游", "宠物饲养"]

_VARIANT_PROMPT = """把下面这个健身问题改写成一个口语化、像真人在聊天框里随手打字的版本。
要求：核心意思必须完全不变；可以加语气词、口语连接词或生活场景（如"我这种每天加班的"），但不要引入新的具体事实（体重/次数等数字）；只输出改写后的问题本身，不要任何解释。

原问题：{q}"""

_REJECT_PROMPT = """生成 {n} 个"{domain}"领域的中文提问，会被发给一个健身知识助手。
要求：必须与健身/训练/饮食营养/身体完全无关（正是要考它会不会拒答）；像真人提问，长短自然，每个问题风格各异；每行一个，不要编号不要解释。"""


def _clean(text: str) -> str:
    # 剥掉模型不听话加的编号前缀（"1. ""2、"）——提示词禁不住的靠代码兜
    text = re.sub(r"^\s*\d+\s*[.、)．]\s*", "", text.strip())
    return re.sub(r"\s+", " ", text)


def gen_variant(row: dict) -> dict | None:
    raw = chat_stream([{"role": "user",
                        "content": _VARIANT_PROMPT.format(q=row[COL_Q])}],
                      temperature=0.8)
    q = _clean(raw.splitlines()[0]) if raw else ""
    # 质量闸：必须像问题、与原题实质不同、长度合理
    if not (6 <= len(q) <= 80) or _clean(row[COL_Q]) == q:
        return None
    return {COL_Q: q, COL_REF: row[COL_REF], COL_SRC: row[COL_SRC],
            COL_ACC: row[COL_ACC], COL_TYPE: "knowledge",
            COL_NOTES: f"v2口语化变体(源{row[COL_ID]})"}


def gen_rejects(domain: str) -> list[str]:
    raw = chat_stream([{"role": "user",
                        "content": _REJECT_PROMPT.format(n=N_REJECT_PER_DOMAIN, domain=domain)}],
                      temperature=0.9)
    qs = [_clean(l) for l in raw.splitlines() if 6 <= len(_clean(l)) <= 60]
    return qs[:N_REJECT_PER_DOMAIN]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只生成不写盘")
    args = ap.parse_args()

    with EVAL_CSV.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    header = list(rows[0].keys())
    existing_q = {_clean(r[COL_Q]) for r in rows}
    print(f"现有 {len(rows)} 题")

    # ---- ① 口语化变体：201 题里等距抽 150 ----
    knowledge = [r for r in rows if r[COL_TYPE] == "knowledge"]
    step = len(knowledge) / N_VARIANTS
    sampled = [knowledge[int(i * step)] for i in range(N_VARIANTS)]

    variants: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(gen_variant, r): r for r in sampled}
        for n, fut in enumerate(as_completed(futs), 1):
            v = fut.result()
            if v and _clean(v[COL_Q]) not in existing_q:
                variants.append(v)
                existing_q.add(_clean(v[COL_Q]))
            if n % 30 == 0:
                print(f"  变体 {n}/{len(sampled)}")

    # ---- ② 拒答题：10 领域 × 4 ----
    rejects: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(gen_rejects, d): d for d in REJECT_DOMAINS}
        for fut in as_completed(futs):
            domain = futs[fut]
            for q in fut.result():
                if q not in existing_q:
                    rejects.append({COL_Q: q, COL_REF: "", COL_SRC: "", COL_ACC: "",
                                    COL_TYPE: "reject", COL_NOTES: f"v2拒答-{domain}"})
                    existing_q.add(q)

    # ---- ③ 编号、合并、写盘 ----
    new_rows = variants + rejects
    start = max(int(r[COL_ID][1:]) for r in rows) + 1
    for i, r in enumerate(new_rows):
        r[COL_ID] = f"e{start + i:03d}"

    print(f"\n生成：口语化变体 {len(variants)} + 拒答题 {len(rejects)} = {len(new_rows)}")
    print("变体样例:")
    for r in variants[:5]:
        print(f"  {r[COL_Q]}")
    print("拒答题样例:")
    for r in rejects[:6]:
        print(f"  [{r[COL_NOTES]}] {r[COL_Q]}")

    if args.dry:
        print("\n--dry 模式，未写盘")
        return

    backup = EVAL_CSV.with_name("eval_set_backup_248.csv")
    backup.write_text(EVAL_CSV.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    with EVAL_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows + new_rows)

    from collections import Counter
    merged = rows + new_rows
    print(f"\n已写入 {EVAL_CSV}（原 248 备份为 {backup.name}）")
    print("新题型分布:", dict(Counter(r[COL_TYPE] for r in merged)))


if __name__ == "__main__":
    main()
