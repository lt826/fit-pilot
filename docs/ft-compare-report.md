# 微调三组对比报告（第7步④：LoRA 实验）

- 日期：2026-10-31
- 底座：Qwen2.5-3B-Instruct（同一底座，唯一变量是 LoRA 与检索增强）
- LoRA：rank 16 / alpha 32 / target all / 3 epochs，训练 3.6 分钟（RTX 4080 SUPER 32GB），
  可训练参数 29.9M（0.96%），训练数据为知识库蒸馏 SFT 集 791 条（6 种问法变体）
- 服务：vLLM 单进程双模型名（qwen-base / fitpilot-lora），推理参数完全一致
- 评测：knowledge 201 题（裁判二元判卷）+ reject 20 题（结构化标记判拒答）
- 裁判：glm-4-flash（三组同裁判同口径）。首轮曾用 glm-4.7 判 A/B 两组
  （82.8% / 70.6%），判至 C 组时账号余额耗尽、429 被静默吞掉导致整批误判，
  修复脚本后改为免费 flash 全量重判——两组裁判下 A>B 的方向性结论一致

| 组别 | 知识题正确率 | 拒答题拒答率 | 知识题误拒率 |
|---|---|---|---|
| Qwen2.5-3B 基座直接答 | 87.9% | 60.0% | 1.5% |
| LoRA 微调后直接答 | 66.2% | 10.0% | 0.0% |
| LoRA + RAG 检索增强 | **96.9%** | **100%** | 4.5% |

## 结论解读

**1. 检索增强才是正确率天花板（B→C：+30.7pct）**
LoRA 直接答 66.2% → 加上 RAG 后 96.9%。微调让模型学会口吻和部分知识，
但 3B 底座 + 791 条样本的知识内化有上限，且推理时无纠错来源；
RAG 把"回忆"变成"查证"，答案有出处、可溯源，正确率一步到顶。

**2. 单独微调反而低于基座（A vs B：-21.7pct）**
Qwen2.5-3B 预训练里见过海量中文健身内容，通用知识扎实；LoRA 在 791 条
小数据上 3 epochs 出现过拟合倾向——回答更"像教练"，但具体数字靠回忆
输出，错得比基座的泛化回答更"自信"。微调不是免费午餐。

**3. 拒答题暴露幻觉抑制的真实来源**
- 基座拒答 60%：靠通用对齐训练的边界感
- LoRA 拒答仅 10%：微调教会它"什么都要用教练口吻答"，边界感反而丢失
  ——对健身外问题（医疗诊断等）也更敢答了，幻觉风险上升
- LoRA+RAG 拒答 100%：检索闸门（top1 向量分 < 0.61 直接拒答）提供
  确定性的边界，这是微调无法替代的机制性防线

**4. 工程启示**
微调与 RAG 不是替代关系：微调塑造风格与领域先验，检索提供事实与边界。
本项目最终架构（RAG 为主 + 可选微调模型即插即用）经实验验证成立——
换模型只改 CHAT_BASE_URL / CHAT_MODEL 两个环境变量。

## 产物清单

- LoRA adapter：`models/qwen2.5-3b-fitpilot-lora/`（115MB，可挂任意 Qwen2.5-3B-Instruct 基座）
- 训练曲线：`docs/training_loss.png`（loss 2.63→1.50）
- SFT 数据：`data/sft/fitpilot_sft.jsonl`（791 条，生成脚本 `scripts/gen_sft_data.py`）
- 训练/服务配置：`scripts/autodl/qwen_lora_sft.yaml`、`scripts/autodl/serve.sh`
- 评测脚本：`scripts/eval_finetune.py`（断点续跑 / 原位重判 / 分通道裁判）
- 逐题明细：`data/eval/_ft_checkpoint.jsonl`（glm-4.7 首轮备份 `_ft_checkpoint_47backup.jsonl`）
