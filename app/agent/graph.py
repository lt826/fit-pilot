"""LangGraph 编排：意图分流到 闲聊 / 知识问答(RAG) / 任务执行(工具) / 混合 四条链路。

为什么用 LangGraph 而不是 if-else：图结构把路由决策显式化为节点和边，
新增链路（如第7步的微调模型节点）只是加节点，不改主流程；
条件边由 classify 结果驱动，单一职责、便于单测各节点。

事件流（emit）：各节点在执行过程中把 route/tool_call/citation/delta
事件实时抛给回调——SSE 层据此做过程可视化，CLI 层传 None 保持纯同步。
节点业务逻辑不感知传输方式，一套代码两种消费。

混合链路（本项目的招牌能力）执行三步：
  ① 工具链路：只查数据不提建议（防模型跳过工具直接编）
  ② RAG 链路：检索相关健身知识
  ③ 合成：用户画像 + ①的数据 + ②的资料 → 最终回答
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.agent.loop import ToolAgent
from app.agent.router import classify
from app.core.llm import chat_stream
from app.memory.session import Session
from app.memory import profile as profile_mem
from app.rag.pipeline import RAGPipeline


class CoachState(TypedDict, total=False):
    query: str
    session: Session
    profile_note: str  # 用户画像摘要（个性化注入）
    emit: object  # 可选事件回调 (event: str, data: dict) -> None
    route: str
    answer: str
    citations: list[str]
    tool_trace: list[dict]


@dataclass
class CoachResult:
    route: str
    answer: str
    citations: list[str] = field(default_factory=list)
    tool_trace: list[dict] = field(default_factory=list)


@lru_cache
def _pipeline() -> RAGPipeline:
    # 模块级缓存：BM25 分词器与 pickle 加载只发生一次
    return RAGPipeline()


def _emit(state: CoachState, event: str, data: dict) -> None:
    emit = state.get("emit")
    if emit:
        emit(event, data)


def _rewrite_query(query: str, history: list[dict]) -> str:
    """多轮追问改写："那肩膀呢？"→"卧推时肩膀疼怎么调整？"。
    近期原文历史足够改写使用，无需摘要。"""
    if not history:
        return query
    convo = "\n".join(f"{m['role']}: {m['content'][:100]}" for m in history[-4:])
    prompt = (f"结合对话历史，把用户最新问题改写成一个独立、完整、可脱离上下文理解的问题。\n"
              f"只输出改写后的问题，若本身已完整则原样输出。\n\n对话历史：\n{convo}\n\n最新问题：{query}")
    return chat_stream([{"role": "user", "content": prompt}], temperature=0)


# ---------------- 四个业务节点 ----------------

def _node_classify(state: CoachState) -> CoachState:
    session: Session = state["session"]
    route = classify(state["query"], session.context_history())
    state["route"] = route
    _emit(state, "route", {"route": route})
    return state


def _node_chat(state: CoachState) -> CoachState:
    session: Session = state["session"]
    system = ("你是健身私教助手 FitPilot，友好简洁地回应问候与闲聊。"
              f"{state['profile_note']}")
    messages = [{"role": "system", "content": system + session.as_system_note()},
                *session.context_history(),
                {"role": "user", "content": state["query"]}]
    state["answer"] = chat_stream(
        messages, on_delta=lambda t: _emit(state, "delta", {"text": t})
    )
    return state


def _node_knowledge(state: CoachState) -> CoachState:
    session: Session = state["session"]
    rewritten = _rewrite_query(state["query"], session.context_history())
    rag = _pipeline().answer(
        rewritten, mode="hybrid",
        on_delta=lambda t: _emit(state, "delta", {"text": t}),
    )
    state["answer"] = rag.answer
    state["citations"] = rag.citations
    if rag.citations:
        _emit(state, "citation", {"sources": rag.citations})
    return state


def _node_task(state: CoachState) -> CoachState:
    session: Session = state["session"]
    result = ToolAgent().run(
        state["query"],
        history=session.context_history(),
        on_event=lambda e: _emit(state, e["type"], e),
    )
    state["answer"] = result.answer
    state["tool_trace"] = result.tool_trace
    # 工具循环的最终回答是整段返回的（流式意义在工具过程），一次性推给前端
    _emit(state, "delta", {"text": result.answer})
    return state


def _node_mixed(state: CoachState) -> CoachState:
    """先工具查数据 → 再 RAG 取知识 → 最后合成。"""
    session: Session = state["session"]
    query = state["query"]

    # ① 只取数据/信息：明确禁止工具 Agent 给建议，避免两段回答互相矛盾。
    # 可用信息源有两类：用户个人数据（训练/体征），或联网搜索（仅健身相关时效性问题）
    data_result = ToolAgent().run(
        f"请只调用工具获取回答下面问题所需的信息——用户训练/身体数据用查询工具，"
        f"时效性问题（最新/今年/最近）用联网搜索。"
        f"汇总获取到的信息本身，不要给任何建议或评价：\n{query}",
        history=session.context_history(),
        on_event=lambda e: _emit(state, e["type"], e),
    )

    # ② 取知识：数据描述拼进检索 query，让检索带上个性化语境（此处不流式，它是素材）
    rag = _pipeline().answer(f"{query}（用户近况：{data_result.answer}）", mode="hybrid")
    knowledge = "" if rag.refused else rag.answer
    if rag.citations:
        _emit(state, "citation", {"sources": rag.citations})

    # ③ 合成（流式推给前端）
    system = (
        "你是健身私教助手 FitPilot。请基于【用户画像】【用户数据】【知识资料】"
        "回答问题：结论优先、简洁分点、保留关键数字；引用资料观点时注明来自知识库；"
        "【用户数据】里若含联网搜索结果，必须向用户说明该部分来自网络检索并附来源链接，"
        "与知识库信息区分开；若用户数据显示情况与知识资料不符，如实说明；"
        "两处都缺信息时坦白告知，不要编造。"
        f"\n用户画像：{state['profile_note'] or '暂无'}"
    )
    user = (f"【用户数据】{data_result.answer}\n\n"
            f"【知识资料】{knowledge or '（知识库未检索到直接相关内容）'}\n\n"
            f"【问题】{query}")
    state["answer"] = chat_stream(
        [{"role": "system", "content": system},
         {"role": "user", "content": user}],
        on_delta=lambda t: _emit(state, "delta", {"text": t}),
    )
    state["tool_trace"] = data_result.tool_trace
    state["citations"] = rag.citations
    return state


def build_coach_graph():
    graph = StateGraph(CoachState)
    graph.add_node("classify", _node_classify)
    graph.add_node("chat", _node_chat)
    graph.add_node("knowledge", _node_knowledge)
    graph.add_node("task", _node_task)
    graph.add_node("mixed", _node_mixed)
    graph.set_entry_point("classify")
    graph.add_conditional_edges(
        "classify",
        lambda s: s["route"],  # classify 结果决定走向
        {"chat": "chat", "knowledge": "knowledge", "task": "task", "mixed": "mixed"},
    )
    for node in ("chat", "knowledge", "task", "mixed"):
        graph.add_edge(node, END)
    return graph.compile()


class FitnessCoach:
    """对外统一入口：管理会话记忆与画像，驱动 LangGraph。"""

    def __init__(self) -> None:
        self.graph = build_coach_graph()
        self.session = Session()

    def _run(self, query: str, emit=None) -> CoachResult:
        # 节点使用"本轮之前"的历史做上下文，所以先 invoke 再 append
        final: CoachState = self.graph.invoke(
            {"query": query, "session": self.session,
             "profile_note": profile_mem.profile_summary(), "emit": emit}
        )
        return CoachResult(
            route=final.get("route", "knowledge"),
            answer=final.get("answer", ""),
            citations=final.get("citations", []),
            tool_trace=final.get("tool_trace", []),
        )

    def _memorize(self, query: str, answer: str) -> None:
        self.session.append("user", query)
        self.session.append("assistant", answer)
        if self.session.needs_compression():
            self.session.compress()

    def chat(self, query: str) -> CoachResult:
        """同步完整版（CLI / 评测用）。"""
        result = self._run(query)
        self._memorize(query, result.answer)
        if updates := profile_mem.maybe_extract_and_update(query):
            result.answer += f"\n（已更新用户画像：{updates}）"
        return result

    def stream_chat(self, query: str, emit) -> CoachResult:
        """事件流版（SSE 用）：过程事件实时回调，答案以 delta 事件推送。"""
        result = self._run(query, emit=emit)
        self._memorize(query, result.answer)
        if updates := profile_mem.maybe_extract_and_update(query):
            _emit({"emit": emit}, "notice", {"text": f"已更新用户画像：{updates}"})
        return result
