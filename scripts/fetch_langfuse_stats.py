"""第7步③：从 LangFuse 提取成本/延迟指标。

拉取近 N 天 v2 observations，按观测名聚合：
- chat_turn（每轮对话根 trace）：轮数 / 平均与 P50/P95 延迟
- llm_chat：token 用量合计与均值（成本口径）、平均延迟
- 各环节（路由/检索/工具）平均耗时占比

输出：控制台 + docs/observability-stats.md
用法: .venv/Scripts/python.exe scripts/fetch_langfuse_stats.py [天数，默认7]
"""

import base64
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_MD = PROJECT_ROOT / "docs" / "observability-stats.md"
API = "https://cloud.langfuse.com/api/public/v2/observations"


def fetch_all(days: int) -> list[dict]:
    s = get_settings()
    auth = base64.b64encode(
        f"{s.langfuse_public_key}:{s.langfuse_secret_key}".encode()
    ).decode()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    until = datetime.now(timezone.utc) + timedelta(minutes=5)
    fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    # v2 接口用 cursor 分页（meta.cursor 指向下一页，None 表示到底）
    out, cursor, guard = [], None, 0
    while guard < 50:
        guard += 1
        url = (f"{API}?fromStartTime={fmt(since)}&toStartTime={fmt(until)}&limit=100"
               + (f"&cursor={cursor}" if cursor else ""))
        req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
        # LangFuse 免费档 API 限流较紧：429 时退避重试，翻页间主动节流
        data = None
        for attempt in range(4):
            try:
                data = json.load(urllib.request.urlopen(req, timeout=30))
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 3:
                    time.sleep(3 + 3 * attempt)
                    continue
                raise
        time.sleep(1)
        if data is None:
            break
        batch = data.get("data", [])
        out.extend(batch)
        cursor = (data.get("meta") or {}).get("cursor")
        if not cursor or not batch:
            break
    return out


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(len(ordered) * p), len(ordered) - 1)
    return ordered[idx]


def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    obs = fetch_all(days)
    print(f"近{days}天观测 {len(obs)} 条")

    def latencies(name_prefix: str) -> list[float]:
        return [o["latency"] for o in obs
                if o.get("name", "").startswith(name_prefix) and o.get("latency")]

    def tokens(o: dict) -> tuple[int, int]:
        """用量双通道：usageDetails 优先，metadata 兜底（列表接口不回传前者）。"""
        u = o.get("usageDetails") or {}
        md = o.get("metadata") or {}
        if isinstance(md, str):
            try:
                md = json.loads(md)
            except (json.JSONDecodeError, TypeError):
                md = {}
        p = int(u.get("input") or md.get("prompt_tokens") or 0)
        q = int(u.get("output") or md.get("completion_tokens") or 0)
        return p, q

    turns = latencies("chat_turn")
    gens = [o for o in obs if o.get("name") == "llm_chat"]
    tokens_in = sum(tokens(o)[0] for o in gens)
    tokens_out = sum(tokens(o)[1] for o in gens)
    token_note = "" if (tokens_in or tokens_out) else "\n（注：v2 列表接口不回传 usage 字段，token 成本请在 LangFuse 控制台 Dashboard 查看）"

    stages = {}
    for name in ("classify_intent", "hybrid_retrieve", "rag_answer", "tool:"):
        vals = latencies(name)
        if vals:
            stages[name] = vals

    n_turn = len(turns)
    lines = [
        "# FitPilot 可观测指标（LangFuse）",
        "",
        f"- 统计窗口：近 {days} 天（截至 {datetime.now():%Y-%m-%d %H:%M}）",
        f"- 观测总数：{len(obs)}",
        "",
        "## 每轮对话（chat_turn）",
        "",
        f"- 轮数：{n_turn}",
        f"- 平均延迟：{sum(turns)/n_turn:.2f}s" if n_turn else "- 无数据",
        f"- P50：{percentile(turns, 0.5):.2f}s | P95：{percentile(turns, 0.95):.2f}s" if n_turn else "",
        "",
        "## Token 用量（llm_chat 合计）",
        "",
        f"- 输入 {tokens_in} tok / 输出 {tokens_out} tok"
        + (f" / 每轮平均 {(tokens_in + tokens_out) / max(n_turn, 1):.0f} tok" if n_turn else ""),
        token_note,
        "",
        "## 各环节平均耗时",
        "",
        "| 环节 | 次数 | 平均 | P95 |", "|---|---|---|---|",
    ]
    for name, vals in stages.items():
        lines.append(f"| {name} | {len(vals)} | {sum(vals)/len(vals):.2f}s | {percentile(vals, 0.95):.2f}s |")

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n已写入 {OUT_MD}")


if __name__ == "__main__":
    main()
