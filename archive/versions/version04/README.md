# 本地 AI 热点日报 Agent - Version 4

这是第四版 agent：在 Version 3 的 SQLite 长期记忆和轻量 RAG 基础上，加入了本地 embedding 向量检索和用户反馈评分。

当前版本目录：

```text
C:\Users\18352\Desktop\agent\version4
```

## Version 4 新增能力

- `embeddings.py`：把新闻标题、摘要、来源类别转换成本地哈希 embedding。
- 向量检索 RAG：用余弦相似度从 SQLite 中检索历史相似新闻。
- `feedback.json`：记录喜欢/不喜欢的关键词、来源、类别。
- `feedback.py`：读取反馈配置。
- `scorer.py`：评分时叠加反馈加分/扣分。
- `user_feedback` 表：保存每次运行使用的反馈快照。
- `news_items.embedding_json`：每条新闻保存 embedding，后续可做语义检索。

## 1. 准备环境

确认使用 Python 3.10 或更高版本。本项目仍然只使用 Python 标准库，不需要安装第三方依赖。

## 2. 配置 DeepSeek API Key

复制 `.env.example` 为 `.env`，然后把 `DEEPSEEK_API_KEY` 改成你自己的 Key。

```text
DEEPSEEK_API_KEY=sk-你的真实key
```

Version 4 新增/沿用配置：

```text
PROFILE_FILE=profile.json
FEEDBACK_FILE=feedback.json
DATABASE_PATH=data/agent_v4.sqlite3
```

## 3. 立即运行一次

在 `version4` 目录执行：

```bash
python catch_ai.py --run-once
```

如果终端当前在总目录 `C:\Users\18352\Desktop\agent`，可以执行：

```bash
python version4\catch_ai.py --run-once
```

成功后会生成：

- `reports/ai_hotspots_YYYY-MM-DD.md`：最终日报
- `data/raw/ai_news_raw_YYYY-MM-DD.json`：原始采集数据
- `data/runs/run_state_YYYYMMDD_HHMMSS.json`：运行状态 JSON
- `data/agent_v4.sqlite3`：SQLite 长期记忆数据库

## 4. 向量 RAG 如何工作

Version 4 的 RAG 流程：

```text
当天入选新闻
  -> 拼接标题、摘要、类别、来源
  -> embeddings.py 生成本地 embedding
  -> database.py 从历史 news_items 中读取 embedding
  -> 计算余弦相似度
  -> 选出最相似的历史新闻
  -> 写入 DeepSeek 最终汇总 prompt
```

它仍然不是商业 embedding 模型，但已经具备真正的“文本向量化 + 相似度检索 + prompt 增强”结构。后续可以把 `embed_text()` 替换成 API embedding。

## 5. 用户反馈如何影响打分

`feedback.json` 示例：

```json
{
  "liked_keywords": ["agent", "workflow", "智能体", "工作流"],
  "disliked_keywords": ["融资", "估值", "纯论文"],
  "liked_sources": ["OpenAI Blog", "Microsoft AI Blog"],
  "disliked_sources": [],
  "liked_categories": ["应用与产品", "企业应用"],
  "disliked_categories": ["研究论文"]
}
```

评分时会叠加：

```text
喜欢类别：+2
不喜欢类别：-3
喜欢来源：+2
不喜欢来源：-3
喜欢关键词：每个 +1
不喜欢关键词：每个 -2
```

这些反馈不会替代 `profile.json`，而是作为“后续微调偏好”叠加在原评分规则上。

## 6. 数据库表

SQLite 里目前有这些核心表：

```text
runs            # 每次运行的总体状态
news_items      # 新闻、去重、评分、embedding、入选结果
reports         # Markdown 报告正文和自查结果
source_errors   # RSS 来源失败记录
user_feedback   # 每次运行使用的反馈规则快照
```

## 7. 代码结构

```text
catch_ai.py                  # 命令行入口
sources.json                 # RSS 资讯源配置
profile.json                 # 用户偏好配置
feedback.json                # 用户反馈配置
ai_report_agent/
  agent.py                   # 串联完整日报流程
  config.py                  # 配置和 .env 读取
  critic.py                  # 报告质量自查和修订
  database.py                # SQLite 长期记忆、反馈快照、向量 RAG 检索
  deduplicator.py            # 资讯去重
  deepseek_client.py         # DeepSeek API 调用
  embeddings.py              # 本地 embedding 和余弦相似度
  feedback.py                # 用户反馈读取
  profile.py                 # 用户偏好读取
  report.py                  # Markdown 报告生成
  scorer.py                  # 热点评分筛选，叠加用户反馈
  scheduler.py               # 每日定时调度
  sources.py                 # RSS 热点源采集和解析
  state.py                   # 运行状态记录
```

## 8. 常见问题

如果提示缺少 `DEEPSEEK_API_KEY`，请检查 `version4/.env` 是否存在，并确认 Key 已填写。

如果你想观察 RAG 是否生效，可以打开 `data/debug/*final_report_prompt.md`，搜索：

```text
历史检索上下文
```

如果里面出现“向量检索找到的相关历史资讯”，说明 v4 的向量 RAG 已经命中历史内容。
