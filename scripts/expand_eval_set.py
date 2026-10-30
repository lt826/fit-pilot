"""评测集扩充（第7步①）：58 → 150+ 条。

- 知识题：遍历语料章节自动出题——问答型文档的章节标题本身就是问题；
  动作库按"动作名+板块"模板出题。已被现有评测覆盖的章节跳过
- 拒答/混合/任务题：手工设计清单（混合题专为"工具+检索"双依赖场景设计）
- 新增 acceptable_docs(可接受出处) 列：修正 e014 暴露的"单出处标签"口径问题
- 幂等：已存在相同问题的行跳过

用法: .venv/Scripts/python.exe scripts/expand_eval_set.py
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.chunker import load_corpus  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_CSV = PROJECT_ROOT / "data" / "eval" / "eval_set.csv"

COL_ID = "id(编号)"
COL_Q = "question(问题)"
COL_REF = "reference_answer(参考答案)"
COL_SRC = "source_doc(来源文档)"
COL_TYPE = "type(题型)"
COL_ACC = "acceptable_docs(可接受出处)"

# 问答标题的"像问题"特征：不像问题的章节不出题
_Q_MARKS = ("什么", "怎么", "哪些", "多少", "多久", "吗", "几", "如何", "能不能",
            "可以", "应该", "还是", "需要", "有用吗", "靠谱")

# 动作库板块 → 出题模板
_EXERCISE_TEMPLATES = {
    "目标肌群与价值": "{a}主要锻炼哪些肌肉？",
    "动作步骤": "{a}的标准动作步骤是什么？",
    "常见错误": "做{a}时最常见的错误有哪些？",
    "进阶与退阶": "{a}做不动怎么退阶？想进阶又该怎么练？",
    "安全要点": "做{a}有哪些安全注意事项？",
}

REJECTS = [
    ("怎么用Python写一个网页爬虫？", "域外：编程"),
    ("帮我算一道线性代数题：矩阵A的逆怎么求？", "域外：数学"),
    ("明天北京的天气怎么样？", "域外：天气"),
    ("推荐一条云南七日游的路线", "域外：旅游"),
    ("现在买什么股票比较稳？", "域外：投资建议"),
    ("租房合同违约金条款怎么写才有法律效力？", "域外：法律"),
    ("帮我写一份实习周报", "域外：文书"),
    ("把'健身使我快乐'翻译成英文并润色", "域外：翻译"),
    ("如何用PPT做出高级感的封面？", "域外：办公软件"),
    ("我最近总是情绪低落，是不是得了抑郁症？", "域外：医疗诊断"),
    ("半月板缝合手术的具体术式怎么选？", "超知识库深度：手术方案"),
    ("布洛芬和乙酰氨基酚可以同时吃吗？剂量呢？", "超知识库深度：药物"),
    ("水瓶座和处女座合得来吗？", "域外：星座"),
    ("原神前期培养什么角色性价比高？", "域外：游戏"),
    ("高考志愿填报选计算机还是临床医学？", "域外：升学"),
]

MIXED = [
    ("我这周练了两次背，是不是太少了？", "需查训练记录+每肌群每周2次的知识综合判断"),
    ("我最近的体重趋势怎么样？减脂速度正常吗？", "需查体重记录+每周0.5-1kg的健康减脂知识"),
    ("我今天吃了两碗米饭和150克鸡胸肉，蛋白质够吗？", "需营养工具计算+按体重估蛋白需求"),
    ("结合我的目标帮我安排这周的腿部训练", "需画像(目标/伤病史)+腿部训练知识"),
    ("以我的训练水平，适合直接上5x5计划吗？", "需画像(训练年限)+5x5适合期知识"),
    ("我最近三周练了几次腿？恢复时间够吗？", "需查记录+大肌群48-72h恢复知识"),
    ("我腰部有旧伤，还能做硬拉吗？", "需画像(伤病史)+硬拉替代动作知识"),
    ("我上周和这周的训练容量比怎么样？", "需查两周记录对比+容量渐进知识"),
    ("按我的体重，每天应该喝多少水？", "需体重数据(画像或指标)+30-40ml/kg知识"),
    ("我这周训练频率和我上周比是不是太高了？", "需查两周记录+频率恢复知识"),
]

TASKS = [
    ("记一下我今天做了臀桥50公斤3组每组12次", "应调用log_training写入并确认"),
    ("查一下豆腐有什么营养成分", "应调用query_nutrition返回豆腐每100克营养"),
    ("帮我看看最近30天我练了几次", "应调用query_training统计近30天记录"),
    ("帮我记录一下腰围85厘米", "应调用log_body_metric记录腰围"),
]


def gen_knowledge_candidates() -> list[dict]:
    cands = []
    for c in load_corpus():
        title, doc = c.section_title, c.doc_path
        if c.category == "exercises":
            action = c.doc_title.replace("（", "(").split("(")[0]
            tpl = _EXERCISE_TEMPLATES.get(title)
            if tpl:
                cands.append({"q": tpl.format(a=action), "ref": c.text[60:220],
                              "src": doc, "type": "knowledge"})
        else:
            if any(m in title for m in _Q_MARKS) or title.endswith(("？", "?")):
                ref = c.text.split("\n", 2)
                ref_text = ref[2] if len(ref) > 2 else c.text
                cands.append({"q": title if title.endswith(("？", "?")) else title + "？",
                              "ref": ref_text[:180], "src": doc, "type": "knowledge"})
    return cands


def main() -> None:
    with EVAL_CSV.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if COL_ACC not in fieldnames:
        fieldnames = fieldnames + [COL_ACC]

    existing_q = {r[COL_Q].strip() for r in rows}
    # e014 口径修正：多文档都可接受
    for r in rows:
        if r[COL_ID] == "e014":
            r[COL_ACC] = "exercises/引体向上.md;exercises/高位下拉.md"
        r.setdefault(COL_ACC, "")

    next_id = max(int(r[COL_ID][1:]) for r in rows) + 1
    added = {"knowledge": 0, "reject": 0, "mixed": 0, "task": 0}

    def add(q, ref, src, typ, acc="", note=""):
        nonlocal next_id
        if q.strip() in existing_q:
            return
        rows.append({COL_ID: f"e{next_id:03d}", COL_Q: q, COL_REF: ref,
                     COL_SRC: src, COL_TYPE: typ, COL_ACC: acc or src,
                     "notes(备注)": note})
        existing_q.add(q.strip())
        next_id += 1
        added[typ] += 1

    for c in gen_knowledge_candidates():
        add(c["q"], c["ref"], c["src"], "knowledge")
    for q, note in REJECTS:
        add(q, "应拒答：超出健身知识库范围", "", "reject", "", note)
    for q, ref in MIXED:
        add(q, ref, "", "mixed", "", "需工具+检索综合")
    for q, ref in TASKS:
        add(q, ref, "", "task", "", "Agent工具题")

    with EVAL_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    print(f"新增 {sum(added.values())} 条：{added}")
    print(f"总数：{len(rows)} 条，分布：{dict(Counter(r[COL_TYPE] for r in rows))}")


if __name__ == "__main__":
    main()
