"""FastAPI 服务：SSE 流式对话 + 用户画像读写。

SSE 事件协议（前后端契约）：
  session   {session_id}                       连接建立，返回会话id
  route     {route}                            意图路由结果(chat/knowledge/task/mixed)
  tool_call {tool, args, result}               一次工具调用及其结果(截断)
  citation  {sources: [...]}                   知识引用出处
  delta     {text}                             答案增量(打字机)
  notice    {text}                             附带信息(如画像更新)
  error     {message}                          执行异常
  done      {}                                 本轮结束

线程模型：graph.invoke 是阻塞调用，放到工作线程跑，
事件经 queue 传给 SSE 生成器——否则首事件要等整轮结束才发出。
"""

import json
import queue
import threading
import uuid
from contextlib import asynccontextmanager, contextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent.graph import FitnessCoach
from app.core.observability import finish_turn, shutdown_client, turn_trace
from app.db.database import get_conn, init_db, now_str

# 服务启动即建表：不能依赖某条链路（如工具层）顺带初始化，
# 否则纯聊天/纯检索流程会因缺表而 500
init_db()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    shutdown_client()  # 退出前冲刷 LangFuse 缓冲，保住最后几条 trace


app = FastAPI(title="FitPilot API", version="0.1.0", lifespan=lifespan)

# 开发期直连(5173/5174)与 Vite 代理并存；生产由同源静态托管，无需 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                   "http://localhost:5174", "http://127.0.0.1:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 会话表：session_id → Coach 实例（含各自的短期记忆）。
# 单进程内存方案；多 worker 部署时需换 Redis 等外部存储（README 已注明）
SESSIONS: dict[str, FitnessCoach] = {}


def _get_coach(session_id: str | None) -> tuple[str, FitnessCoach]:
    if session_id and session_id in SESSIONS:
        return session_id, SESSIONS[session_id]
    new_id = session_id or uuid.uuid4().hex[:12]
    coach = FitnessCoach()
    # 服务重启后内存缓存丢失：若该会话在库里有历史，回灌为短期记忆
    # （上下文续接可用；压缩摘要不持久化，超限后会重新压缩，代价可接受）
    if session_id:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM chat_messages WHERE session_id=? ORDER BY id",
                (session_id,),
            ).fetchall()
        for r in rows:
            coach.session.append(r["role"], r["content"])
    SESSIONS[new_id] = coach
    return new_id, coach


def _persist_turn(session_id: str, user_text: str, result) -> None:
    """一轮对话落库：两条消息 + 自动标题 + 会话时间戳。"""
    with get_conn() as conn:
        now = now_str()
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content, route, created_at)"
            " VALUES (?,?,?,?,?)",
            (session_id, "user", user_text, None, now),
        )
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content, route, created_at)"
            " VALUES (?,?,?,?,?)",
            (session_id, "assistant", result.answer, result.route, now),
        )
        row = conn.execute(
            "SELECT title FROM chat_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if row is None:  # 未经 /api/sessions 创建的旧式会话，补一条会话行
            conn.execute(
                "INSERT INTO chat_sessions (id, title, created_at, updated_at)"
                " VALUES (?,?,?,?)",
                (session_id, user_text[:24], now, now),
            )
        elif not row["title"]:  # 首轮：以首条用户消息做自动标题
            conn.execute(
                "UPDATE chat_sessions SET title=?, updated_at=? WHERE id=?",
                (user_text[:24], now, session_id),
            )
        else:
            conn.execute(
                "UPDATE chat_sessions SET updated_at=? WHERE id=?", (now, session_id)
            )


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None


@app.post("/api/chat/stream")
def chat_stream(body: ChatIn):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")
    session_id, coach = _get_coach(body.session_id)
    events: queue.Queue = queue.Queue()

    def worker() -> None:
        try:
            # 根 trace 必须开在线程内：OTel 上下文不跨线程，
            # 线程内开后，路由/检索/LLM/工具的嵌套观测自动挂到同一棵树
            with turn_trace(session_id, body.message) as root:
                result = coach.stream_chat(body.message, lambda e, d: events.put((e, d)))
                finish_turn(root, result.answer, result.route)
            _persist_turn(session_id, body.message, result)
        except Exception as exc:  # noqa: BLE001 —— SSE 必须把异常传到前端而不是断流
            events.put(("error", {"message": f"{exc.__class__.__name__}: {exc}"}))
        finally:
            events.put(None)  # 结束哨兵

    threading.Thread(target=worker, daemon=True).start()

    def gen():
        yield f"event: session\ndata: {json.dumps({'session_id': session_id})}\n\n"
        while True:
            item = events.get()
            if item is None:
                break
            event, data = item
            yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


class ProfileIn(BaseModel):
    goal: str | None = None
    training_years: float | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    injuries: str | None = None
    weekly_days: int | None = None


@app.get("/api/profile")
def get_profile():
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone()
    return dict(row) if row else {}


@app.put("/api/profile")
def update_profile(p: ProfileIn):
    updates = {k: v for k, v in p.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="没有可更新字段")
    sets = ", ".join(f"{k}=?" for k in updates)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE user_profile SET {sets}, updated_at=? WHERE id=1",
            (*updates.values(), now_str()),
        )
    return {"status": "ok", "updated": updates}


# ---------------- 会话历史 ----------------

@app.post("/api/sessions")
def create_session():
    """显式新建会话（前端进入页面/点新建时调用）。"""
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = FitnessCoach()
    now = now_str()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO chat_sessions (id, title, created_at, updated_at) VALUES (?,?,?,?)",
            (sid, "", now, now),
        )
    return {"session_id": sid}


@app.get("/api/sessions")
def list_sessions():
    """历史会话列表：只列有消息的会话（避免刷新产生的空会话堆积），按最近更新排序。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT s.id, s.title, s.updated_at, COUNT(m.id) AS msg_n"
            " FROM chat_sessions s JOIN chat_messages m ON m.session_id = s.id"
            " GROUP BY s.id ORDER BY s.updated_at DESC LIMIT 50"
        ).fetchall()
    return [
        {"session_id": r["id"], "title": r["title"] or "新对话",
         "updated_at": r["updated_at"], "messages": r["msg_n"]}
        for r in rows
    ]


@app.get("/api/sessions/{sid}/messages")
def get_session_messages(sid: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content, route FROM chat_messages WHERE session_id=? ORDER BY id",
            (sid,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/sessions/{sid}")
def delete_session(sid: str):
    SESSIONS.pop(sid, None)
    with get_conn() as conn:
        conn.execute("DELETE FROM chat_messages WHERE session_id=?", (sid,))
        conn.execute("DELETE FROM chat_sessions WHERE id=?", (sid,))
    return {"status": "ok"}


# ---------------- 数据管理 ----------------
# 刻意不做成 Agent 工具：对话里一句"清空吧"就真删库太危险，
# 不可逆操作必须走 UI（实测模型会虚构"已清空"的执行结果）。
# 粒度分层：单条删（本处）/ 全清（清空接口，仅兜底）——前端主力是勾选删除面板

@app.get("/api/training-logs")
def list_training_logs():
    """训练记录列表（删除面板用），新日期在前。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM training_logs ORDER BY log_date DESC, id DESC LIMIT 500"
        ).fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/training-logs/{lid}")
def delete_training_log(lid: int):
    with get_conn() as conn:
        n = conn.execute("DELETE FROM training_logs WHERE id=?", (lid,)).rowcount
    if not n:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"status": "ok"}


@app.get("/api/body-metrics")
def list_body_metrics():
    """体测记录列表（删除面板用）。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM body_metrics ORDER BY log_date DESC, id DESC LIMIT 500"
        ).fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/body-metrics/{mid}")
def delete_body_metric(mid: int):
    with get_conn() as conn:
        n = conn.execute("DELETE FROM body_metrics WHERE id=?", (mid,)).rowcount
    if not n:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"status": "ok"}


@app.delete("/api/training-logs")
def clear_training_logs():
    """清空全部训练记录（兜底接口，UI 主力是单条勾选删除）。"""
    with get_conn() as conn:
        n = conn.execute("DELETE FROM training_logs").rowcount
    return {"status": "ok", "deleted": n}


@app.delete("/api/body-metrics")
def clear_body_metrics():
    """清空全部体测记录（兜底接口）。"""
    with get_conn() as conn:
        n = conn.execute("DELETE FROM body_metrics").rowcount
    return {"status": "ok", "deleted": n}


# ---------------- 生产模式：同源托管前端构建产物 ----------------
# 开发期前后端分端口（5174/8000，Vite 代理转发 /api）；生产把 web/dist 挂到根路径，
# 一个 uvicorn 进程同时服务页面和 API，同源部署天然无 CORS 问题。
# 必须放在所有路由定义之后：挂载在 "/" 的 StaticFiles 会吞掉后续未匹配的路径。
from pathlib import Path  # noqa: E402

from fastapi.staticfiles import StaticFiles  # noqa: E402

_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
else:
    # dist 不存在不报错：纯 API 模式照常跑（开发/评测脚本场景）
    print("[提示] 未找到 web/dist，当前为纯 API 模式（前端请用 npm run dev）")
