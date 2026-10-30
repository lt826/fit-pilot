"""RAG 主管线：检索 → 相关度闸门 → 生成。

相关度闸门（拒答第一道防线）：
向量检索的最高余弦分低于阈值 → 认为知识库没有相关内容，
直接拒答、跳过生成调用（省 token，也避免模型对着无关资料硬编）。
生成层的拒答（第二道防线）处理"检索分数够高但资料实际答不了"的情况，
双保险对应评测集里的拒答题。
"""

from dataclasses import dataclass, field

from app.core.config import get_settings
from app.core.observability import obs
from app.rag.generator import Generation, generate
from app.rag.retriever import HybridRetriever, RetrievedChunk


@dataclass
class RAGAnswer:
    query: str
    mode: str  # vector / hybrid / bm25
    answer: str  # 展示用干净回答（拒答时是拒答说明）
    refused: bool
    gated: bool  # True=闸门拦截（未调用生成），False=进入了生成
    citations: list[str] = field(default_factory=list)  # 引用出处（doc § section）
    top1_vector_score: float | None = None
    generation: Generation | None = None


class RAGPipeline:
    def __init__(self, retriever: HybridRetriever | None = None) -> None:
        self.retriever = retriever or HybridRetriever()
        self.threshold = get_settings().rag_refuse_threshold

    @obs(name="rag_answer", capture_input=False, capture_output=False)
    def answer(self, query: str, k: int = 5, mode: str = "hybrid",
               results: list[RetrievedChunk] | None = None,
               on_delta=None) -> RAGAnswer:
        """results 允许外部传入已算好的检索结果（评测场景），
        避免同一问题先 retrieve 一遍算指标、再 answer 一遍的重复 embedding 开销。
        on_delta 提供时答案流式增量回调（SSE 层用）。"""
        from app.core.observability import note_metadata

        result = self._answer_impl(query, k, mode, results, on_delta)
        note_metadata(gated=result.gated, refused=result.refused,
                      top1_vec=round(result.top1_vector_score, 3) if result.top1_vector_score else None,
                      citations=result.citations)
        return result

    def _answer_impl(self, query: str, k: int, mode: str,
                     results: list[RetrievedChunk] | None, on_delta) -> RAGAnswer:
        if results is None:
            results = self.retriever.retrieve(query, k=k, mode=mode)

        # 闸门分数取"检索结果中最高的向量分"而非第一条的分数：
        # hybrid 模式下排第一的可能是只有 BM25 命中的结果（vector_score 为 None）
        vec_scores = [r.vector_score for r in results if r.vector_score is not None]
        top1 = max(vec_scores) if vec_scores else 0.0

        # 闸门只在"有向量分"时按阈值判定。
        # 向量侧不可用（检索已降级到 BM25）时不能拿 top1=0 当"不相关"证据，
        # 否则降级期间所有知识题都会被误拒——改用"是否还有任何检索结果"判断
        gated = (top1 < self.threshold) if vec_scores else (not results)

        if gated:
            refusal = "抱歉，这个问题超出了我目前知识库的范围，暂时无法回答。"
            if on_delta:
                # 拒答文本也必须走流式通道，否则前端收不到任何 delta、气泡空白
                on_delta(refusal)
            return RAGAnswer(
                query=query,
                mode=mode,
                answer=refusal,
                refused=True,
                gated=True,
                top1_vector_score=top1 or None,
            )

        gen = generate(query, [r.chunk for r in results], on_delta=on_delta)
        citations = [results[i - 1].chunk.source for i in gen.cited_indices]
        return RAGAnswer(
            query=query,
            mode=mode,
            answer=gen.clean_answer if not gen.refused else gen.answer,
            refused=gen.refused,
            gated=False,
            citations=citations,
            top1_vector_score=top1,
            generation=gen,
        )
