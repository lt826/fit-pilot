"""Embedding 封装：批量调用智谱 embedding-3，带指数退避重试。"""

import time

from app.core.config import get_settings
from app.core.llm import get_llm_client

# 每批文本数：兼顾吞吐与单请求 token 上限；语料千级以内 16 比较稳
BATCH_SIZE = 16
MAX_RETRIES = 3


def embed_texts(texts: list[str], batch_size: int = BATCH_SIZE) -> list[list[float]]:
    """按输入顺序返回每条文本的向量。"""
    client = get_llm_client()
    model = get_settings().embedding_model
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        vectors.extend(_embed_batch(client, model, batch))
        done = min(i + batch_size, len(texts))
        print(f"  embedding {done}/{len(texts)}")
    return vectors


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def _embed_batch(client, model: str, batch: list[str]) -> list[list[float]]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.embeddings.create(model=model, input=batch)
            # 官方约定 resp.data 顺序与 input 一致
            return [item.embedding for item in resp.data]
        except Exception as exc:  # noqa: BLE001 —— 网络/限流统一在此重试
            if attempt == MAX_RETRIES:
                raise
            wait = 2**attempt
            print(f"  embedding 第{attempt}次失败({exc.__class__.__name__})，{wait}s 后重试")
            time.sleep(wait)
    return []  # 不可达，安抚类型检查
