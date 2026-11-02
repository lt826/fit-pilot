"""FitPilot MCP Server：把 Agent 的 6 个工具暴露为标准 MCP 服务（stdio 传输）。

设计决策：
- 工具层与 Agent 解耦——FitPilot 内部的 function calling 循环只是这套工具的
  消费者之一；暴露成 MCP 后，Claude Desktop / Cursor / Cherry Studio 等
  任何 MCP 客户端都能复用同一个健身数据库与搜索能力
- 与手写 FC 循环构成"私有协议 vs 标准协议"的完整对比：FC 直连快、零依赖；
  MCP 走 JSON-RPC 多一层进程通信，换来的是生态互操作
- 工具实现完全复用 app/agent/tools.py（含"错误转可读字符串"的容错约定），
  本文件只做协议包装，不含业务逻辑

启动：python app/mcp_server.py（任意 cwd 均可，路径已在文件内自举）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.mcpserver import MCPServer

from app.agent import tools as t

mcp = MCPServer("fitpilot-tools")


@mcp.tool()
def log_training(exercise: str, sets: int, reps: int, weight_kg: float = 0,
                 date: str | None = None, body_part: str | None = None) -> str:
    """记录一条训练日志。用户提到完成了某个动作（含重量/组数/次数）时调用。

    Args:
        exercise: 动作名，如 深蹲、卧推
        sets: 组数
        reps: 每组次数
        weight_kg: 单次重量（公斤），自重动作填 0
        date: 日期 YYYY-MM-DD，'今天'不用传，默认今天
        body_part: 部位：胸/背/腿/肩/手臂/核心/全身。不传则自动推断
    """
    return t.log_training(exercise, sets, reps, weight_kg, date, body_part)


@mcp.tool()
def query_training(days: int = 30, body_part: str | None = None) -> str:
    """查询用户近 N 天的训练记录与按部位汇总（次数、总容量）。
    用户问'这周/这个月练了几次腿''最近练了什么'时调用。

    Args:
        days: 回溯天数，默认 30
        body_part: 可选，只看某部位
    """
    return t.query_training(days, body_part)


@mcp.tool()
def log_body_metric(weight_kg: float, date: str | None = None,
                    waist_cm: float | None = None) -> str:
    """记录身体指标：晨起体重（可含腰围）。用户说'记录体重xx公斤'时调用。

    Args:
        weight_kg: 体重（公斤）
        date: 日期 YYYY-MM-DD，默认今天
        waist_cm: 腰围（厘米），可选
    """
    return t.log_body_metric(weight_kg, date, waist_cm)


@mcp.tool()
def query_body_metrics(days: int = 90) -> str:
    """查询近 N 天体重记录及变化趋势。

    Args:
        days: 回溯天数，默认 90
    """
    return t.query_body_metrics(days)


@mcp.tool()
def query_nutrition(food_name: str) -> str:
    """查询食物营养成分（含每100克数值、常见份量估算与整份营养）。
    用户按'个/碗/块'提问时优先使用结果里的【常见份量估算】或【整份营养】。

    Args:
        food_name: 食物名称
    """
    return t.query_nutrition(food_name)


@mcp.tool()
def search_web(query: str, max_results: int = 5) -> str:
    """联网搜索最新资讯（搜狗源）。仅当问题与健身/营养/训练相关、且明显依赖
    时效性信息（如'最新''今年''最近流行'）而调用方知识库无法覆盖时使用。
    结果含 notice：回答时必须说明信息来自网络检索并附来源链接。

    Args:
        query: 搜索关键词，加上年份等时效词效果更好
        max_results: 返回条数，默认 5
    """
    return t.search_web(query, max_results)


if __name__ == "__main__":
    mcp.run()  # 默认 stdio 传输：MCP 客户端以子进程方式拉起本文件即可
