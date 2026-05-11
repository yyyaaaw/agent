# 本地 AI 热点日报 Agent - Version 3

这是第三版 agent：在 Version 2 的“采集、去重、评分、DeepSeek 分析、自查”基础上，增加了 SQLite 长期记忆和轻量 RAG 检索。

当前版本目录：

```text
C:\Users\18352\Desktop\agent\version3
```

## Version 3 新增能力

- `database.py`：使用 SQLite 保存运行、新闻、评分、报告和采集错误。
- `DATABASE_PATH`：在 `.env` 中配置数据库文件路径，默认是 `data/agent_v3.sqlite3`。
- 历史检索上下文：生成最终日报前，会从数据库检索相关历史资讯，并写入最终汇总 prompt。
- 来源质量沉淀：采集失败的 RSS 来源会写入数据库，后续可以统计来源稳定性。
- 报告长期存档：Markdown 报告不仅保存为文件，也保存到 SQLite，方便后续做周报、月报和趋势分析。

## 1. 准备环境

确认使用 Python 3.10 或更高版本。本项目仍然只使用 Python 标准库，不需要安装第三方依赖。

## 2. 配置 DeepSeek API Key

复制 `.env.example` 为 `.env`，然后把 `DEEPSEEK_API_KEY` 改成你自己的 Key。

```text
DEEPSEEK_API_KEY=sk-你的真实key
```

Version 3 新增数据库配置：

```text
DATABASE_PATH=data/agent_v3.sqlite3
```

## 3. 立即运行一次

在 `version3` 目录执行：

```bash
python catch_ai.py --run-once
```

如果终端当前在总目录 `C:\Users\18352\Desktop\agent`，可以执行：

```bash
python version3\catch_ai.py --run-once
```

成功后会生成：

- `reports/ai_hotspots_YYYY-MM-DD.md`：最终日报
- `data/raw/ai_news_raw_YYYY-MM-DD.json`：原始采集数据
- `data/runs/run_state_YYYYMMDD_HHMMSS.json`：运行状态 JSON
- `data/agent_v3.sqlite3`：SQLite 长期记忆数据库

## 4. 数据库保存了什么

SQLite 里目前有四张核心表：

```text
runs            # 每次运行的总体状态
news_items      # 每次采集到的新闻、评分和入选结果
reports         # 最终 Markdown 报告正文和自查结果
source_errors   # RSS 来源失败记录
```

这些数据让 agent 不只“当天生成一份报告”，还可以逐步拥有历史记忆。后续可以基于它继续做：

- 最近 7 天相似新闻检索
- 某家公司连续动态追踪
- 来源质量评分
- 周报/月报生成
- 用户反馈闭环
- embedding 向量检索

## 5. 轻量 RAG 如何工作

Version 3 现在先做了一个低成本 RAG 雏形：

1. 先采集和评分当天新闻。
2. 选出进入 DeepSeek 的资讯。
3. 从 SQLite 历史新闻里检索标题/摘要相关的旧记录。
4. 把检索结果写进最终汇总 prompt。
5. DeepSeek 在写日报时可以参考这些历史上下文，判断趋势延续性。

这还不是 embedding RAG，只是关键词检索。下一阶段可以把 `retrieve_related_history()` 替换成向量检索。

## 6. 配置资讯源和偏好

- `sources.json`：RSS 来源配置。
- `profile.json`：用户偏好配置。

`profile.json` 会影响：

- 本地规则打分
- DeepSeek 分析 prompt
- 报告质量自查标准

## 7. 每天定时运行

例如每天早上 9 点运行：

```bash
python catch_ai.py --schedule 09:00
```

也可以在 `.env` 中修改：

```text
REPORT_TIME=09:00
```

然后直接运行：

```bash
python catch_ai.py
```

如果使用 Windows 任务计划程序，建议：

```text
程序或脚本：
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe

添加参数：
catch_ai.py --run-once

起始于：
C:\Users\18352\Desktop\agent\version3
```

## 8. 代码结构

```text
catch_ai.py                  # 命令行入口
sources.json                 # RSS 资讯源配置
profile.json                 # 用户偏好配置
ai_report_agent/
  agent.py                   # 串联完整日报流程
  config.py                  # 配置和 .env 读取
  critic.py                  # 报告质量自查和修订
  database.py                # SQLite 长期记忆和轻量历史检索
  deduplicator.py            # 资讯去重
  deepseek_client.py         # DeepSeek API 调用
  profile.py                 # 用户偏好读取
  report.py                  # Markdown 报告生成
  scorer.py                  # 热点评分筛选
  scheduler.py               # 每日定时调度
  sources.py                 # RSS 热点源采集和解析
  state.py                   # 运行状态记录
```

## 9. 常见问题

如果提示缺少 `DEEPSEEK_API_KEY`，请检查 `version3/.env` 是否存在，并确认 Key 已填写。

如果某些资讯源采集失败，日报仍会基于成功采集的内容生成，失败源会记录在报告底部，也会写入 SQLite 的 `source_errors` 表。
