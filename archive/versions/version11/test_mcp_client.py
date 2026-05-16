import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def main():
    # 这里模拟一个 MCP 客户端，启动你的 MCP Server
    params = StdioServerParameters(
        command=r"C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe",
        args=[
            r"C:\Users\18352\Desktop\agent\version11\catch_ai.py",
            "--mcp",
        ],
        cwd=r"C:\Users\18352\Desktop\agent\version11",
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            # 1. 初始化 MCP 会话
            await session.initialize()

            # 2. 查看 server 暴露了哪些工具
            tools = await session.list_tools()
            print("可用工具：")
            for tool in tools.tools:
                print("-", tool.name)

            # 3. 调用一个低成本工具，不会调用 DeepSeek
            result = await session.call_tool(
                "evaluate_recent_runs",
                {"limit": 3},
            )

            print("\n调用 evaluate_recent_runs 的结果：")
            print(result.content[0].text)


anyio.run(main)
