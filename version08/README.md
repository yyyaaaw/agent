# 本地 AI 热点日报 Agent - Version 8

Version 8 在 Version 7 的反馈闭环基础上，重点优化“新闻 -> 事件”的归类质量。

## 新增能力

- 先用 BGE embedding 做候选事件粗聚类。
- 再调用 DeepSeek 对候选事件做二次整合，判断哪些候选事件其实属于同一个真实事件。
- 事件标题由 LLM 重新生成，不再默认使用某一条新闻标题。
- `data/runs/run_state_*.json` 的 `decisions` 会写入：
  - embedding 粗聚类得到多少候选事件
  - LLM 如何合并候选事件
  - 最终事件清单
  - 每个事件包含哪些相关新闻

## 运行日报

```powershell
cd C:\Users\18352\Desktop\agent\version8
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --run-once
```

运行结束后，可以直接查看：

```text
data/runs/run_state_*.json
```

重点看 `decisions` 里的这些内容：

```text
事件粗聚类完成：30 条入选资讯 -> 30 个候选事件
LLM事件整合：OpenAI 语音模型与客服 Agent 落地加速 <- event_1, event_8
LLM事件整合结果：30 个候选事件 -> 18 个最终事件
最终事件清单：
事件 1｜OpenAI 语音模型与客服 Agent 落地加速｜新闻数 3｜来源 ...
```

## 提交反馈

日报运行完成后，执行：

```powershell
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --feedback
```

程序会列出最近一次日报的事件，你可以点赞、点踩或写备注。
反馈会保存到 SQLite 的 `event_feedback` 表，同时自动汇总写回 `feedback.json`。

## 数据库

默认数据库：

```text
data/agent_v8.sqlite3
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

## 配置

仍然使用本地 BGE-M3 做 embedding，并使用 DeepSeek 做事件整合和日报生成：

```text
DATABASE_PATH=data/agent_v8.sqlite3
EMBEDDING_PROVIDER=bge
EMBEDDING_MODEL_PATH=E:\Agent_zr\embedding_model\bge-m3
```

## 和 Version 7 的区别

Version 7 的事件标题默认来自最高分新闻标题，容易出现“一个新闻一个事件”的反馈体验。

Version 8 会把候选事件材料交给 LLM，让模型根据“主体、核心进展、时间段、事实关系”重新合并事件，并生成更像事件而不是新闻标题的名称。
