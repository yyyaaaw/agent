# 本地 AI 热点日报 Agent - Version 5

这是第五版 agent：在 Version 4 的 SQLite 长期记忆、反馈评分和向量 RAG 基础上，把 embedding 从“哈希向量”升级为本地部署的 `BAAI/bge-m3` 模型。

当前版本目录：

```text
C:\Users\18352\Desktop\agent\version5
```

## Version 5 新增能力

- 使用本地 `bge-m3` 生成真正语义 embedding。
- 支持中英文混合新闻的语义相似度检索。
- 向量写入 SQLite 的 `news_items.embedding_json` 字段。
- 最终日报生成前，用 BGE 向量检索历史相似新闻作为 RAG 上下文。
- 保留 `hash` embedding 作为可选 fallback，但默认关闭。

## 1. 本地模型路径

当前默认模型路径：

```text
E:\Agent_zr\embedding_model\bge-m3
```

如果你的模型路径不同，请修改 `.env`：

```text
EMBEDDING_MODEL_PATH=你的模型路径
```

## 2. 需要安装的 Python 包

Version 5 需要 `FlagEmbedding`。

在项目虚拟环境中安装：

```bash
python -m pip install -U FlagEmbedding
```

你已经测试通过本地模型后，agent 就可以直接使用。

## 3. 配置文件

`.env` 中和 embedding 相关的配置：

```text
DATABASE_PATH=data/agent_v5.sqlite3
EMBEDDING_PROVIDER=bge
EMBEDDING_MODEL_PATH=E:\Agent_zr\embedding_model\bge-m3
EMBEDDING_USE_FP16=false
EMBEDDING_BATCH_SIZE=8
EMBEDDING_MAX_LENGTH=512
EMBEDDING_FALLBACK_TO_HASH=false
```

字段说明：

- `EMBEDDING_PROVIDER=bge`：使用本地 BGE-M3。
- `EMBEDDING_MODEL_PATH`：本地模型目录。
- `EMBEDDING_USE_FP16=false`：CPU 推荐 false；GPU 可尝试 true。
- `EMBEDDING_BATCH_SIZE=8`：批量生成 embedding 的条数。
- `EMBEDDING_MAX_LENGTH=512`：每条新闻送入 BGE 的最大长度。
- `EMBEDDING_FALLBACK_TO_HASH=false`：BGE 加载失败时是否退回哈希 embedding。默认 false，避免悄悄退化。

## 4. 运行方式

在 `version5` 目录执行：

```bash
python catch_ai.py --run-once
```

如果终端当前在总目录 `C:\Users\18352\Desktop\agent`，可以执行：

```bash
python version5\catch_ai.py --run-once
```

成功后会生成：

- `reports/ai_hotspots_YYYY-MM-DD.md`
- `data/raw/ai_news_raw_YYYY-MM-DD.json`
- `data/runs/run_state_YYYYMMDD_HHMMSS.json`
- `data/agent_v5.sqlite3`

## 5. BGE RAG 如何工作

Version 5 的 RAG 流程：

```text
当天入选新闻
  -> 拼接标题、摘要、类别、来源
  -> 本地 BGE-M3 生成 dense embedding
  -> 写入 SQLite
  -> 查询历史已入选/高分新闻
  -> 读取历史 embedding
  -> 计算余弦相似度
  -> 选出相似历史新闻
  -> 放进 DeepSeek 最终汇总 prompt
```

这比 Version 4 的哈希向量更智能，因为 BGE 能理解语义相近但关键词不同的表达。

例如：

```text
AI voice assistant for customer service
企业客服语音智能体
```

这两句话关键词不完全一样，但 BGE 更可能判断它们语义相近。

## 6. 如何确认 RAG 生效

运行后打开：

```text
data/debug/*final_report_prompt.md
```

搜索：

```text
历史检索上下文
```

如果看到：

```text
以下是向量检索找到的相关历史资讯
```

说明 RAG 命中了历史记录。

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
  database.py                # SQLite 长期记忆、BGE 向量 RAG 检索
  deduplicator.py            # 资讯去重
  deepseek_client.py         # DeepSeek API 调用
  embeddings.py              # 本地 BGE-M3 embedding 和 hash fallback
  feedback.py                # 用户反馈读取
  profile.py                 # 用户偏好读取
  report.py                  # Markdown 报告生成
  scorer.py                  # 热点评分筛选，叠加用户反馈
  scheduler.py               # 每日定时调度
  sources.py                 # RSS 热点源采集和解析
  state.py                   # 运行状态记录
```

## 8. 常见问题

如果提示缺少 `FlagEmbedding`：

```bash
python -m pip install -U FlagEmbedding
```

如果提示模型路径不存在，请检查：

```text
E:\Agent_zr\embedding_model\bge-m3
```

如果你临时想不用 BGE，可在 `.env` 中改成：

```text
EMBEDDING_PROVIDER=hash
```
