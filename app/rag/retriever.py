"""混合检索：向量（语义）+ BM25（关键词），RRF 倒数排名融合。

为什么需要两路：
- 向量检索擅长"意思相近但用词不同"（如'练完第二天肌肉疼' ≈ DOMS）
- BM25 擅长精确关键词（如'5x5'、'RDL'、'48小时'这类术语/数字）
- RRF 只用排名不用原始分值，天然规避两路分数量纲不可比的问题
"""

from dataclasses import dataclass

from app.core.observability import obs, note_metadata
from app.rag.bm25_store import BM25Store
from app.rag.chunker import Chunk
from app.rag.embedder import embed_query
from app.rag.vector_store import VectorStore

RRF_K = 60  # RRF 平滑常数，业界通用值


@dataclass
class RetrievedChunk:
    chunk: Chunk
    rrf_score: float
    vector_score: float | None  # 未进入向量 top-N 时为 None
    bm25_score: float | None  # 未进入 BM25 top-N 时为 None

    @property
    def source(self) -> str:
        return self.chunk.source


class HybridRetriever:
    def __init__(self, vector_store: VectorStore | None = None, bm25: BM25Store | None = None) -> None:
        self.vector = vector_store or VectorStore()
        self.bm25 = bm25 or BM25Store.load()

    def retrieve(self, query: str, k: int = 5, k_each: int = 20, mode: str = "hybrid") -> list[RetrievedChunk]:
        return self._obs_retrieve(query, k, k_each, mode)

    # 观测包装层：与业务方法隔离，避免 self（含 Qdrant 客户端）被序列化进观测入参
    @obs(name="hybrid_retrieve", as_type="retriever",
         capture_input=False, capture_output=False)
    def _obs_retrieve(self, query: str, k: int, k_each: int, mode: str) -> list[RetrievedChunk]:
        results = self._do_retrieve(query, k, k_each, mode)
        note_metadata(
            query=query, mode=mode, hits=len(results),
            top_sources=[r.chunk.source for r in results[:5]],
        )
        return results

    def _do_retrieve(self, query: str, k: int, k_each: int, mode: str) -> list[RetrievedChunk]:
        """两路各取 k_each 个候选，RRF 融合后返回前 k 个。

        mode: "hybrid"（默认，两路融合）/ "vector" / "bm25"——
        单路模式供第2步对比实验使用（固定其余变量只换检索策略）。

        k_each(20) 故意大于 k(5)：给融合留足候选空间，
        让"只被一路命中"的结果也有机会挤进前 k——
        这正是混合检索相对单路检索的价值来源。
        """
        vec_hits: list = []
        bm_hits: list = []
        if mode in ("hybrid", "vector"):
            # 降级设计：向量侧（embedding API 或 Qdrant）不可用时退到 BM25 单路，
            # 助手整体保持可用（词法检索质量略降好过完全瘫痪）；
            # vector-only 模式是评测基线，评测必须暴露故障，不降级
            try:
                vec_hits = self.vector.search(embed_query(query), top_k=k_each)
            except Exception as exc:  # noqa: BLE001
                if mode == "hybrid":
                    print(f"  [降级] 向量检索不可用({exc.__class__.__name__})，仅用 BM25")
                else:
                    raise
        if mode in ("hybrid", "bm25"):
            bm_hits = self.bm25.search(query, top_k=k_each)

        # RRF：每路按排名贡献 1/(K+rank+1)，两路命中同一 chunk 时分数相加，
        # 因此"双路都认可"的 chunk 天然排到最前（无需调权重）
        rrf: dict[str, float] = {}
        vec_by_id = {}
        bm_by_id = {}

        for rank, hit in enumerate(vec_hits):
            cid = hit["payload"]["chunk_id"]
            rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
            vec_by_id[cid] = hit
        for rank, (score, chunk) in enumerate(bm_hits):
            rrf[chunk.chunk_id] = rrf.get(chunk.chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
            bm_by_id[chunk.chunk_id] = (score, chunk)

        top_ids = sorted(rrf, key=rrf.get, reverse=True)[:k]
        results = []
        for cid in top_ids:
            vec_hit = vec_by_id.get(cid)
            bm_hit = bm_by_id.get(cid)
            # 融合结果优先用向量侧 payload 构造 Chunk（两路同源，内容一致）
            if vec_hit:
                p = vec_hit["payload"]
                chunk = Chunk(
                    chunk_id=cid,
                    doc_path=p["doc_path"],
                    doc_title=p["doc_title"],
                    category=p["category"],
                    section_title=p["section_title"],
                    text=p["text"],
                )
            else:
                chunk = bm_hit[1]
            results.append(
                RetrievedChunk(
                    chunk=chunk,
                    rrf_score=rrf[cid],
                    vector_score=vec_hit["score"] if vec_hit else None,
                    bm25_score=bm_hit[0] if bm_hit else None,
                )
            )
        return results
