"""长期记忆：用户画像（user_profile 表）的注入与增量抽取。

画像即个性化回答的依据："我腰有旧伤"之后，所有计划建议都应绕开大重量硬拉。
抽取用触发词做前置过滤（省一次 LLM 调用），命中才让 LLM 结构化抽取。
"""

from app.core.config import get_settings
from app.core.llm import get_llm_client
from app.db.database import get_conn, now_str

# 出现这些词才触发画像抽取（绝大多数消息不含个人信息，没必要每轮都调 LLM）
TRIGGER_WORDS = ("目标", "增肌", "减脂", "保持", "身高", "体重", "腰", "伤", "膝",
                 "几年", "新手", "老手", "每周", "初级", "中级", "高级", "想瘦", "想壮")

_EXTRACT_PROMPT = """从用户的健身相关陈述中抽取画像信息，只抽用户明确表达的字段，输出 JSON（不要 markdown 代码块）：
{"goal": "增肌/减脂/保持", "training_years": 数字, "height_cm": 数字, "weight_kg": 数字,
 "injuries": "伤病史描述", "weekly_days": 数字}
没有任何可抽取信息时输出 {}。不要猜测。"""


def load_profile() -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone()
    return dict(row) if row else {}


def profile_summary() -> str:
    """给各链路 system prompt 注入的画像摘要；空画像返回空串。"""
    p = load_profile()
    parts = []
    if p.get("goal"):
        parts.append(f"目标{p['goal']}")
    if p.get("training_years"):
        parts.append(f"训练年限约{p['training_years']}年")
    if p.get("height_cm"):
        parts.append(f"身高{p['height_cm']}cm")
    if p.get("weight_kg"):
        parts.append(f"体重{p['weight_kg']}kg")
    if p.get("injuries"):
        parts.append(f"伤病史:{p['injuries']}（建议规避相关大重量动作）")
    if p.get("weekly_days"):
        parts.append(f"每周可练{p['weekly_days']}天")
    return "；".join(parts)


def maybe_extract_and_update(user_text: str) -> dict:
    """触发词命中 → LLM 抽取 → 增量 UPDATE 非空字段。返回实际更新的字段。"""
    if not any(w in user_text for w in TRIGGER_WORDS):
        return {}
    resp = get_llm_client().chat.completions.create(
        model=get_settings().chat_model,
        temperature=0,
        messages=[{"role": "user", "content": f"{_EXTRACT_PROMPT}\n\n用户陈述：{user_text}"}],
    )
    import json

    raw = (resp.choices[0].message.content or "").strip()
    try:
        updates = {k: v for k, v in json.loads(raw).items() if v not in (None, "", [])}
    except json.JSONDecodeError:
        return {}
    if not updates:
        return {}
    # 画像字段与回答风格强相关，新值直接覆盖旧值（最新陈述优先）
    sets = ", ".join(f"{k}=?" for k in updates)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE user_profile SET {sets}, updated_at=? WHERE id=1",
            (*updates.values(), now_str()),
        )
    return updates
