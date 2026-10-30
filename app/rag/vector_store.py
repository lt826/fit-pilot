"""Qdrant 向量库封装：建集合、批量写入、相似检索。"""

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.core.config import get_settings
from app.rag.chunker import Chunk


class VectorStore:
    def __init__(self, url: str | None = None, collection: str | None = None) -> None:
        s = get_settings()
        self.client = QdrantClient(url=url or s.qdrant_url)
        self.collection = collection or s.qdrant_collection

    def recreate(self, dim: int) -> None:
        """删除并重建集合：全量重建索引用，保证与语料一一对应。"""
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )

    def upsert_chunks(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        # payload 设计要点：
        # - chunk_id 冗余存进 payload：RRF 融合时要用 id 把向量/BM25 两路结果对齐
        # - text 也存进 payload：第2步生成时直接从检索结果取上下文，无需回读源文件
        # - 全部来源元数据（doc_path/section_title/category）随点存储：
        #   引用溯源和按类目过滤都依赖它，避免检索后再查一次文件系统
        points = [
            PointStruct(
                id=c.chunk_id,
                vector=v,
                payload={
                    "chunk_id": c.chunk_id,
                    "doc_path": c.doc_path,
                    "doc_title": c.doc_title,
                    "category": c.category,
                    "section_title": c.section_title,
                    "text": c.text,
                },
            )
            for c, v in zip(chunks, vectors)
        ]
        for i in range(0, len(points), 64):
            self.client.upsert(collection_name=self.collection, points=points[i : i + 64])

    def search(self, query_vector: list[float], top_k: int = 20) -> list[dict]:
        """返回 [{"score": float, "payload": {...}}, ...]。"""
        result = self.client.query_points(
            collection_name=self.collection, query=query_vector, limit=top_k
        )
        return [{"score": p.score, "payload": p.payload} for p in result.points]

    def count(self) -> int:
        info = self.client.get_collection(self.collection)
        return info.points_count
