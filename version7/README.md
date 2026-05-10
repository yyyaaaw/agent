# 本地 AI 热点日报 Agent - Version 7

Version 7 在 Version 6 的事件聚类和事件级 RAG 基础上，新增真正的用户反馈闭环。

## 新增能力

- `--feedback`：对最近一次日报事件进行交互式反馈。
- `event_feedback` 表：保存真实用户反馈。
- 反馈结束后会自动更新 `feedback.json`。
- 下次运行日报时，agent 直接读取更新后的 `feedback.json` 参与评分。

## 运行日报

```powershell
cd C:\Users\18352\Desktop\agent\version7
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --run-once
```

## 提交反馈

日报运行完成后，执行：

```powershell
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --feedback
```

程序会列出最近一次日报的事件：

```text
1. OpenAI 语音 Agent 能力更新
2. NVIDIA 物理 AI 仿真进展
3. AI 公司融资动态
```

然后你可以输入：

```text
喜欢哪些事件？1,2
不喜欢哪些事件？3
备注：融资类少写，工具类多写
```

这些反馈会保存到 SQLite 的 `event_feedback` 表，同时自动汇总写回 `feedback.json`。

## 反馈如何影响下一次评分

下次运行日报时：

```text
--feedback
  -> event_feedback 保存原始反馈
  -> 自动更新 feedback.json
--run-once
  -> 读取 feedback.json
  -> 转成 FeedbackRules
  -> scorer.py 加分/扣分
```

例如：

- 你多次喜欢 “OpenAI 语音 Agent” 相关事件
- 系统会从事件标题、来源、类别中提取偏好，并写入 `feedback.json`
- 下次类似来源/类别/关键词会更容易加分

## 数据库

默认数据库：

```text
data/agent_v7.sqlite3
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

仍然使用本地 BGE-M3：

```text
EMBEDDING_PROVIDER=bge
EMBEDDING_MODEL_PATH=E:\Agent_zr\embedding_model\bge-m3
DATABASE_PATH=data/agent_v7.sqlite3
```

## 注意

`profile.json` 适合写长期稳定的初始偏好，例如你关注 AI 应用、办公自动化、智能体。
`feedback.json` 适合保存运行过程中学到的偏好，它会被 `--feedback` 自动更新，也可以手动微调。
`event_feedback` 保存每次原始交互记录，方便之后追溯 agent 是从哪些反馈里学到这些规则的。
