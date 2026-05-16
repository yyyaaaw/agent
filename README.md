# 本地 AI 热点日报 Agent

这是一个面向 AI 应用趋势跟踪的本地 Agent 项目。它会从多个 AI 资讯源采集内容，完成去重、评分筛选、事件聚类、历史检索增强、日报生成、质量自查和离线评估，并把每次运行的状态、trace、报告和评估结果保存到本地。

当前根目录是最新版代码结构。历史迭代版本已归档到 `archive/versions/`。

## Project Positioning

目标用户：

- 需要持续跟踪 AI 产品、应用、商业落地和开发者工具变化的个人或团队。
- 希望把资讯采集、筛选、归并、总结和质量检查自动化的工程实践者。
- 希望展示一个可观测、可评估、可扩展 Agent 项目的开发者。

核心目标：

- 把分散 AI 新闻压缩成事件级日报，而不是简单新闻列表。
- 让每次 Agent 运行都能被复盘：看得到输入、决策、输出、耗时、错误和质量检查结果。
- 用离线评估指标持续判断 Agent 是否更稳定、更可靠。

非目标：

- 不保证完全自动事实核验，关键结论仍需要人工抽查。
- 不直接发布或推送到生产系统。
- 不处理敏感密钥托管、团队权限系统或多租户部署。

## Core Capabilities

- RSS/网页资讯源采集与来源健康记录。
- 新闻去重、评分和用户偏好过滤。
- 基于 embedding、实体、动作类型和关键词重叠的事件粗聚类。
- LLM 事件整合与中文日报生成。
- SQLite 本地长期记忆与事件级 RAG。
- 报告 critic 质量自查与自动修订闸门。
- JSON trace、run state、SQLite 记录和离线评估报告。
- MCP server，允许外部 MCP 客户端调用 Agent 能力。

## Documentation

- [能力边界](docs/capabilities.md)
- [架构设计](docs/architecture.md)
- [输入输出契约](docs/io_contract.md)
- [指标体系](docs/metrics.md)
- [安全设计](docs/safety.md)

## Architecture

```text
sources.json / profile.json / feedback.json
        ↓
collect_news
        ↓
deduplicate_items
        ↓
score_items + select_items_for_analysis
        ↓
cluster_scored_items
        ↓
refine_events_with_llm
        ↓
retrieve_related_events / retrieve_related_history
        ↓
analyze_news
        ↓
critique_report + optional revision
        ↓
reports/ + data/runs/ + data/traces/ + SQLite
        ↓
offline evaluation
```

## Quick Start

安装依赖后，复制 `.env.example` 为本地 `.env` 并配置 `DEEPSEEK_API_KEY`。

```powershell
python -m pip install -r requirements.txt
```

生成一次日报：

```powershell
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --run-once
```

评估最近运行：

```powershell
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --eval --eval-limit 5
```

启动 MCP server：

```powershell
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --mcp
```

## Inputs And Outputs

主要输入：

- `.env.example` / `.env`：模型、路径、超时、批大小等运行配置。
- `sources.json`：资讯源配置。
- `profile.json`：用户关注方向和报告风格。
- `feedback.json`：历史反馈沉淀出的评分规则。

主要输出：

- `reports/`：最终 Markdown 日报。
- `data/runs/`：每次运行的结构化状态。
- `data/traces/`：每个阶段的耗时、状态和指标。
- `data/eval/`：离线评估报告。
- `data/agent.sqlite3`：本地长期运行数据库。
- `data/source_health.json`：资讯源可用性记录。

## Evaluation Metrics

`python catch_ai.py --eval` 会输出 Markdown 和 JSON 两份离线评估报告，当前包含：

- 运行成功率：最近 N 次运行中正常完成的比例。
- critic 通过率：报告质量检查 PASS 的比例。
- 幻觉代理率：critic 发现“无来源支撑事实”的比例。
- 来源成功率：资讯源采集成功次数 / 总尝试次数。
- 事件压缩率：入选新闻数 / 候选事件数。
- 平均每事件新闻数：用于判断是否从新闻级列表提升到事件级聚合。
- RAG 命中率：运行中是否检索到历史上下文。
- 平均耗时、p95 耗时和最慢阶段：来自 trace span。
- LLM 调用次数、token 用量、实际扣费和估算成本：优先用 DeepSeek 运行前后余额差额，失败时保留 usage * 单价估算。

## Safety

- `.env` 不进入版本控制，根目录只保留 `.env.example`。
- API Key 仅从本地环境变量或 `.env` 读取。
- 运行数据默认保存在本地 `data/` 和 `reports/`。
- Agent 会记录 trace 和 run state，避免黑盒运行。
- critic 会检查日期错误、无来源事实、重复热点和报告结构问题。

## Project Layout

```text
agent/
  ai_report_agent/          # 当前最新版 Agent 代码
  archive/versions/         # 历史版本快照
  docs/                     # 工程文档
  data/                     # 本地运行数据
  reports/                  # 生成的日报
  catch_ai.py               # CLI 入口
  sources.json              # 资讯源配置
  profile.json              # 用户偏好
  feedback.json             # 反馈规则
  .env.example              # 环境变量示例
```

## Version Archive

历史版本位于：

```text
archive/versions/version01
archive/versions/version02
...
archive/versions/version13
```

根目录代表当前可运行版本；历史目录用于回看每次能力迭代和设计取舍。
