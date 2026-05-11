# 本地 AI 热点日报 Agent - Version 10

Version 10 基于 Version 9 继续优化，重点完成第二阶段升级：

> MCP Server

这一版的目标是：让这个本地 Agent 不再只是一个命令行脚本，而是可以被其他 Agent 或支持 MCP 的客户端调用的工具服务器。

实现了“手写 MCP 协议的最小可用版”，代码透明，适合理解 MCP 的本质：stdio + JSON-RPC + tools/list + tools/call。

## Version 10 新增了什么

Version 9 已经具备：

- 多源 RSS 采集
- 新闻去重
- 用户偏好评分
- BGE embedding 事件聚类
- LLM 事件二次合并
- 事件级长期记忆 RAG
- 用户反馈闭环
- critic 自我检查与自动修订
- trace 可观测性
- 离线评测报告

Version 10 在此基础上新增：

- `ai_report_agent/mcp_server.py`
- `python catch_ai.py --mcp`
- 一组可被外部 Agent 调用的 MCP tools

这样你可以把这个项目包装成：

> 一个面向 AI 行业动态的本地 Agentic Intelligence MCP Server。

## 启动 MCP Server

```powershell
cd C:\Users\18352\Desktop\agent\version10
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --mcp
```

MCP Server 使用 stdio 通信：

- 从标准输入读取 JSON-RPC 消息
- 向标准输出返回 JSON-RPC 响应
- 日志写到标准错误，避免污染协议输出

当前实现不依赖额外的 MCP Python SDK，方便本地直接运行。

## MCP 客户端配置示例

如果某个 MCP 客户端支持 stdio server，可以配置成类似这样：

```json
{
  "mcpServers": {
    "ai-report-agent": {
      "command": "C:\\Users\\18352\\Desktop\\agent\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\Users\\18352\\Desktop\\agent\\version10\\catch_ai.py",
        "--mcp"
      ],
      "cwd": "C:\\Users\\18352\\Desktop\\agent\\version10"
    }
  }
}
```

不同客户端的配置文件位置不一样，但核心都是：

- command：Python 解释器路径
- args：`catch_ai.py --mcp`
- cwd：`version10` 项目目录

## 暴露的 MCP Tools

### 1. `generate_daily_report`

运行完整日报 Agent。

它会执行：

```text
采集 -> 去重 -> 评分 -> 事件聚类 -> LLM 合并 -> RAG -> 生成报告 -> critic -> 保存
```

返回：

- 报告路径
- 成功提示

注意：这个工具会调用网络、embedding 模型和 DeepSeek API，因此耗时较长。

### 2. `evaluate_recent_runs`

生成最近若干次运行的离线评测报告。

参数：

```json
{
  "limit": 5
}
```

返回：

- eval 报告路径
- Markdown 评测内容

适合让外部 Agent 直接询问：

> 最近几次运行质量怎么样？

### 3. `list_recent_runs`

列出最近运行记录。

参数：

```json
{
  "limit": 5
}
```

返回字段包括：

- run_id
- started_at
- raw_item_count
- unique_item_count
- selected_item_count
- duplicate_count
- report_path
- critic_result
- updated_at

### 4. `get_run_details`

查询某次运行的详细信息。

参数：

```json
{
  "run_id": "20260511_143000"
}
```

返回：

- run 基本信息
- decisions 决策轨迹
- errors 错误列表
- events 最终事件列表

适合复盘某次日报为什么这样生成。

### 5. `get_latest_report`

读取最近一份 Markdown 日报。

不需要参数。

返回：

- run_id
- report_date
- path
- markdown
- critic_result
- created_at

### 6. `list_recent_events`

列出最近保存的事件级长期记忆。

参数：

```json
{
  "limit": 10
}
```

返回：

- event id
- run_id
- title
- summary
- sources
- categories
- scores
- representative_link

### 7. `search_events`

按关键词搜索历史事件。

参数：

```json
{
  "query": "OpenAI",
  "limit": 10
}
```

当前是 SQLite 文本搜索，适合快速查询历史事件标题和摘要。

后续可以继续升级成 embedding 语义搜索。

### 8. `get_run_trace`

读取某次运行的 trace 文件。

参数：

```json
{
  "run_id": "20260511_143000"
}
```

返回：

- trace_path
- trace JSON

适合让外部 Agent 分析：

- 哪一步最慢
- 哪一步失败
- 每个阶段处理了多少数据
- RAG 是否命中
- critic 是否失败

### 9. `submit_event_feedback`

给某个事件提交用户反馈。

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

提交后会：

- 写入 SQLite 的 `event_feedback` 表
- 根据历史反馈重新生成动态偏好规则
- 合并并更新 `feedback.json`

这使外部 Agent 可以直接帮用户调整日报偏好。

## 普通命令仍然可用

生成一次日报：

```powershell
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --run-once
```

运行离线评测：

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

Version 10 默认数据库：

```text
data/agent_v10.sqlite3
```

核心表：

```text
runs
news_items
events
event_items
event_feedback
reports
source_errors
user_feedback
```

## 和 Version 9 的区别

Version 9 解决的是：

> 这个 Agent 能不能被观测、被评测、被复盘？

Version 10 解决的是：

> 这个 Agent 能不能作为工具，被其他 Agent 调用？

新增能力包括：

- stdio MCP Server
- tools/list 工具发现
- tools/call 工具调用
- 日报生成工具
- 历史运行查询工具
- 历史事件查询工具
- trace 查询工具
- eval 查询工具
- 事件反馈提交工具

## 简历表述建议

可以这样写：

> 将本地 AI 趋势日报 Agent 封装为 stdio MCP Server，暴露日报生成、运行评测、历史事件检索、trace 查询和用户反馈提交等 tools，使外部 Agent 可以调用其长期记忆、报告生成和质量评估能力。

更简短一点：

> Built an MCP-compatible tool server for a local AI research agent, exposing report generation, event memory search, observability traces, offline evaluation, and feedback learning as callable tools.

面试时可以重点讲：

- 为什么 MCP 能提升 Agent 间的工具互操作性
- 如何用 tools/list 和 tools/call 暴露本地 Agent 能力
- 为什么日志必须写 stderr，协议响应写 stdout
- 哪些能力适合做成 MCP tool
- 如何让外部 Agent 查询长期记忆和 trace
- 如何通过 feedback tool 形成用户偏好闭环

## 备注

### MCP Server 是什么？
MCP（Model Context Protocol，模型上下文协议） 是由 Anthropic 推出的一项开源开放标准，旨在解决大语言模型与外部数据源、工具之间连接碎片化的问题。

MCP Server（MCP 服务器） 就是实现了这一协议的服务端程序。它像是一个“通用通用适配器”，将你本地或云端的私有数据、API、数据库或业务逻辑封装起来，统一暴露给支持 MCP 的客户端（如 Claude Desktop、Cursor 等 AI 应用）。

一个 MCP Server 通常可以向大模型暴露以下三种核心能力：

- 工具 (Tools)： 允许 AI 调用的可执行函数（例如：执行数据库 SQL 查询、发送邮件、触发特定仿真自动化脚本）。

- 资源 (Resources)： 允许 AI 读取的只读数据源（例如：读取本地某个代码文件的内容、拉取内部 wiki 页面）。

- 提示词模板 (Prompts)： 预定义的结构化交互模板，帮助 AI 更好地理解特定的业务上下文。

### MCP Python SDK 是什么？
MCP Python SDK 是官方提供给 Python 开发者的开发工具包（可通过 pip install mcp 或 uv add mcp 安装），用于极其高效地构建 MCP 服务端或客户端。

它的核心作用是屏蔽底层的协议编解码和流通信细节。SDK 中最核心且现代的组件是 FastMCP（设计理念极度类似于 FastAPI），让开发者可以用极简的 Python 装饰器语法快速定义并启动服务：

from mcp.server.fastmcp import FastMCP
'创建一个 MCP 服务实例'
mcp = FastMCP("DemoServer")
'通过装饰器一键暴露 Tool 工具给大模型'
@mcp.tool()
def add_numbers(a: int, b: int) -> int:
    """将两个数字相加"""
    return a + b

### stdio MCP Server 是什么？
在 MCP 协议中，客户端和服务端需要进行双向通信，这就需要底层的传输层 (Transport) 支持。目前 MCP 规范支持的传输方式主要有两种：stdio 和 HTTP (SSE/Streamable HTTP)。

stdio MCP Server 是指基于标准输入输出（Standard Input/Output）流进行数据通信的 MCP 服务端。

- 工作原理： 当 AI 应用（客户端）启动时，它会在本地机器上直接以子进程（Subprocess）的形式拉起这个 MCP Server（比如在后台执行 python server.py）。随后，客户端直接向该进程的 stdin 写入请求文本，并从进程的 stdout 读取响应文本。

- 核心优势：

  极低延迟： 完全在本地内存和操作系统进程间通信，没有任何网络开销，延迟通常低于 10 毫秒。

  极致安全与简单： 数据完全不出本地机器，不需要配置复杂的端口监听、HTTP 证书或鉴权机制，天然具备操作系统级的进程隔离。

- 适用场景： 极其适合在 Cursor、Claude Desktop 等本地桌面客户端中，接入本地文件系统、本地 SQLite 数据库或本地命令行脚本。

### JSON-RPC 是什么？
JSON-RPC 是一种无状态、轻量级的远程过程调用（RPC，Remote Procedure Call）协议，它使用 JSON 作为数据传输格式。MCP 的数据层完全基于 JSON-RPC 2.0 规范构建。

无论是获取工具列表、执行具体的工具，还是读取资源，MCP 客户端和服务端之间互相传递的，本质上都是完全符合 JSON-RPC 2.0 语法的 JSON 字符串。

JSON-RPC 消息主要分为三种类型：

- 请求 (Request)： 期望对方给出回复。必须包含 jsonrpc: "2.0"、唯一的 id、调用的方法名 method 以及参数 params。
{
  "jsonrpc": "2.0",
  "id": "req_001",
  "method": "tools/call",
  "params": {
    "name": "add_numbers",
    "arguments": { "a": 5, "b": 10 }
  }
}

- 响应 (Response)： 针对请求的最终回复。通过相同的 id 进行映射关联，包含成功时的 result 或失败时的 error
{
  "jsonrpc": "2.0",
  "id": "req_001",
  "result": {
    "content": [{ "type": "text", "text": "15" }]
  }
}

- 通知 (Notification)： 单向触发消息，没有 id 字段，接收方收到后无需发送任何回复（例如服务器向客户端实时推送状态更新）

## 本地测试 MCP 功能
MCP 本质上就是通过 stdin/stdout 传 JSON-RPC 消息.

'''powershell
cd C:\Users\18352\Desktop\agent\version10

@'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
'@ | & C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --mcp
'''

如果正常，你会看到两个 JSON 响应：
- 第一个是 server 信息：ai-report-agent
{"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "ai-report-agent", "version": "10.0.0"}}}

- 第二个是 tools 列表，比如 generate_daily_report、evaluate_recent_runs 等
{"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "generate_daily_report", "description": "Run the full AI trend report agent once and return the generated report path.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": false}}, {"name": "evaluate_recent_runs", "description": "Generate an offline evaluation report for recent agent runs.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "description": "Number of recent runs to evaluate.", "default": 5}}, "additionalProperties": false}}, {"name": "list_recent_runs", "description": "List recent run metadata from SQLite.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 5}}, "additionalProperties": false}}, {"name": "get_run_details", "description": "Return run decisions, errors, and events for one run_id.", "inputSchema": {"type": "object", "properties": {"run_id": {"type": "string"}}, "required": ["run_id"], "additionalProperties": false}}, {"name": "get_latest_report", "description": "Return the latest saved Markdown report.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": false}}, {"name": "list_recent_events", "description": "List recent event-level memory records.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 10}}, "additionalProperties": false}}, {"name": "search_events", "description": "Search historical events by keyword in title or summary.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["query"], "additionalProperties": false}}, {"name": "get_run_trace", "description": "Return the observability trace JSON for one run_id.", "inputSchema": {"type": "object", "properties": {"run_id": {"type": "string"}}, "required": ["run_id"], "additionalProperties": false}}, {"name": "submit_event_feedback", "description": "Submit like/dislike/note feedback for an event and refresh feedback.json.", "inputSchema": {"type": "object", "properties": {"event_id": {"type": "integer"}, "feedback_type": {"type": "string", "enum": ["like", "dislike", "note"]}, "note": {"type": "string", "default": ""}}, "required": ["event_id", "feedback_type"], "additionalProperties": false}}]}}

也可以调用其它函数，比如：
@'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"evaluate_recent_runs","arguments":{"limit":3}}}
'@ | & C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --mcp
或者
@'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_recent_runs","arguments":{"limit":5}}}
'@ | & C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --mcp
