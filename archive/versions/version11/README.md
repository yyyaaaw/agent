# 本地 AI 热点日报 Agent - Version 11

Version 11 基于 Version 10 继续优化，重点是：

> 从手写 MCP 协议升级为 MCP SDK 版本

Version 10 里我们自己处理 JSON-RPC、`tools/list` 和 `tools/call`。  
Version 11 改用 MCP Python SDK 的 `FastMCP`，让 SDK 负责协议细节，我们只负责定义工具函数。

## 为什么升级到 MCP SDK

手写 MCP 的好处是能理解底层机制：

- stdio 通信
- JSON-RPC 消息
- `initialize`
- `tools/list`
- `tools/call`

但真实工程中更推荐 SDK：

- 工具注册更简洁
- 协议处理更标准
- 客户端兼容性更好
- 后续扩展 resources、prompts 等能力更方便
- 不需要自己维护 JSON-RPC 细节

## 安装 MCP SDK

如果你的虚拟环境还没有安装 `mcp` 包，先运行：

```powershell
cd C:\Users\18352\Desktop\agent\version11
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe -m pip install -r requirements-mcp.txt
```

也可以直接安装：

```powershell
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe -m pip install mcp
```

注意：普通命令如 `--run-once`、`--eval` 不依赖 MCP SDK。只有运行 `--mcp` 时才需要安装。

## 启动 MCP Server

```powershell
cd C:\Users\18352\Desktop\agent\version11
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --mcp
```

启动后，MCP SDK 会负责：

- 读取 stdio 消息
- 处理 MCP initialize
- 暴露 tools/list
- 路由 tools/call
- 序列化工具返回值

## MCP 客户端配置示例

```json
{
  "mcpServers": {
    "ai-report-agent": {
      "command": "C:\\Users\\18352\\Desktop\\agent\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\Users\\18352\\Desktop\\agent\\version11\\catch_ai.py",
        "--mcp"
      ],
      "cwd": "C:\\Users\\18352\\Desktop\\agent\\version11"
    }
  }
}
```

不同 MCP 客户端配置位置不同，但核心都是：

- command：Python 解释器
- args：`catch_ai.py --mcp`
- cwd：`version11` 项目目录

## 暴露的 MCP Tools

Version 11 暴露以下工具：

```text
generate_daily_report
evaluate_recent_runs
list_recent_runs
get_run_details
get_latest_report
list_recent_events
search_events
get_run_trace
submit_event_feedback
```

### `generate_daily_report`

运行完整日报 Agent。

会执行：

```text
采集 -> 去重 -> 评分 -> 事件聚类 -> LLM 合并 -> RAG -> 生成报告 -> critic -> 保存
```

注意：这个工具会调用 RSS、embedding 模型和 DeepSeek API，耗时较长。

### `evaluate_recent_runs`

生成最近若干次运行的离线评测报告。

参数：

```json
{
  "limit": 5
}
```

### `list_recent_runs`

列出最近运行记录。

参数：

```json
{
  "limit": 5
}
```

### `get_run_details`

查询某次运行的详细信息。

参数：

```json
{
  "run_id": "20260511_143000"
}
```

返回：

- 运行状态
- decisions 决策轨迹
- errors 错误列表
- events 最终事件

### `get_latest_report`

读取最近一份 Markdown 日报。

### `list_recent_events`

列出最近保存的事件级长期记忆。

参数：

```json
{
  "limit": 10
}
```

### `search_events`

按关键词搜索历史事件。

参数：

```json
{
  "query": "OpenAI",
  "limit": 10
}
```

当前是 SQLite 文本搜索，后续可以继续升级成 embedding 语义搜索。

### `get_run_trace`

读取某次运行的 trace JSON。

参数：

```json
{
  "run_id": "20260511_143000"
}
```

### `submit_event_feedback`

给某个事件提交反馈，并刷新 `feedback.json`。

参数：

```json
{
  "event_id": 1,
  "feedback_type": "like",
  "note": "更关注这类产品落地新闻"
}
```

`feedback_type` 支持：

- `like`
- `dislike`
- `note`

## 普通命令仍然可用

生成日报：

```powershell
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --run-once
```

运行评测：

```powershell
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --eval
```

提交命令行反馈：

```powershell
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --feedback
```

定时运行：

```powershell
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --schedule 09:00
```

## 数据库

Version 11 默认数据库：

```text
data/agent_v11.sqlite3
```

## 和 Version 10 的区别

Version 10：

- 手写 stdio JSON-RPC
- 手写 `tools/list`
- 手写 `tools/call`
- 手动维护工具 schema

Version 11：

- 使用 MCP SDK
- 使用 `FastMCP`
- 使用 `@mcp.tool()` 注册工具
- 工具参数由函数签名表达
- 协议细节交给 SDK 处理

## 简历表述建议

可以这样写：

> 将本地 AI 趋势日报 Agent 从手写 JSON-RPC MCP Server 升级为 MCP SDK 实现，使用 FastMCP 注册日报生成、历史事件检索、运行评测、trace 查询和用户反馈等工具，提高协议兼容性和工程可维护性。

更短一点：

> Migrated a custom stdio MCP implementation to the MCP Python SDK, exposing agent memory, evaluation, observability traces, report generation, and feedback learning as production-style MCP tools.

面试时可以重点讲：

- 手写 MCP 和 SDK MCP 的差异
- 为什么 SDK 更适合生产工程
- `@mcp.tool()` 如何把函数暴露成 Agent 工具
- 为什么启动 MCP 时才导入 SDK
- 如何保证普通 CLI 命令不被 MCP 依赖影响

## 测试脚本 version1\test_mcp_client.py
