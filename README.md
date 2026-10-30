# FitPilot

> 基于 RAG 与多工具 Agent 的智能健身私教系统

FitPilot 不只是一个"能查资料的问答机"：它认识用户（长期画像 + 记忆），既能回答有出处的健身知识（混合检索 + 重排），也能动手做事（记录训练、查食物热量、生成训练计划）。

## 功能规划

- **知识问答（RAG）**：健身/营养知识，答案附带引用来源，知识库外的问题主动拒答
- **任务执行（Agent）**：训练记录增删查、食物热量查询、体重追踪、训练计划生成
- **个性化（记忆）**：长期用户画像（目标/水平/伤病史）+ 短期对话压缩
- **意图路由**：LangGraph 分流闲聊 / 知识问答 / 任务执行 / 混合型问题（先查数据再答知识）

## 架构

<!-- TODO: 架构图占位，阶段②完成后补充 -->

```
用户输入 → LangGraph 路由
  ├─ 闲聊 ────────────────→ LLM 直接回答
  ├─ 知识问答 → 查询改写 → 混合检索(BM25+向量) → rerank → 带引用生成
  ├─ 任务执行 → 工具循环 → [热量查询|训练记录|计划生成|体重追踪]
  └─ 混合 ────→ 规划：先调工具拿数据，再走检索，最后综合
                    ↓
        记忆层(短期压缩+长期画像) / LangFuse 全链路追踪
```

## 快速开始

### 方式一：Docker 一键部署（推荐）

```bash
cp .env.example .env   # 填入 ZHIPU_API_KEY（LANGFUSE_* 可选，不填则观测自动关闭）
docker compose up -d --build
# 打开 http://localhost:8090
```

三个服务自动编排：Nginx 前端(8090) → FastAPI 后端 → Qdrant 向量库；训练数据落宿主机 `./data` 卷，容器重建不丢；SSE 流式经 Nginx 反代透传（`proxy_buffering off`）。

### 方式二：本地开发

```bash
# 1. 安装依赖（需要 uv：pip install uv）
uv sync

# 2. 配置密钥
cp .env.example .env   # 填入 ZHIPU_API_KEY

# 3. 启动 Qdrant
docker compose up -d qdrant

# 4. 冒烟测试 + 建索引
.venv/Scripts/python.exe scripts/smoke_test.py
.venv/Scripts/python.exe scripts/build_index.py

# 5. 后端(8000) 与前端(5173/5174)
.venv/Scripts/python.exe scripts/run_server.py
cd web && npm install && npm run dev
```

## 技术栈

Python 3.12 · FastAPI · LangGraph · Qdrant · rank-bm25 · 智谱 GLM（OpenAI 兼容接口） · uv · Docker

## 项目结构

```
app/
├── core/    # 配置、LLM 客户端
├── rag/     # 文档解析、切分、索引、检索、生成
├── agent/   # LangGraph 路由与工具
├── memory/  # 短期压缩 + 长期画像
└── api/     # FastAPI 路由 + SSE 流式
data/
├── corpus/    # 知识库语料（Markdown）
├── nutrition/ # 食物营养数据（CSV）
└── eval/      # 评测集
scripts/       # 冒烟测试、建索引等脚本
```

## 开发路线

- [ ] 阶段① RAG 底座：语料与评测集 → 混合检索 + rerank → 对比实验
- [ ] 阶段② Agent 层：意图路由 + 工具循环 + 记忆
- [ ] 阶段③ 工程化：FastAPI + SSE + LangFuse + Docker 部署
- [ ] 阶段④ 亮点拉升：LoRA 微调对比 + badcase 分析报告
