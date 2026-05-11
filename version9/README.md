# 本地 AI 热点日报 Agent - Version 9

Version 9 基于 Version 8 继续优化，重点完成第一阶段升级：

> Agent 评测体系 + 可观测性

这版的目标不是简单“再生成一份日报”，而是让这个 Agent 变得更像一个可复盘、可调试、可解释的生产级系统。这样也更适合写进简历，用来展示你对 Agent 工程化的理解。

测评框架：
+ 构造历史样本集：保存几次日报的原始新闻、事件聚类结果、最终报告、人工标注反馈。
+ 评测指标：
    资讯筛选准确率：选中的新闻是否真和 AI 应用有关。
    事件聚类质量：同一事件是否被拆散，不同事件是否被误合并。
    报告事实一致性：每个关键结论能否追溯到来源。
    个性化命中率：用户点赞类型在后续报告中是否上升。
使用 eval.py 一键输出评分报告。

可观测性：
    记录耗时、输入数量、输出数量、LLM token、费用、失败原因。
    做一个简单 dashboard：最近 10 次运行成功率、来源失败率、聚类数量变化、critic 通过率
帮助理解生产环境中的Agent.

## 新增能力

### 1. 结构化运行 Trace

每次运行日报时，Version 9 会额外保存一份 trace 文件：

```text
data/traces/trace_<run_id>.json
```

trace 会记录 Agent 每个关键阶段的运行情况，包括：

- `initialize_database`：初始化数据库
- `load_profile_and_feedback`：读取用户偏好和反馈规则
- `load_sources`：读取 RSS 信息源
- `collect_news`：采集新闻
- `save_raw_items`：保存原始采集结果
- `save_raw_news_items`：将新闻写入 SQLite
- `deduplicate_items`：新闻去重
- `score_items`：按用户偏好和应用价值评分
- `select_items_for_analysis`：筛选进入 LLM 分析的新闻
- `cluster_scored_items`：用 embedding 做事件粗聚类
- `refine_events_with_llm`：用 LLM 做事件二次合并
- `retrieve_related_events`：检索历史相关事件
- `retrieve_related_history_fallback`：事件检索失败时回退到新闻级历史检索
- `analyze_news`：生成日报正文
- `build_report_markdown`：拼装 Markdown 报告
- `critique_report`：质量自查
- `revise_report`：必要时自动修订
- `save_report`：保存最终报告

每个阶段会记录：

- 开始时间
- 结束时间
- 耗时，单位毫秒
- 执行状态
- 关键指标，例如采集数量、入选数量、最终事件数、RAG 是否命中
- 如果失败，会记录错误信息

这就是 Agent 的可观测性。它能帮你回答：

- 哪一步最慢？
- 哪一步失败了？
- 采集到了多少新闻？
- 去重是否有效？
- 事件聚类是否真的压缩了重复新闻？
- RAG 长期记忆有没有发挥作用？
- critic 是否认为报告质量通过？

### 2. 离线评测体系

Version 9 新增：

```text
ai_report_agent/evaluation.py
```

它会读取 SQLite、run_state 和 trace 文件，自动生成一份 Agent 运行质量评测报告。

运行方式：

```powershell
cd C:\Users\18352\Desktop\agent\version9
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --eval
```

也可以指定评测最近多少次运行：

```powershell
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --eval --eval-limit 10
```

评测结果会保存到：

```text
data/eval/eval_report_<timestamp>.md
data/eval/eval_report_<timestamp>.json
```

当前评测指标包括：

- 采集数量是否充足
- 去重后是否还有有效新闻
- 筛选比例是否合理
- 事件聚类是否有压缩效果
- 信息源失败数量
- RAG 长期记忆是否命中
- critic 是否通过
- trace 总耗时
- 用户反馈数量

这个评分不是严格学术 benchmark，而是工程上很实用的健康度评分。它的价值在于帮助你持续观察：

> 这个 Agent 是否越来越稳定、越来越可解释、越来越符合用户偏好？

## 生成一次日报

```powershell
cd C:\Users\18352\Desktop\agent\version9
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --run-once
```

运行后会生成：

```text
reports/ai_hotspots_<date>.md
data/runs/run_state_<run_id>.json
data/traces/trace_<run_id>.json
data/agent_v9.sqlite3
```

## 提交用户反馈

```powershell
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --feedback
```

反馈会写入 SQLite，并同步更新 `feedback.json`。下一次生成日报时，Agent 会使用这些反馈影响新闻评分。

## 运行评测

```powershell
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --eval
```

如果当前 `agent_v9.sqlite3` 还没有运行记录，评测报告会提示先执行：

```powershell
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --run-once
```

这是正常情况。

## 数据库

Version 9 默认数据库：

```text
data/agent_v9.sqlite3
```

核心表包括：

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

## 和 Version 8 的区别

Version 8 的重点是提升“新闻 -> 事件”的归类质量：

- 使用 BGE embedding 做候选事件粗聚类
- 使用 DeepSeek 对候选事件做二次合并
- 生成更像真实事件的标题，而不是直接复用新闻标题
- 增加事件级 RAG 和记忆检索

Version 9 在此基础上新增工程化能力：

- 给每次运行保存结构化 trace
- 对关键阶段记录耗时和指标
- 失败时也尽量保存 trace，方便复盘
- 新增 `--eval` 命令
- 自动生成离线评测报告
- 用评分和 findings 展示 Agent 当前的质量风险

## 简历表述建议

可以这样写：

> 构建了一个面向 AI 行业动态的本地 Agent 系统，支持多源 RSS 采集、语义去重、事件级聚类、长期记忆 RAG、用户反馈学习、LLM 自我评审与自动修订，并在 Version 9 中加入结构化 trace 和离线评测体系，用于监控采集质量、事件压缩效果、RAG 命中情况、critic 通过率和运行耗时。

也可以写得更短一点：

> 为多阶段 AI Agent 增加可观测性与离线评测能力，实现 trace 级调试、历史运行质量评分和 Agent 行为复盘。

面试时可以重点讲：

- 为什么 Agent 需要 evaluation，而不只是能跑通
- 如何用 trace 定位慢步骤和失败步骤
- 如何用事件压缩率判断聚类质量
- 如何用 RAG 命中率判断长期记忆是否有效
- 如何用 critic 通过率衡量报告可靠性
