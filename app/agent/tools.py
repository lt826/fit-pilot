"""Agent 工具层：训练记录 / 体重 / 食物营养查询，供 function calling 调用。

结构约定：
- TOOLS_SPEC 是 OpenAI function calling 格式的工具声明（直接传给 chat 接口）
- EXECUTORS 是 工具名 → 执行函数 的注册表
- 每个执行函数返回"给模型看的字符串或 JSON"，异常不上抛，
  而是返回错误描述让模型自己修正参数重试（这是工具循环容错的关键）
"""

import csv
import json
import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from app.db.database import get_conn, now_str

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FOODS_CSV = PROJECT_ROOT / "data" / "nutrition" / "foods.csv"

# 动作名 → 部位的关键词推断表；与语料中"推拉腿"分化的归类保持一致（硬拉归拉类=背）
_PART_KEYWORDS = {
    "背": ["划船", "引体", "下拉", "硬拉", "飞鸟划"],
    "胸": ["卧推", "俯卧撑", "飞鸟", "夹胸", "双杠"],
    "腿": ["深蹲", "箭步蹲", "腿举", "腿屈伸", "腿弯举", "臀桥", "髋", "提踵", "分腿蹲"],
    "肩": ["肩推", "推举", "侧平举", "前平举", "阿诺德", "俯身飞鸟"],
    "手臂": ["弯举", "臂屈伸", "三头", "二头"],
    "核心": ["平板", "卷腹", "举腿", "转体", "鸟狗"],
}


def infer_body_part(exercise: str) -> str:
    for part, keywords in _PART_KEYWORDS.items():
        if any(k in exercise for k in keywords):
            return part
    return "全身"


def _norm_date(d: str | None) -> str:
    """日期参数规范化：空 → 今天；非法 → 抛 ValueError 给上层转成模型可读错误。"""
    if not d:
        return datetime.now().strftime("%Y-%m-%d")
    return datetime.strptime(d, "%Y-%m-%d").strftime("%Y-%m-%d")


# ---------------- 工具执行函数 ----------------

def log_training(exercise: str, sets: int, reps: int, weight_kg: float = 0,
                 date: str | None = None, body_part: str | None = None) -> str:
    log_date = _norm_date(date)
    part = body_part or infer_body_part(exercise)
    volume = round(float(weight_kg) * int(sets) * int(reps), 1)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO training_logs (log_date, body_part, exercise, weight_kg,"
            " sets, reps, volume_kg, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (log_date, part, exercise, float(weight_kg), int(sets), int(reps), volume, now_str()),
        )
        rid = cur.lastrowid
    return json.dumps(
        {"status": "ok", "id": rid, "date": log_date, "body_part": part,
         "exercise": exercise, "volume_kg": volume},
        ensure_ascii=False,
    )


def query_training(days: int = 30, body_part: str | None = None) -> str:
    since = (datetime.now() - timedelta(days=int(days))).strftime("%Y-%m-%d")
    sql = ("SELECT log_date, body_part, exercise, weight_kg, sets, reps, volume_kg"
           " FROM training_logs WHERE log_date >= ? AND user_id=1")
    params: list = [since]
    if body_part:
        sql += " AND body_part = ?"
        params.append(body_part)
    sql += " ORDER BY log_date DESC"
    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    # 汇总信息帮模型少算术：按部位统计次数与总容量
    by_part: dict[str, dict] = {}
    for r in rows:
        p = r["body_part"]
        agg = by_part.setdefault(p, {"次数": 0, "总容量kg": 0.0})
        agg["次数"] += 1
        agg["总容量kg"] = round(agg["总容量kg"] + r["volume_kg"], 1)
    return json.dumps(
        {"window": f"最近{days}天(自{since})", "filter": body_part or "全部部位",
         "summary": by_part, "count": len(rows), "records": rows},
        ensure_ascii=False,
    )


def log_body_metric(weight_kg: float, date: str | None = None, waist_cm: float | None = None) -> str:
    log_date = _norm_date(date)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO body_metrics (log_date, weight_kg, waist_cm, created_at)"
            " VALUES (?,?,?,?)",
            (log_date, float(weight_kg), waist_cm, now_str()),
        )
        rid = cur.lastrowid
    return json.dumps({"status": "ok", "id": rid, "date": log_date, "weight_kg": weight_kg},
                      ensure_ascii=False)


def query_body_metrics(days: int = 90) -> str:
    since = (datetime.now() - timedelta(days=int(days))).strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT log_date, weight_kg, waist_cm FROM body_metrics"
            " WHERE log_date >= ? AND user_id=1 ORDER BY log_date DESC", (since,)
        ).fetchall()]
    trend = ""
    if len(rows) >= 2:
        delta = rows[-1]["weight_kg"] - rows[0]["weight_kg"]  # 旧→新
        trend = f"区间变化 {delta:+.1f}kg"
    return json.dumps({"window": f"最近{days}天", "trend": trend, "records": rows},
                      ensure_ascii=False)


@lru_cache
def _load_foods() -> list[dict]:
    with FOODS_CSV.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# 从"1个约50-60克"这类自由文本里提取克数（取区间中点）
_PORTION_RE = re.compile(r"约?(\d+)(?:-(\d+))?\s*(克|毫升)")


def _portion_estimate(food: dict) -> dict | None:
    """把常见份量换算成具体营养值。

    教训（本步 badcase）：只给模型"每100克数值+份量文本"，它会忽略份量
    直接按100克计算（两个鸡蛋算出25g蛋白质，实际约14g）。
    算术是确定性问题，应该在工具层算好，模型只负责组织语言。
    """
    m = _PORTION_RE.search(food.get("common_portion(常见份量)") or "")
    if not m:
        return None
    lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
    grams = (lo + hi) / 2
    factor = grams / 100
    return {
        "份量说明": f"{food['common_portion(常见份量)']}≈{grams:.0f}克",
        "热量kcal": round(float(food["calories_kcal(热量_千卡)"]) * factor),
        "蛋白质g": round(float(food["protein_g(蛋白质_克)"]) * factor, 1),
        "脂肪g": round(float(food["fat_g(脂肪_克)"]) * factor, 1),
        "碳水g": round(float(food["carbs_g(碳水_克)"]) * factor, 1),
    }


def query_nutrition(food_name: str) -> str:
    """食物营养查询：双向子串模糊匹配，最多返回 3 个候选，让模型自己挑最贴切的。"""
    foods = _load_foods()
    name = food_name.strip()
    exact = [f for f in foods if f["food_name(食物名)"] == name]
    fuzzy = [f for f in foods if name in f["food_name(食物名)"] or f["food_name(食物名)"] in name]
    hits = (exact or fuzzy or [])[:3]
    if not hits:
        return json.dumps({"status": "not_found",
                           "message": f"营养库中没有找到「{food_name}」，请告知用户该食物暂未收录"},
                          ensure_ascii=False)
    items = []
    for f in hits:
        unit = f["unit(单位)"]
        values = {"热量kcal": f["calories_kcal(热量_千卡)"],
                  "蛋白质g": f["protein_g(蛋白质_克)"],
                  "脂肪g": f["fat_g(脂肪_克)"],
                  "碳水g": f["carbs_g(碳水_克)"]}
        if unit == "每100克":
            items.append({"food": f["food_name(食物名)"], "每100克": values,
                          # 优先引用这份估算；用户给出具体克数时再按每100克换算
                          "常见份量估算": _portion_estimate(f)})
        else:
            # 复合菜品（牛肉面/蛋炒饭等）数值基准是整份而非100克，
            # 直接标注真实基准，避免模型误说"每100克650千卡"
            items.append({"food": f["food_name(食物名)"],
                          f"整份营养（基准：{unit}）": values})
    return json.dumps(items, ensure_ascii=False)


# ---------------- 联网搜索（分级知识源的兜底层） ----------------

# 搜索源选型是实测出来的：SearXNG 的主流引擎（google/ddg/brave）在国内全部超时；
# cn.bing 对无 Cookie 的程序化请求返回劣化结果池（热榜/百科，与查询无关）；
# 百度 302 反爬。搜狗是唯一对普通 HTTP 请求返回干净可解析结果页的源。
_SOGOU_BLOCK_RE = re.compile(r'<div class="vrwrap"|<div class="rb"')
_SOGOU_TITLE_RE = re.compile(
    r'<h3 class="vr-title[^"]*"[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_SCRIPT_STYLE_RE = re.compile(r"<script.*?</script>|<style.*?</style>", re.S)
_COMMENT_RE = re.compile(r"<!--.*?-->")
_TAG_RE = re.compile(r"<[^>]+>")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _clean_text(fragment: str) -> str:
    """HTML 片段 → 纯文本：去脚本/注释/标签，还原实体，折叠空白。"""
    import html as _html
    txt = _COMMENT_RE.sub("", _SCRIPT_STYLE_RE.sub("", fragment))
    return re.sub(r"\s+", " ", _TAG_RE.sub("", _html.unescape(txt))).strip()


def _resolve_sogou_link(href: str) -> str:
    """搜狗部分结果是 /link?url= 跳转链，HEAD 跟随一次拿真实地址；失败则原样返回。"""
    import httpx

    url = "https://www.sogou.com" + href if href.startswith("/") else href
    if "/link?" not in url:
        return url
    try:
        resp = httpx.head(url, timeout=3, follow_redirects=True,
                          headers={"User-Agent": _UA})
        return str(resp.url)
    except Exception:  # noqa: BLE001 —— 解析失败时跳转链本身也能用
        return url


def search_web(query: str, max_results: int = 5) -> str:
    """联网搜索（搜狗结果页）：返回标题/链接/摘要，由模型组织成带来源的回答。

    设计约束：本地知识库是第一优先级，本工具只兜底健身相关的时效性问题；
    结果里显式携带 notice 提醒模型向用户标注"信息来自网络"。
    网络故障返回可读错误（与其他工具的容错约定一致），不抛异常。
    """
    import httpx

    try:
        resp = httpx.get(
            "https://www.sogou.com/web",
            params={"query": query},
            timeout=10.0,
            headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"},
            follow_redirects=True,
        )
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001 —— 网络故障转模型可读信息
        return f"[搜索服务不可用] {e.__class__.__name__}: {e}；请告知用户暂时无法联网，并基于已有知识回答"

    items = []
    for block in _SOGOU_BLOCK_RE.split(resp.text):
        m = _SOGOU_TITLE_RE.search(block)
        if not m:
            continue
        title = _clean_text(m.group(2))
        if not title:
            continue
        # 摘要 = 容器全文去掉标题后的开头部分（摘要节点 class 不稳定，整容器更皮实）
        body = _clean_text(block)
        snippet = body.split(title, 1)[-1][:200] if title in body else body[:200]
        items.append({"title": title,
                      "url": _resolve_sogou_link(m.group(1)),
                      "snippet": snippet})
        if len(items) >= max_results:
            break
    if not items:
        return json.dumps(
            {"status": "not_found", "message": f"联网未搜到与「{query}」相关的结果"},
            ensure_ascii=False)
    return json.dumps({
        "notice": "以下结果来自互联网检索而非本地知识库，回答时必须向用户说明并附来源链接",
        "results": items,
    }, ensure_ascii=False)


# ---------------- 工具声明（OpenAI function calling 格式）----------------

TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "log_training",
            "description": "记录一条训练日志。用户提到完成了某个动作（含重量/组数/次数）时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "exercise": {"type": "string", "description": "动作名，如 深蹲、卧推"},
                    "sets": {"type": "integer", "description": "组数"},
                    "reps": {"type": "integer", "description": "每组次数"},
                    "weight_kg": {"type": "number", "description": "单次重量（公斤），自重动作填 0"},
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD，'今天'不用传，默认今天"},
                    "body_part": {"type": "string",
                                  "description": "部位：胸/背/腿/肩/手臂/核心/全身。不传则自动推断"},
                },
                "required": ["exercise", "sets", "reps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_training",
            "description": "查询用户近 N 天的训练记录与按部位汇总（次数、总容量）。"
                           "用户问'这周/这个月练了几次腿''最近练了什么'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "回溯天数，默认 30"},
                    "body_part": {"type": "string", "description": "可选，只看某部位"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_body_metric",
            "description": "记录身体指标：晨起体重（可含腰围）。用户说'记录体重xx公斤'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "weight_kg": {"type": "number", "description": "体重（公斤）"},
                    "waist_cm": {"type": "number", "description": "腰围（厘米），可选"},
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"},
                },
                "required": ["weight_kg"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_body_metrics",
            "description": "查询近 N 天体重记录及变化趋势。",
            "parameters": {
                "type": "object",
                "properties": {"days": {"type": "integer", "description": "回溯天数，默认 90"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_nutrition",
            "description": "查询食物营养成分，用户问到食物热量/蛋白质就调用，"
                           "无需向用户确认基准——结果同时包含每100克数值和常见份量估算。"
                           "用户按'个/碗/块'提问时优先使用【常见份量估算】或【整份营养】；"
                           "用户给出具体克数时才按每100克数值换算。",
            "parameters": {
                "type": "object",
                "properties": {"food_name": {"type": "string", "description": "食物名称"}},
                "required": ["food_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "联网搜索最新资讯。仅当满足两个条件才调用：①问题与健身/营养/训练相关，"
                           "②明显依赖时效性信息（如'最新''今年''最近流行'）且本地知识库无法覆盖。"
                           "普通健身知识问题禁止调用（应走知识问答）；与健身无关的问题也不调用（直接说明无法帮助）。"
                           "回答时必须向用户说明信息来自网络检索并附来源链接。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词，加上年份等时效词效果更好"},
                    "max_results": {"type": "integer", "description": "返回条数，默认 5"},
                },
                "required": ["query"],
            },
        },
    },
]

EXECUTORS = {
    "log_training": log_training,
    "query_training": query_training,
    "log_body_metric": log_body_metric,
    "query_body_metrics": query_body_metrics,
    "query_nutrition": query_nutrition,
    "search_web": search_web,
}


def execute_tool(name: str, arguments_json: str) -> str:
    """统一调度入口：参数解析失败/执行异常都返回描述性错误字符串（不抛异常），
    模型读到错误会修正参数重试——这是工具循环容错的核心机制。
    每次调用记录为 LangFuse tool 观测（入参/结果/耗时）。"""
    import json as _json

    from app.core.observability import obs

    @obs(name=f"tool:{name}", as_type="tool")
    def _run(name: str = name, arguments_json: str = arguments_json) -> str:
        try:
            args = _json.loads(arguments_json or "{}")
        except _json.JSONDecodeError as e:
            return f"[参数解析失败] {e}；请检查参数是合法 JSON 后重试"
        fn = EXECUTORS.get(name)
        if fn is None:
            return f"[未知工具] {name}；可用工具：{list(EXECUTORS)}"
        try:
            return fn(**args)
        except TypeError as e:
            # 常见于参数名拼错 / 缺必填参数 / 多余参数
            return f"[参数错误] {e}；请对照工具定义修正参数后重试"
        except Exception as e:  # noqa: BLE001 —— 其余异常也转成模型可读信息
            return f"[工具执行出错] {e.__class__.__name__}: {e}"

    return _run(name, arguments_json)
