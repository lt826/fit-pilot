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
    embedding_model: str = "embedding-3"
    # 评测裁判模型：比生成模型更强，消除"自己判自己"的同源偏差；
    # 不可用时降级回 chat_model
    judge_model: str = "glm-4.7"

    # Qdrant 向量库（docker compose up -d qdrant 启动）
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "fitpilot_kb"

    # RAG 拒答阈值：检索结果中最高的向量余弦分低于该值时，不进入生成、直接拒答。
    # 两轮标定（2026-10-29）：先导探测初定 0.50 → 全量 45 题分数分布显示
    # 知识题最低 0.469（e010）、拒答题最高 0.433（e008），分界带 (0.433, 0.469)，
    # 最终取 0.45。注意：在与评测集同源数据上标定，评测集扩充后需用新样本复核。
    # 详见 docs/eval-report.md
    rag_refuse_threshold: float = 0.45

    # LangFuse 可观测（EU 云版，国内直连可达；Key 留空则观测自动关闭）
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
