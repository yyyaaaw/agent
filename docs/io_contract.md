# 输入输出契约

本文档定义 Agent 的主要输入、命令和输出，方便别人接入、复现和评估。

## CLI 命令

| 命令 | 作用 | 主要输出 |
| --- | --- | --- |
| `python catch_ai.py --run-once` | 立即生成一次日报 | `reports/*.md`、`data/runs/*.json`、`data/traces/*.json`、SQLite |
| `python catch_ai.py --schedule 09:00` | 按指定时间每日运行 | 同 `--run-once` |
| `python catch_ai.py --feedback` | 对最近事件做反馈 | 更新 `feedback.json` 和 SQLite feedback 表 |
| `python catch_ai.py --eval --eval-limit 5` | 评估最近 N 次运行 | `data/eval/eval_report_*.md` 和 `.json` |
| `python catch_ai.py --eval-regression` | 运行固定回归评估样例 | `data/eval/regression_report_*.md` 和 `.json` |
| `python catch_ai.py --mcp` | 启动 MCP server | stdio MCP tools |

## 配置输入

### `.env`

`.env` 是本地敏感配置，不进入版本控制。可从 `.env.example` 复制。

关键字段：

| 字段 | 示例 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | `sk-...` | LLM API Key。 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 生成和 critic 使用的模型。 |
| `DATABASE_PATH` | `data/agent.sqlite3` | 本地 SQLite 数据库路径。 |
| `EMBEDDING_PROVIDER` | `bge` / `hash` | embedding 提供方式。 |
| `EMBEDDING_MODEL_PATH` | `models/bge-m3` | 本地 BGE 模型路径。 |
| `MAX_ITEMS_PER_SOURCE` | `6` | 每个来源最多采集条数。 |
| `MAX_ANALYSIS_ITEMS` | `40` | 最多进入 LLM 分析的新闻数。 |
| `BATCH_SIZE` | `20` | LLM 分批处理大小。 |
| `REQUEST_TIMEOUT` | `120` | 网络请求超时秒数。 |
| `DEEPSEEK_COST_MODE` | `balance_delta` | 成本统计模式，默认用 DeepSeek 运行前后余额差额。 |
| `DEEPSEEK_COST_CURRENCY` | `CNY` | 余额差额使用的币种。 |
| `DEEPSEEK_INPUT_PRICE_PER_1M_TOKENS` | `0` | 输入 token 单价，仅作为余额差额不可用时的估算兜底。 |
| `DEEPSEEK_OUTPUT_PRICE_PER_1M_TOKENS` | `0` | 输出 token 单价，仅作为余额差额不可用时的估算兜底。 |

### `sources.json`

资讯源数组。每个来源支持：

```json
{
  "name": "OpenAI Blog",
  "url": "https://openai.com/news/rss.xml",
  "category": "产品与模型",
  "enabled": true,
  "homepage_url": "https://openai.com/news/",
  "fallback_urls": ["https://openai.com/blog/rss.xml"]
}
```

### `profile.json`

用户偏好，影响评分和报告风格。典型字段包括：

- `interests`
- `avoid`
- `preferred_categories`
- `report_style`
- `top_questions`

### `feedback.json`

用户反馈沉淀出的规则，包括喜欢/不喜欢的关键词、来源和类别。

## 运行输出

### `reports/*.md`

最终日报。包含日报正文、参考来源和采集状态。

### `data/runs/run_state_*.json`

单次运行状态。核心字段：

| 字段 | 说明 |
| --- | --- |
| `run_id` | 本次运行 ID。 |
| `raw_item_count` | 原始采集新闻数。 |
| `unique_item_count` | 去重后新闻数。 |
| `selected_item_count` | 入选 LLM 分析新闻数。 |
| `duplicate_count` | 重复新闻数。 |
| `decisions` | 关键决策轨迹。 |
| `errors` | 采集或处理错误。 |
| `report_path` | 最终报告路径。 |
| `critic_result` | 报告自查结果。 |

### `data/traces/trace_*.json`

阶段级 trace。每个 span 包含：

- `name`
- `started_at`
- `ended_at`
- `duration_ms`
- `status`
- `metrics`
- `error`

LLM 相关 span 还会记录本阶段的调用次数、prompt tokens、completion tokens、total tokens 和估算成本。run-level trace 还会记录 DeepSeek 余额差额字段，包括 `llm_actual_cost_available`、`llm_actual_cost`、`llm_actual_cost_currency`、`llm_balance_before`、`llm_balance_after` 和 `llm_balance_error`。

### `data/eval/eval_report_*.md`

离线评估报告。用于回答“最近几次运行是否健康”。
评估报告会汇总运行成功率、critic 通过率、幻觉代理率、来源成功率、RAG 命中率、事件压缩率、耗时、LLM 调用次数、token 用量、余额差额实际扣费和估算成本。

### `evals/regression_cases.json`

固定回归评估样例。用于回答“核心规则在代码或 prompt 修改后有没有退化”。当前样例覆盖去重、评分排序、本地 critic 硬规则、修订完整性校验和 critic FAIL 解析。

### `data/eval/regression_report_*.md`

固定回归评估报告。它不依赖真实 RSS、SQLite 历史数据或 DeepSeek 调用，适合在修改核心逻辑前后快速对比。

### `data/agent.sqlite3`

本地长期数据库，包含 runs、news_items、events、reports、feedback 和 source_errors 等表。
