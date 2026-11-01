#!/bin/bash
# AutoDL 服务器侧安装：LLaMA-Factory + vLLM（vllm 固定 0.11.0：要求 torch==2.8.0，
# 与镜像自带 torch 2.8.0+cu128 精确匹配，避免 pip 因版本约束重装/升级 torch）
set -ex
cd /root/autodl-tmp
source /etc/network_turbo   # AutoDL 学术加速，只对 github 生效
git clone --depth 1 https://github.com/hiyouga/LLaMA-Factory.git
cd LLaMA-Factory
pip install -e .
pip install vllm==0.11.0
python -c "import llamafactory, vllm; print('LF+vLLM OK', vllm.__version__)"
