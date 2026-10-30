"""手写 function calling 工具循环（Agent 核心）。

为什么手写而不用框架：循环只有几十行，手写能完全掌控
工具结果如何回填、错误如何反馈、轮数如何熔断——
这也是面试时讲清 Agent 执行机制的基础。

循环机制：
  LLM → tool_calls? → 执行工具（结果/错误以 role=tool 回填）→ LLM → ...
  → 无 tool_calls 即最终回答；超过 MAX_TOOL_ROUNDS 轮强制无工具收尾
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.agent.tools import TOOLS_SPEC, execute_tool
from app.core.config import get_settings
from app.core.llm import get_llm_client
from app.db.database import init_db

MAX_TOOL_ROUNDS = 5  # 熔断上限：正常 1-2 轮足够，5 轮仍没完说明模型在打转

SYSTEM_PROMPT = """你是健身私教助手 FitPilot。今天是 {today}。

你可以调用工具管理用户的训练记录、体重数据和查询食物营养。规则：
1. 凡涉及记录或查询用户的训练/体重/食物热量，必须调用工具获取真实数据，禁止编造
2. 用户说"今天/昨天"时换算成具体日期再传参
3. 工具返回 [参数错误]/[工具执行出错] 时，修正参数后重试，最多重试 2 次
4. 工具查询无结果时如实告知，不要虚构记录
5. 最终回答用中文，自然口语化，保留关键数字的准确性
6. 与训练记录和营养无关的健身知识问题，正常凭专业知识回答（第4步会接入知识库检索）"""


@dataclass
class AgentResult:
    answer: str
    tool_trace: list[dict] = field(default_factory=list)  # 每次 {tool, args, result}

    @property
    def used_tools(self) -> bool:
        return bool(self.tool_trace)


class ToolAgent:
    def __init__(self) -> None:
        init_db()  # 幂等：首次运行自动建库建表
        self.model = get_settings().chat_model

    def run(self, query: str, history: list[dict] | None = None,
            on_event=None) -> AgentResult:
        """on_event({"type": "tool_call", ...}) 在每次工具调用后回调，
        供 SSE 层实时推送执行过程（前端过程可视化的数据来源）。"""
        client = get_llm_client()
        messages = [
            {"role": "system",
             "content": SYSTEM_PROMPT.format(today=datetime.now().strftime("%Y-%m-%d"))},
            *(history or []),
            {"role": "user", "content": query},
        ]
        trace: list[dict] = []

        for _round in range(MAX_TOOL_ROUNDS):
            resp = client.chat.completions.create(
                model=self.model, messages=messages, tools=TOOLS_SPEC, temperature=0.3
            )
            msg = resp.choices[0].message

            if not msg.tool_calls:
                return AgentResult(answer=(msg.content or "").strip(), tool_trace=trace)

            # assistant 消息要原样回填（含 tool_calls），模型才能继续同一轮对话
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name,
                                  "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                result = execute_tool(tc.function.name, tc.function.arguments)
                entry = {"tool": tc.function.name,
                         "args": tc.function.arguments, "result": result}
                trace.append(entry)
                if on_event:
                    # result 截断：过程展示用，全量内容 trace 里有
                    on_event({"type": "tool_call", "tool": entry["tool"],
                              "args": entry["args"], "result": result[:200]})
                # 工具结果以 role=tool 回填，错误信息同样走这条路 → 模型可自纠
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        # 熔断：拿掉 tools 再问一次，强制模型基于已有工具结果输出最终回答
        resp = client.chat.completions.create(
            model=self.model, messages=messages, temperature=0.3
        )
        return AgentResult(
            answer=(resp.choices[0].message.content or "").strip() + "\n（已达工具调用轮数上限）",
            tool_trace=trace,
        )
