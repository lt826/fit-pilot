"""SQLite 连接与建表。

三张表：
- user_profile   用户画像（目标/训练年限/身高体重/伤病史）——第4步长期记忆的落点
- training_logs  训练日志（Agent 工具写入/查询）
- body_metrics   体重等身体指标记录

设计要点：volume_kg（组数×次数×重量）在建表层面冗余存储，
汇总统计（周训练量、月次数）直接 SUM 免运行时计算。
"""

import sqlite3
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "fitpilot.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profile (
    id             INTEGER PRIMARY KEY,   -- 单用户版固定为 1
    goal           TEXT,                  -- 增肌 / 减脂 / 保持
    training_years REAL,
    height_cm      REAL,
    weight_kg      REAL,
    injuries       TEXT,                  -- 伤病史等长期注意事项
    weekly_days    INTEGER,               -- 每周可训练天数
    created_at     TEXT,
    updated_at     TEXT
);

CREATE TABLE IF NOT EXISTS training_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL DEFAULT 1,
    log_date   TEXT    NOT NULL,          -- YYYY-MM-DD，用 TEXT 存保证字典序=时间序
    body_part  TEXT    NOT NULL,          -- 胸/背/腿/肩/手臂/核心/全身
    exercise   TEXT    NOT NULL,
    weight_kg  REAL    NOT NULL DEFAULT 0,
    sets       INTEGER NOT NULL,
    reps       INTEGER NOT NULL,
    volume_kg  REAL    NOT NULL,          -- 冗余列：sets*reps*weight_kg
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS body_metrics (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL DEFAULT 1,
    log_date   TEXT    NOT NULL,
    weight_kg  REAL    NOT NULL,
    waist_cm   REAL,
    created_at TEXT
);

-- 会话持久化：服务重启后历史对话可恢复（内存 SESSIONS 只是运行时缓存）
CREATE TABLE IF NOT EXISTS chat_sessions (
    id         TEXT PRIMARY KEY,   -- 12位hex，由服务端生成
    title      TEXT DEFAULT '',    -- 首条用户消息截断，DeepSeek式自动标题
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,      -- user / assistant
    content    TEXT NOT NULL,
    route      TEXT,               -- assistant 消息的路由标签（历史展示用）
    created_at TEXT
);
"""


def get_conn() -> sqlite3.Connection:
    """每个操作短连接：SQLite 文件库上开销可忽略，
    且避免长连接在脚本/服务混跑时持有文件锁。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 结果按列名取值，可读性优先
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        # 单用户画像行不存在则占位创建，后续 UPDATE 即可
        if conn.execute("SELECT 1 FROM user_profile WHERE id=1").fetchone() is None:
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO user_profile (id, created_at, updated_at) VALUES (1, ?, ?)",
                (now, now),
            )


def now_str() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")
