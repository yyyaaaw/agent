# 架构设计

本项目采用本地单体 Agent 架构。核心思路是把“资讯采集、结构化处理、模型生成、质量检查、评估复盘”拆成明确阶段，并为每个阶段留下可观察产物。

## 运行流程

```text
配置加载
  .env / sources.json / profile.json / feedback.json
        ↓
Skill / CLI / MCP 能力入口
  skills.py -> catch_ai.py / mcp_server.py
        ↓
资讯采集
  load_sources -> collect_news -> source_health.json
        ↓
持久化原始数据
  data/raw/*.json + news_items table
        ↓
去重
  deduplicate_items -> unique items
        ↓
评分筛选
  score_items -> select_items_for_analysis
        ↓
事件粗聚类
  cluster_scored_items -> candidate events
        ↓
LLM 事件整合
  refine_events_with_llm -> final events
        ↓
长期记忆检索
  retrieve_related_events -> retrieve_related_history fallback
        ↓
日报生成
  event-first analyze_news -> build_report_markdown
        ↓
质量自查和修订
  critique_report -> revise_report -> validate_revision_report
        ↓
保存产物
  reports/ + data/runs/ + data/traces/ + SQLite
        ↓
离线评估
  python catch_ai.py --eval
```

## 模块职责

| 模块 | 职责 |
| --- | --- |
| `catch_ai.py` | CLI 入口，分发 run、schedule、feedback、eval、mcp 命令。 |
| `config.py` | 读取 `.env` 和默认配置，创建目录。 |
| `sources.py` | 加载来源、抓取 RSS、自动发现 feed、维护来源健康状态。 |
| `deduplicator.py` | 链接和标题级去重。 |
| `scorer.py` | 按偏好、来源、类别和反馈规则给新闻打分。 |
| `events.py` | 事件特征提取、粗聚类、事件格式化。 |
| `deepseek_client.py` | 构造 prompt、调用 LLM、解析事件合并 JSON。 |
| `database.py` | SQLite 表结构、运行记录、新闻、事件、报告和 RAG 检索。 |
| `critic.py` | 报告质量检查、日期硬规则、修订闸门。 |
| `observability.py` | span trace、阶段耗时和 run-level metrics。 |
| `evaluation.py` | 离线评估最近运行，输出 Markdown 和 JSON 报告。 |
| `mcp_server.py` | 把核心能力暴露为 MCP tools。 |
| `skills.py` | Agent v16 Skill Registry，描述技能、风险、工具链和 dry-run 计划。 |

## 数据存储

- SQLite：长期运行事实、新闻、事件、报告、反馈和 RAG 检索数据。
- JSON：run state、trace、source health、raw data 和 eval report。
- Markdown：最终日报和评估报告。

## 设计取舍

- 采用本地 SQLite，而不是外部数据库，降低部署和展示成本。
- 采用标准库 HTTP 和 XML 解析，减少基础链路依赖。
- 把 prompt 保存到 `data/debug/`，方便定位模型输入问题。
- 把 critic 和 evaluation 拆开：critic 评单次报告，evaluation 看多次运行趋势。
- 把 Skill 层放在现有 pipeline 之上：它负责能力发现和规划，不重写稳定的日报主流程。
