"""LLM / Embedding 客户端工厂。

全项目共用一个 OpenAI 兼容客户端（指向智谱开放平台），避免多处重复创建。
"""

from functools import lru_cache

from openai import OpenAI

from app.core.config import get_settings


@lru_cache
def get_llm_client() -> OpenAI:
    s = get_settings()
    return OpenAI(api_key=s.zhipu_api_key, base_url=s.zhipu_base_url)


@lru_cache
def get_embed_client() -> OpenAI:
    """Embedding 专用客户端：与对话通道解耦——
    两者供应商/配额/故障域都不同（实测智谱 embedding 被账号级限流时 chat 正常），
    共用一个客户端会把单点故障放大到全链路。"""
    s = get_settings()
    return OpenAI(
        api_key=s.embedding_api_key or s.zhipu_api_key,
        base_url=s.embedding_base_url,
    )


def chat_stream(messages: list[dict], temperature: float = 0.3,
                on_delta=None) -> str:
    """对话统一入口：on_delta 提供时走流式并逐段回调，否则普通调用。

    返回完整文本——调用方不必区分流式/非流式两种返回处理。
    每次调用都是一个 LangFuse generation 观测（模型/延迟/用量）。
    """
    from app.core.config import get_settings
    from app.core.observability import obs, note_generation_usage

    @obs(name="llm_chat", as_type="generation")
    def _call() -> str:
        client = get_llm_client()
        model = get_settings().chat_model

        def create(**kwargs):
            # 瞬时故障重试：批量评测/高峰期的 500 与限流靠重试吸收，
            # 不重试则一次网络抖动就可能炸掉整个批任务
            import time
            for attempt in range(1, 4):
                try:
                    return client.chat.completions.create(**kwargs)
                except Exception:  # noqa: BLE001
                    if attempt == 3:
                        raise
                    time.sleep(2 ** attempt)

        if on_delta is None:
            resp = create(model=model, messages=messages, temperature=temperature)
            usage = getattr(resp, "usage", None)
            note_generation_usage(
                model, getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
            )
            return (resp.choices[0].message.content or "").strip()

        parts: list[str] = []
        usage = None
        # include_usage 让最后一个 chunk 携带用量；个别兼容端点不支持则降级重试
        try:
            stream = create(model=model, messages=messages, temperature=temperature,
                            stream=True, stream_options={"include_usage": True})
        except Exception:  # noqa: BLE001 —— 端点不支持 stream_options
            stream = create(model=model, messages=messages, temperature=temperature,
                            stream=True)
        for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = chunk.usage
            if not chunk.choices:  # include_usage 的末尾 chunk choices 为空
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                parts.append(delta)
                on_delta(delta)
        note_generation_usage(
            model, getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
        )
        return "".join(parts).strip()

    return _call()
