"""本地 MCP Client 调试脚本。

这个脚本会启动当前项目的 MCP Server，然后调用一个低成本工具
`evaluate_recent_runs` 验证 MCP 通信是否正常。

注意：
- 它不会直接调用 DeepSeek。
- 它会读取已有 SQLite/trace 数据来生成评估报告。
- 路径从当前文件位置推导，不写死本机绝对路径。
"""

# sys.executable 表示当前 Python 解释器路径，避免写死 .venv 绝对路径。
import sys

# Path 用来定位当前项目根目录。
from pathlib import Path

# anyio 用来运行异步 main()。
import anyio

# ClientSession 是 MCP 客户端会话对象。
from mcp.client.session import ClientSession

# stdio_client 会通过标准输入/输出和本地 MCP Server 通信。
from mcp.client.stdio import StdioServerParameters, stdio_client


PROJECT_ROOT = Path(__file__).resolve().parent


async def main() -> None:
    """启动本地 MCP Server，并调用 evaluate_recent_runs 做连通性测试。"""

    # 这里模拟一个 MCP 客户端，启动当前项目的 MCP Server。
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            str(PROJECT_ROOT / "catch_ai.py"),
            "--mcp",
        ],
        cwd=str(PROJECT_ROOT),
    )

    # stdio_client 负责启动子进程，并返回读写流。
    async with stdio_client(params) as (read, write):
        # ClientSession 负责 MCP initialize、list_tools、call_tool 等协议操作。
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


# anyio.run 接收异步函数对象，负责创建事件循环并运行。
anyio.run(main)
