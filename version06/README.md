# 本地 AI 热点日报 Agent - Version 6

这是第六版 agent：在 Version 5 的本地 BGE-M3 embedding RAG 基础上，新增“事件聚类”和“事件级 RAG”。

当前版本目录：

```text
C:\Users\18352\Desktop\agent\version6
```

## Version 6 新增能力

- `events.py`：把相似新闻聚成事件。
- `events` 表：保存每天的事件级聚类结果。
- `event_items` 表：保存事件和新闻之间的关系。
- 最终报告优先基于事件，而不是零散新闻。
- RAG 优先检索历史事件，找不到时再回退到历史新闻。

## 为什么要做事件聚类

多个 RSS 来源可能报道同一件事：

```text
OpenAI 官方发布新语音模型
TechCrunch 报道语音客服落地
The Decoder 跟进 OpenAI 语音能力
```

Version 6 会尽量把它们合并成一个事件：

```text
事件：OpenAI 语音 Agent / 实时语音能力扩展
来源：OpenAI Blog、TechCrunch、The Decoder
```

这样报告更少重复，更像趋势分析。

## 配置

仍然使用本地 BGE-M3：

```text
EMBEDDING_PROVIDER=bge
EMBEDDING_MODEL_PATH=E:\Agent_zr\embedding_model\bge-m3
EMBEDDING_USE_FP16=false
EMBEDDING_BATCH_SIZE=8
EMBEDDING_MAX_LENGTH=512
DATABASE_PATH=data/agent_v6.sqlite3
```

## 运行方式

推荐使用项目虚拟环境：

```powershell
cd C:\Users\18352\Desktop\agent\version6
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --run-once
```

成功后会生成：

- `reports/ai_hotspots_YYYY-MM-DD.md`
- `data/raw/ai_news_raw_YYYY-MM-DD.json`
- `data/runs/run_state_YYYYMMDD_HHMMSS.json`
- `data/agent_v6.sqlite3`

## 数据库表

核心表：

```text
runs            # 每次运行状态
news_items      # 新闻、评分、embedding、入选结果
events          # 事件聚类结果
event_items     # 事件和新闻的关联
reports         # Markdown 报告正文和自查结果
source_errors   # RSS 来源失败记录
user_feedback   # 用户反馈规则快照
```

## RAG 如何变化

Version 5：

```text
当天新闻 -> 检索历史新闻 -> 放进 prompt
```

Version 6：

```text
当天新闻 -> 聚成事件 -> 检索历史事件 -> 放进 prompt
```

如果历史事件为空，会自动回退到历史新闻检索。

## 如何确认事件聚类生效

运行后查看：

```text
data/runs/run_state_*.json
```

搜索：

```text
事件聚类完成
```

也可以打开 SQLite 查看 `events` 表。

## 代码结构

```text
ai_report_agent/
  agent.py                   # 串联完整流程
  database.py                # SQLite、事件表、事件级 RAG
  deepseek_client.py         # DeepSeek API 与最终 prompt
  embeddings.py              # 本地 BGE-M3 embedding
  events.py                  # 事件聚类
  scorer.py                  # 评分和反馈加权
```
