# FitPilot 可观测指标（LangFuse）

- 统计窗口：近 1 天（截至 2026-10-31 10:55）
- 观测总数：5000

## 每轮对话（chat_turn）

- 轮数：8
- 平均延迟：10.13s
- P50：5.40s | P95：41.48s

## Token 用量（llm_chat 合计）

- 输入 0 tok / 输出 0 tok / 每轮平均 0 tok

（注：v2 列表接口不回传 usage 字段，token 成本请在 LangFuse 控制台 Dashboard 查看）

## 各环节平均耗时

| 环节 | 次数 | 平均 | P95 |
|---|---|---|---|
| classify_intent | 62 | 1.12s | 2.21s |
| hybrid_retrieve | 1372 | 2.30s | 11.16s |
| rag_answer | 1583 | 5.65s | 12.27s |
| tool: | 46 | 0.00s | 0.02s |
