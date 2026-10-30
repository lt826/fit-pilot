"""带引用的答案生成：检索结果装配 prompt → LLM → 解析引用标注。

两个关键设计：
1. 拒答信号用结构化标记而非关键词判断——要求模型在无法回答时
   以"【无法回答】"开头，代码用 startswith 判定，确定性强、不误判
2. 引用标注让模型在回答里写 [1] [2]，再用正则回收映射回真实出处，
   从而知道"答案实际用了哪几条资料"（而不是把我们喂的全算引用）
"""

import re
from dataclasses import dataclass, field

from app.core.llm import chat_stream
from app.rag.chunker import Chunk

REFUSE_MARKER = "【无法回答】"

SYSTEM_PROMPT = """你是健身知识助手 FitPilot。严格遵守以下规则：
1. 只根据【参考资料】回答问题，禁止使用资料之外的知识，禁止编造
2. 回答中用到某条资料时，用 [1] [2] 这样的标注注明来源
3. 如果参考资料不足以回答问题，你的回复必须以"【无法回答】"开头，\
并说明当前知识库无法覆盖该问题，不要尝试给出任何答案
4. 回答简洁、分点，面向普通健身人群，保留资料中的具体数字"""

_CITE_RE = re.compile(r"\[(\d+)\]")


@dataclass
class Generation:
    answer: str  # 模型原始回答（拒答时含【无法回答】标记）
    refused: bool  # 是否拒答
    cited_indices: list[int] = field(default_factory=list)  # 回答中实际引用的资料编号

    @property
    def clean_answer(self) -> str:
        return self.answer.removeprefix(REFUSE_MARKER).strip()


def build_context(chunks: list[Chunk]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(f"[{i}] 来源：{c.doc_path} § {c.section_title}\n{c.text}")
    return "\n\n".join(parts)


def generate(query: str, chunks: list[Chunk], on_delta=None) -> Generation:
    """检索结果 → 带引用的回答。调用方需保证 chunks 非空。

    on_delta 提供时流式输出（增量回调），完整回答仍由本函数聚合返回——
    拒答判定与引用解析必须在完整文本上做，调用方不用关心流式细节。
    """
    answer = chat_stream(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"【参考资料】\n{build_context(chunks)}\n\n【问题】{query}",
            },
        ],
        temperature=0.3,
        on_delta=on_delta,
    )
    refused = answer.startswith(REFUSE_MARKER)
    # 去重保序：模型可能多次引用同一条资料
    cited = sorted({int(n) for n in _CITE_RE.findall(answer) if int(n) <= len(chunks)})
    return Generation(answer=answer, refused=refused, cited_indices=cited)
