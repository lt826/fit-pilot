"""MCP 端到端测试：以标准 stdio 客户端拉起 MCP server 子进程，
走完整 JSON-RPC 握手 → 列出工具 → 调用只读工具验证。

不依赖任何特定客户端（Claude Desktop 等），协议跑通即可证明 server 合规。

用法：python scripts/test_mcp_server.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

VENV_PY = Path(__file__).resolve().parents[1] / ".venv" / "Scripts" / "python.exe"
SERVER = Path(__file__).resolve().parents[1] / "app" / "mcp_server.py"


async def main() -> None:
    params = StdioServerParameters(
        command=str(VENV_PY), args=[str(SERVER)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_tools()
            names = [t.name for t in listed.tools]
            print(f"握手成功，共 {len(names)} 个工具: {names}")
            assert len(names) == 6, "工具数不对"

            for tool, args in [("query_nutrition", {"food_name": "鸡蛋"}),
                               ("query_body_metrics", {"days": 30})]:
                res = await session.call_tool(tool, args)
                text = res.content[0].text
                data = json.loads(text)
                print(f"\n调用 {tool} → {'OK' if res.is_error is not True else 'ERROR'}")
                print(json.dumps(data, ensure_ascii=False)[:200])

            print("\nMCP 端到端验证通过")


if __name__ == "__main__":
    asyncio.run(main())
