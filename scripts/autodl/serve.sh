#!/bin/bash
# 非交互 shell 无 conda PATH：python/ninja/nvcc 全找不到，统一导出（含 flashinfer JIT 依赖）
export PATH=/root/miniconda3/bin:/usr/local/cuda/bin:$PATH
# vLLM 起服务：同一进程挂载基座 + LoRA 适配器两个"模型名"，
# 三组对比里 A组(直接答)用基座名、B/C组用 LoRA 名，保证两组推理参数完全一致。
# 本机通过 SSH 隧道访问：ssh -N -L 18800:localhost:8000（AutoDL 只放行 SSH 端口）
set -ex
python -m vllm.entrypoints.openai.api_server \
  --model /root/autodl-tmp/models/Qwen2.5-3B-Instruct \
  --served-model-name qwen-base \
  --enable-lora \
  --lora-modules fitpilot-lora=/root/autodl-tmp/saves/qwen2.5-3b-lora \
  --max-lora-rank 16 \
  --max-model-len 4096 \
  --dtype bfloat16 \
  --gpu-memory-utilization 0.90 \
  --port 8000
