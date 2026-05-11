# 本地 AI 热点日报 Agent - Version 2

这是第二版 agent：在 Version 1 的“固定脚本工作流 + DeepSeek API 分析”基础上，增加了用户偏好、去重、评分筛选、运行状态记录和报告质量自查。

当前版本目录：

```text
C:\Users\18352\Desktop\agent\version2
```

这个项目会在本地笔记本上定时收集 AI 热点资讯，按你的偏好筛选 AI 应用热点，调用 DeepSeek API 做中文分析，并生成 Markdown 汇报。

## Version 2 新增能力

- `profile.json`：记录你的阅读偏好，比如更关注 AI 应用、办公效率、企业落地
- `deduplicator.py`：去掉链接或标题明显重复的资讯
- `scorer.py`：根据用户偏好和应用关键词给资讯打分
- `state.py`：保存本次运行的决策轨迹到 `data/runs`
- `critic.py`：报告生成后做质量自查；如果检查失败，会让 DeepSeek 修订报告

## 1. 准备环境

确认 VSCode 里使用 Python 3.10 或更高版本。本项目只使用 Python 标准库，不需要安装第三方依赖。

## 2. 配置 DeepSeek API Key

复制 `.env.example` 为 `.env`，然后把 `DEEPSEEK_API_KEY` 改成你自己的 Key。

```text
DEEPSEEK_API_KEY=sk-你的真实key
```

## 3. 立即运行一次

在 VSCode 终端执行：

```bash
python catch_ai.py --run-once
```

如果你的终端当前在总目录 `C:\Users\18352\Desktop\agent`，也可以执行：

```bash
python version2\catch_ai.py --run-once
```

成功后会生成：

- `reports/ai_hotspots_YYYY-MM-DD.md`：最终日报
- `data/raw/ai_news_raw_YYYY-MM-DD.json`：原始采集数据

## 4. 配置资讯源

资讯源已经独立放在 `sources.json` 中。每个来源包含：

```json
{
  "name": "TechCrunch AI",
  "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
  "category": "应用与商业",
  "enabled": true
}
```

字段说明：

- `name`：日报中显示的来源名称
- `url`：RSS 地址
- `category`：来源类别，用来帮助 DeepSeek 判断内容类型
- `enabled`：是否启用，改成 `false` 就会临时跳过

当前默认更偏 AI 应用和产品动态，包括 OpenAI、DeepMind、Microsoft AI、NVIDIA AI、VentureBeat AI、TechCrunch AI、The Decoder、MIT Technology Review AI，以及少量 arXiv 论文源。

如果你希望减少论文内容，可以把 `sources.json` 里 `Arxiv CS AI` 的 `enabled` 改成 `false`。

## 5. 配置 DeepSeek 模型和分析参数

DeepSeek 相关参数都在 `.env` 中配置：

```text
DEEPSEEK_MODEL=deepseek-chat
PROFILE_FILE=profile.json
RUN_LOG_DIR=data/runs
MAX_ANALYSIS_ITEMS=40
MIN_ITEM_SCORE=2
BATCH_SIZE=20
REQUEST_TIMEOUT=120
DEEPSEEK_TEMPERATURE=0.3
DEEPSEEK_MAX_TOKENS=2500
SHOW_DEEPSEEK_OUTPUT=true
SAVE_DEBUG_PROMPTS=true
```

字段说明：

- `DEEPSEEK_MODEL`：调用的 DeepSeek 模型名称，例如 `deepseek-chat`
- `PROFILE_FILE`：用户偏好配置文件
- `RUN_LOG_DIR`：运行状态日志目录
- `MAX_ANALYSIS_ITEMS`：最多选择多少条资讯进入 DeepSeek 分析
- `MIN_ITEM_SCORE`：进入分析的最低评分阈值
- `BATCH_SIZE`：每次送给 DeepSeek 分析的资讯条数；全部资讯会分批分析，不会只看第一批
- `REQUEST_TIMEOUT`：单次 API 请求最长等待秒数；设为空、`none` 或 `0` 表示一直等待
- `DEEPSEEK_TEMPERATURE`：生成随机性，越低越稳
- `DEEPSEEK_MAX_TOKENS`：单次回复的最大长度
- `SHOW_DEEPSEEK_OUTPUT`：是否在终端打印 DeepSeek 的生成内容
- `SAVE_DEBUG_PROMPTS`：是否把每次发送给 DeepSeek 的提示词保存到 `data/debug`

注意：终端里能看到的是 DeepSeek 的输入、分批进度和生成内容。模型内部隐藏思考过程不一定会通过 API 返回；如果模型响应里包含 `reasoning_content`，程序会一并显示。

## 6. 每天定时运行

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

如果使用 Windows 任务计划程序，建议这样配置：

```text
程序或脚本：
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe

添加参数：
catch_ai.py --run-once

起始于：
C:\Users\18352\Desktop\agent\version2
```

这样生成的日报会保存在：

```text
C:\Users\18352\Desktop\agent\version2\reports
```

## 7. 日报内容取向

DeepSeek 的分析提示词已经调整为“应用优先”：

- 优先关注新产品、新功能、工具、工作流、企业应用、创作者应用
- 论文、算法和底层技术只作为辅助背景
- 技术内容只有在明显影响产品能力或应用场景时才重点写
- 报告会尽量用通俗语言解释“这件事对用户或业务有什么影响”

## 8. 代码结构

```text
catch_ai.py                  # 命令行入口
sources.json                 # 可编辑的 RSS 资讯源配置
profile.json                 # 用户偏好配置
ai_report_agent/
  agent.py                   # 串联完整日报流程
  config.py                  # 配置和 .env 读取
  critic.py                  # 报告质量自查和修订
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

如果提示缺少 `DEEPSEEK_API_KEY`，请检查项目根目录是否存在 `.env`，并确认 Key 已填写。

如果某些资讯源采集失败，日报仍会基于成功采集的内容生成，失败源会记录在报告底部的“采集状态”中。
