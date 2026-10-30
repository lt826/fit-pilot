"""短期记忆：多轮对话历史 + 超限自动压缩。

策略：保留最近 KEEP_RECENT 条原文（近期指代最关键），
更早的对话由 LLM 压缩成一段摘要注入 system 上下文。
不压缩的问题：历史无限增长 → token 成本线性上升且超上下文；
全量摘要的问题：近期指代丢失。所以采用"摘要 + 近期原文"双层。
"""

from app.core.config import get_settings
from app.core.llm import get_llm_client

MAX_TURNS = 10  # 原文历史条数上限（user/assistant 各算一条），超过触发压缩
KEEP_RECENT = 4  # 压缩时保留的最近条数

_COMPRESS_PROMPT = """把下面的健身助手对话历史压缩成一段简洁摘要（150字内），
保留：用户的目标与约束、已完成的记录操作、已达成的结论。只输出摘要内容。"""


class Session:
    def __init__(self) -> None:
        self.history: list[dict] = []
        self.summary: str = ""

    def append(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})

    def needs_compression(self) -> bool:
        return len(self.history) > MAX_TURNS

    def compress(self) -> None:
        """旧历史并入摘要，只留最近 KEEP_RECENT 条原文。"""
        old = self.history[:-KEEP_RECENT]
        self.history = self.history[-KEEP_RECENT:]
        if not old:
            return
        text = "\n".join(f"{m['role']}: {m['content']}" for m in old)
        if self.summary:
            text = f"既有摘要：{self.summary}\n新增对话：\n{text}"
        resp = get_llm_client().chat.completions.create(
            model=get_settings().chat_model,
            temperature=0.2,
            messages=[{"role": "user", "content": f"{_COMPRESS_PROMPT}\n\n{text}"}],
        )
        self.summary = (resp.choices[0].message.content or "").strip()

    def context_history(self, max_messages: int = 6) -> list[dict]:
        """给各链路 prompt 用的近期上下文。"""
        return self.history[-max_messages:]

    def as_system_note(self) -> str:
        """摘要以 system 备注形式注入，模型能区分'摘要'与'原文'。"""
        return f"（此前对话摘要：{self.summary}）" if self.summary else ""
