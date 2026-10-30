"""检索演示：命令行验证混合检索效果（第1步验收脚本）。

用法:
  .venv/Scripts/python.exe scripts/search_demo.py 新手一周练几次
  .venv/Scripts/python.exe scripts/search_demo.py   # 无参数进入交互模式
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.retriever import HybridRetriever  # noqa: E402


def show(retriever: HybridRetriever, query: str, k: int = 5) -> None:
    print(f"\n查询: {query}")
    results = retriever.retrieve(query, k=k)
    if not results:
        print("  （无结果）")
        return
    for i, r in enumerate(results, 1):
        vec = f"{r.vector_score:.3f}" if r.vector_score is not None else "  -  "
        bm = f"{r.bm25_score:.2f}" if r.bm25_score is not None else "  -  "
        snippet = r.chunk.text[:60].replace("\n", " ")
        # ◎ = 向量与 BM25 双路都命中，融合后通常是最强信号；只有一路命中则空格
        marker = "◎" if r.vector_score is not None and r.bm25_score is not None else " "
        print(f"  {marker}{i}. rrf={r.rrf_score:.4f} vec={vec} bm25={bm}")
        print(f"     [{r.chunk.category}] {r.chunk.source}")
        print(f"     {snippet}...")


def main() -> None:
    print("加载混合检索（首次会加载 BM25/分词器，稍慢）...")
    retriever = HybridRetriever()
    if len(sys.argv) > 1:
        show(retriever, " ".join(sys.argv[1:]))
        return
    print("进入交互模式，输入 q 退出")
    while True:
        try:
            query = input("\n查询> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not query or query.lower() in {"q", "quit", "exit"}:
            break
        show(retriever, query)


if __name__ == "__main__":
    main()
