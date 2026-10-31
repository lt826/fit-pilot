"""集中配置：从环境变量与 .env 读取，全项目只此一处。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 智谱开放平台（OpenAI 兼容接口）
    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    chat_model: str = "glm-4-flash"  # 开发期用免费模型，正式评测换 glm-4 系列
    # 评测裁判模型：比生成模型更强，消除"自己判自己"的同源偏差；
    # 不可用时降级回 chat_model
    judge_model: str = "glm-4.7"

    # Embedding 独立通道（供应商可换）：默认回落智谱；配 .env 切硅基流动 bge-m3。
    # 注意：换 embedding 模型必须重建索引，且拒答阈值需按新模型的分数分布重新标定
    embedding_api_key: str = ""  # 留空回落 zhipu_api_key
    embedding_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    embedding_model: str = "embedding-3"

    # Qdrant 向量库（docker compose up -d qdrant 启动）
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "fitpilot_kb"

    # RAG 拒答阈值：检索结果中最高的向量余弦分低于该值时，不进入生成、直接拒答。
    # 标定（2026-10-31，bge-m3）：知识题 top1 分布 0.693-0.832，拒答题 0.381-0.537，
    # 取分界带中点 0.61（两侧各留 ~0.08 余量）。
    # 注意：该阈值与 embedding 模型强绑定——换模型必须用同款探测重标定（旧 embedding-3 为 0.45）
    rag_refuse_threshold: float = 0.61

    # LangFuse 可观测（EU 云版，国内直连可达；Key 留空则观测自动关闭）
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
