"""全量重建索引：语料 → embedding → Qdrant + BM25 缓存。

用法: .venv/Scripts/python.exe scripts/build_index.py
前置: docker compose up -d qdrant（Qdrant 在 6333 端口运行）
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.bm25_store import BM25Store  # noqa: E402
from app.rag.chunker import load_corpus  # noqa: E402
from app.rag.embedder import embed_texts  # noqa: E402
from app.rag.vector_store import VectorStore  # noqa: E402


def main() -> None:
    t0 = time.time()

    print("[1/4] 解析语料...")
    chunks = load_corpus()
    if not chunks:
        sys.exit("语料为空：请先准备 data/corpus/ 下的 Markdown")
    total_chars = sum(len(c.text) for c in chunks)
    by_cat: dict[str, int] = {}
    for c in chunks:
        by_cat[c.category] = by_cat.get(c.category, 0) + 1
    print(f"  {len(chunks)} 个 chunk / {len({c.doc_path for c in chunks})} 篇文档 / 约{total_chars}字")
    print("  " + "，".join(f"{cat}:{n}" for cat, n in sorted(by_cat.items())))

    print("[2/4] 调用 embedding...")
    vectors = embed_texts([c.text for c in chunks])
    dim = len(vectors[0])

    print(f"[3/4] 写入 Qdrant（dim={dim}）...")
    store = VectorStore()
    # 全量重建而非增量更新：千级以内 chunk 重建只要十几秒，
    # 而增量必须额外处理"语料删除/修改后旧 chunk 残留"的清理逻辑——
    # 语料规模上来之前，简单可重复比聪明更重要
    store.recreate(dim)
    store.upsert_chunks(chunks, vectors)
    print(f"  集合内点数: {store.count()}")

    print("[4/4] 构建 BM25 缓存...")
    bm25 = BM25Store.build(chunks)
    bm25.save()

    print(f"完成，耗时 {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
