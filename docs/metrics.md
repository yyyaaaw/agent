# 指标体系

指标体系用于证明这个 Agent 不是一次性 demo，而是可以观察、比较和持续改进的系统。

## 指标分层

| 层级 | 问题 | 示例指标 |
| --- | --- | --- |
| 运行层 | Agent 有没有成功跑完？ | 运行成功率、失败原因、总耗时 |
| 数据层 | 输入是否稳定？ | 原始新闻数、来源成功率、source error count |
| 筛选层 | 是否减少噪声？ | 去重数、入选比例、评分分布 |
| 事件层 | 是否完成事件级聚合？ | 事件压缩率、平均每事件新闻数、过度合并风险 |
| 生成层 | 报告是否完整？ | Markdown 字符数、critic PASS 率、修订接受率 |
| 事实层 | 是否减少幻觉？ | 无来源支撑事实数、幻觉代理率 |
| 成本层 | 运行是否可控？ | token 用量、余额差额实际扣费、估算成本、模型调用次数 |
| 记忆层 | 历史数据是否有用？ | RAG 命中率、历史事件命中数 |

## 当前已落地指标

| 指标 | 来源 | 说明 |
| --- | --- | --- |
| `raw_items` | run state / trace | 原始采集新闻数。 |
| `unique_items` | run state / trace | 去重后新闻数。 |
| `selected_items` | run state / trace | 进入 LLM 分析的新闻数。 |
| `duplicate_count` | run state / trace | 去重删除数量。 |
| `candidate_events` | trace span | 粗聚类候选事件数。 |
| `candidate_event_compression_ratio` | trace span | 入选新闻数 / 候选事件数。 |
| `final_events` | trace | LLM 整合后的最终事件数。 |
| `source_errors` | trace / SQLite | 本次采集失败来源数。 |
| `rag_hit` | trace / decisions | 是否命中历史上下文。 |
| `critic_failed` | trace / critic_result | critic 是否发现硬问题。 |
| `revision_accepted` | trace | 自动修订是否通过完整性校验。 |
| `duration_ms` | trace | 整体和阶段耗时。 |
| `llm_call_count` | trace | 本次运行的 LLM 调用次数。 |
| `llm_prompt_tokens` | trace | 输入 token 总数。 |
| `llm_completion_tokens` | trace | 输出 token 总数。 |
| `llm_total_tokens` | trace | 输入和输出 token 总数。 |
| `llm_actual_cost_available` | trace | 是否成功用 DeepSeek 余额差额计算实际扣费。 |
| `llm_actual_cost` | trace | 运行前余额 - 运行后余额。 |
| `llm_actual_cost_currency` | trace | 实际扣费币种，默认 `CNY`。 |
| `llm_balance_error` | trace | 余额差额不可用时的原因。 |
| `llm_estimated_cost_usd` | trace | 按配置单价估算的兜底成本。 |

## Eval 汇总 KPI

`python catch_ai.py --eval` 会把最近 N 次运行汇总成项目级 KPI：

| KPI | 计算方式 | 价值 |
| --- | --- | --- |
| 运行成功率 | 成功 run 数 / 最近 N 次 run 数 | 衡量 Agent 是否稳定完成任务。 |
| critic 通过率 | critic PASS 数 / 最近 N 次 run 数 | 衡量报告质量。 |
| 幻觉代理率 | critic 中无来源支撑问题数 / 最近 N 次 run 数 | 近似衡量事实编造风险。 |
| 来源成功率 | 成功来源尝试数 / 总来源尝试数 | 衡量采集链路健康度。 |
| 平均事件压缩率 | 平均 `selected_items / candidate_events` | 衡量新闻是否被归并成事件。 |
| RAG 命中率 | RAG 命中 run 数 / 最近 N 次 run 数 | 衡量长期记忆是否发挥作用。 |
| 平均耗时 | 最近 N 次 trace duration 平均值 | 衡量运行效率。 |
| p95 阶段耗时 | 各 span p95 duration | 定位性能瓶颈。 |
| 修订接受率 | accepted revision 数 / revision triggered 数 | 衡量修订链路可靠性。 |
| 实际扣费 | DeepSeek 运行前后余额差额 | 衡量本次运行的真实扣费；同一 API key 同时被其他任务使用时会有偏差。 |
| 成本估算 | token 用量 * 配置单价 | 余额差额不可用时的兜底参考。 |

默认使用 `DEEPSEEK_COST_MODE=balance_delta`，Agent 会在运行前后读取 DeepSeek 余额并计算差额。Chat Completion 响应本身只提供 token usage，不直接返回本次扣费；如果余额接口不可用，trace 和 eval 会保留错误原因，并使用 `DEEPSEEK_INPUT_PRICE_PER_1M_TOKENS` / `DEEPSEEK_OUTPUT_PRICE_PER_1M_TOKENS` 的估算值作为兜底。

## 幻觉率定义

严格幻觉率需要人工标注或外部事实核验。当前项目先采用“幻觉代理率”：

```text
幻觉代理率 = critic 明确指出无来源支撑事实的运行数 / 被评估运行数
```

这个指标不等于真实幻觉率，但它是工程上可自动计算、可持续跟踪的风险信号。

当前已增加 `evals/regression_cases.json`，用固定样例测试去重、评分排序、本地 critic 硬规则、修订完整性校验和 critic FAIL 解析。它不参与真实日报生成，只用于回归评估。

## 成功率定义

初期使用运行产物判断：

```text
运行成功 = trace status == "ok" 且 report_path 非空
```

更严格版本可以加入：

- critic 必须 PASS。
- source error count 不超过阈值。
- Markdown 字符数不低于阈值。
- final_events 大于 0。

## 推荐目标值

| 指标 | 初始目标 |
| --- | ---: |
| 运行成功率 | >= 90% |
| critic 通过率 | >= 80% |
| 幻觉代理率 | <= 10% |
| 来源成功率 | >= 85% |
| 平均事件压缩率 | >= 1.30 |
| RAG 命中率 | >= 50% |
| 单次运行耗时 | <= 10 分钟 |
