"""冒烟测试：验证智谱 LLM 与 embedding 调用链路。

用法: .venv/Scripts/python.exe scripts/smoke_test.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import OpenAI  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    if not settings.zhipu_api_key:
        sys.exit("未读到 ZHIPU_API_KEY：请检查系统环境变量或项目根目录 .env")

    print(f"[1/3] 配置加载 ok（chat={settings.chat_model}, embed={settings.embedding_model}）")

    client = OpenAI(api_key=settings.zhipu_api_key, base_url=settings.zhipu_base_url)

    reply = client.chat.completions.create(
        model=settings.chat_model,
        messages=[{"role": "user", "content": "只回复两个字：成功"}],
    )
    print(f"[2/3] LLM 调用 ok：{reply.choices[0].message.content}")

    embedding = client.embeddings.create(model=settings.embedding_model, input="健身知识库测试")
    print(f"[3/3] embedding 调用 ok：维度 {len(embedding.data[0].embedding)}")

    print("环境全绿 ✅")


if __name__ == "__main__":
    main()
