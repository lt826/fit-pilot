"""BM25 词法索引：jieba 分词 + rank_bm25，序列化到本地缓存。

语料千级 chunk 以内，索引体积极小，进程内构建 + pickle 缓存即可，
不值得为此引入 Elasticsearch。重建索引时随 build_index.py 一并更新。
"""

import pickle
from pathlib import Path

import jieba
from rank_bm25 import BM25Okapi

from app.rag.chunker import Chunk, load_corpus

jieba.setLogLevel(20)  # 关闭分词器的构建日志

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = PROJECT_ROOT / "data" / "index_cache" / "bm25.pkl"


def tokenize(text: str) -> list[str]:
    """中文分词：BM25 的词法匹配单元。小写化并去掉空白 token。"""
    return [t for t in jieba.lcut(text.lower()) if t.strip()]


class BM25Store:
    def __init__(self, chunks: list[Chunk], tokenized: list[list[str]]) -> None:
        self.chunks = chunks
        self.bm25 = BM25Okapi(tokenized)

    @classmethod
    def build(cls, chunks: list[Chunk]) -> "BM25Store":
        return cls(chunks, [tokenize(c.text) for c in chunks])

    @classmethod
    def load(cls, cache_path: Path = CACHE_PATH) -> "BM25Store":
        """从缓存加载；缓存不存在或与语料版本不符时自动重建。

        语料版本 = chunk 数量 + 最后一个 chunk 的 id（语料一变就失效），
        避免出现"向量库是新语料、BM25 是旧语料"的错位。
        """
        if cache_path.exists():
            with cache_path.open("rb") as f:
                store: BM25Store = pickle.load(f)
            if store._fingerprint() == cls._corpus_fingerprint():
                return store
            print("  BM25 缓存与语料不匹配，重建中...")
        fresh = load_corpus()
        store = cls.build(fresh)
        store.save(cache_path)
        return store

    def save(self, cache_path: Path = CACHE_PATH) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("wb") as f:
            pickle.dump(self, f)

    def search(self, query: str, top_k: int = 20) -> list[tuple[float, Chunk]]:
        """返回 [(bm25得分, chunk)]，按得分降序，过滤零分。"""
        scores = self.bm25.get_scores(tokenize(query))
        # 过滤零分：与查询没有任何共同词项的 chunk 不参与排名，
        # 否则千级语料下会返回大量 0 分噪音挤占 top_k
        ranked = sorted(
            ((float(s), c) for s, c in zip(scores, self.chunks) if s > 0),
            key=lambda x: x[0],
            reverse=True,
        )
        return ranked[:top_k]

    def _fingerprint(self) -> str:
        return f"{len(self.chunks)}:{self.chunks[-1].chunk_id if self.chunks else ''}"

    @staticmethod
    def _corpus_fingerprint() -> str:
        fresh = load_corpus()
        return f"{len(fresh)}:{fresh[-1].chunk_id if fresh else ''}"
