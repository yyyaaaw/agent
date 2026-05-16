# 本地 AI 热点日报 Agent - Version 12

Version 12 基于 Version 11，优先解决 RSS 采集不稳定的问题。

上一版的 RSS 采集逻辑比较“硬”：每个来源只访问 `sources.json` 里配置的一个 RSS 地址。实际运行中已经出现过：

- `Google DeepMind Blog: HTTP Error 404`
- `VentureBeat AI: HTTP Error 308`

这说明有些站点的 feed 地址会变化，有些站点会做永久重定向，还有些站点的分类 RSS 可能临时不可用。Version 12 的目标是让 agent 在这些常见失败场景里具备一定自愈能力。

## 本版改动总览

本版主要修改以下文件：

- `ai_report_agent/sources.py`
- `sources.json`
- `ai_report_agent/config.py`
- `README.md`

没有修改事件聚类、RAG、评分、报告生成、MCP Server 等主流程。

## 为什么先改 RSS

RSS 是整个日报 agent 的第一层输入。如果信息源不稳定，后续评分、事件聚类、RAG 和报告生成都会被影响。

旧逻辑的问题是：

1. 一个来源只有一个固定 RSS URL。
2. URL 404、308、解析失败时，只能记录失败，不能继续找替代地址。
3. agent 没有记忆：上次某个新地址成功了，下次仍然从旧地址开始。
4. `sources.json` 缺少来源主页和备用 RSS 信息，无法支持自动发现。

因此 Version 12 先把 RSS 从“固定 URL 抓取”升级成“可恢复的信息源采集”。

## 新增能力一：备用 RSS 地址

`sources.json` 新增两个字段：

```json
{
  "name": "VentureBeat AI",
  "url": "https://venturebeat.com/category/ai/feed/",
  "homepage_url": "https://venturebeat.com/category/ai/",
  "fallback_urls": [
    "https://venturebeat.com/category/ai/feed",
    "https://venturebeat.com/feed/"
  ],
  "category": "应用与商业",
  "enabled": true
}
```

字段含义：

- `url`：主 RSS 地址，仍然优先尝试。
- `homepage_url`：来源主页，用来自动发现 RSS/Atom feed。
- `fallback_urls`：人工维护的备用 RSS 地址。

这样做的原因是：有些网站的分类 RSS 不稳定，但全站 RSS 仍然可用；有些网站带 `/` 和不带 `/` 的地址行为不同；有些旧地址会重定向到新地址。

## 新增能力二：自动发现 RSS/Atom

新版 `sources.py` 中新增了 `FeedLinkParser`。

当主 RSS 和备用 RSS 不稳定时，agent 会访问 `homepage_url`，从 HTML 里寻找类似下面的标签：

```html
<link rel="alternate" type="application/rss+xml" href="/feed/">
<link rel="alternate" type="application/atom+xml" href="/atom.xml">
```

发现到的相对路径会自动转换成完整 URL。

这样做的原因是：很多站点会调整 RSS 地址，但通常仍会在页面 head 里暴露机器可读 feed。让 agent 自动读取这些声明，比长期手动维护 URL 更稳。

## 新增能力三：常见路径兜底

如果主页没有声明 RSS/Atom，agent 会继续尝试常见路径：

```text
/feed/
/rss.xml
/atom.xml
/feed.xml
/blog/feed/
```

这样做的原因是：不少博客系统和 CMS 使用固定 feed 路径，即使页面没有显式声明，也可能能访问。

## 新增能力四：来源健康状态记忆

Version 12 会新增并自动维护：

```text
data/source_health.json
```

示例结构：

```json
{
  "VentureBeat AI": {
    "source_name": "VentureBeat AI",
    "configured_url": "https://venturebeat.com/category/ai/feed/",
    "working_url": "https://venturebeat.com/feed/",
    "last_status": "success",
    "last_success_at": "2026-05-14 10:30:00",
    "last_error": "",
    "last_item_count": 8,
    "success_count": 3,
    "failure_count": 1,
    "consecutive_failures": 0
  }
}
```

下次运行时，agent 会优先尝试 `working_url`。如果这个地址继续成功，就不用每次都从旧地址开始失败一遍。

这样做的原因是：RSS 自愈不应该只发生在一次运行内，还应该成为 agent 的长期运行经验。

## 新增能力五：更详细的失败记录

旧版错误通常类似：

```text
VentureBeat AI: HTTP Error 308: Permanent Redirect
```

新版会记录每个候选地址的尝试结果，例如：

```text
VentureBeat AI: https://venturebeat.com/category/ai/feed/ -> HTTP 308: Permanent Redirect；
https://venturebeat.com/feed/ -> 解析成功但没有发现新闻条目；
https://venturebeat.com/rss.xml -> HTTP 404: Not Found
```

这样做的原因是：排查 RSS 问题时，单个错误码不够。我们需要知道 agent 试过哪些地址、每个地址为什么失败。

## 采集流程

Version 12 对单个来源的采集顺序如下：

```text
读取 source_health.json 中上次成功的 working_url
    -> 尝试 sources.json 的主 url
    -> 尝试 fallback_urls
    -> 访问 homepage_url，自动发现 RSS/Atom
    -> 尝试常见 feed 路径
    -> 任一候选成功解析出新闻，就记录成功并停止
    -> 全部失败，记录详细错误并更新连续失败次数
```

注意：只有“成功解析出新闻条目”才算来源成功。仅仅 HTTP 200 但不是 feed，或者 XML 里没有新闻条目，都不会被当作成功。

## 和 Version 11 的兼容性

`collect_news(...)` 的返回值保持不变：

```python
tuple[list[NewsItem], list[str]]
```

因此主流程 `agent.py` 不需要改。

`sources.json` 也兼容旧格式。如果某个来源没有配置 `homepage_url` 或 `fallback_urls`，程序会自动使用空值和默认推断逻辑。

## 默认数据库

Version 12 默认数据库改为：

```text
data/agent_v12.sqlite3
```

修改位置：

```text
ai_report_agent/config.py
```

这样做是为了避免 Version 12 的运行数据和 Version 11 混在一起，方便对比 RSS 修复前后的效果。

## 如何运行

生成一次日报：

```powershell
cd C:\Users\18352\Desktop\agent\version12
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --run-once
```

只想快速观察 RSS 是否恢复，可以运行完整日报后查看：

```text
data/source_health.json
data/runs/run_state_*.json
data/traces/trace_*.json
```

重点看：

- `source_health.json` 中哪些来源成功了。
- `run_state_*.json` 里的 `errors` 是否减少。
- trace 里的 `collect_news.source_errors` 是否下降。

## MCP Server

MCP 用法继承 Version 11：

```powershell
cd C:\Users\18352\Desktop\agent\version12
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --mcp
```

MCP 客户端配置中的路径需要从 `version11` 改成 `version12`：

```json
{
  "mcpServers": {
    "ai-report-agent": {
      "command": "C:\\Users\\18352\\Desktop\\agent\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\Users\\18352\\Desktop\\agent\\version12\\catch_ai.py",
        "--mcp"
      ],
      "cwd": "C:\\Users\\18352\\Desktop\\agent\\version12"
    }
  }
}
```

## 本次没有改什么

本版没有解决“一个新闻一个事件”的事件聚类问题。这个问题仍然存在于事件聚类和 LLM 二次归并阶段，后续应该单独处理。

这样拆分的原因是：RSS 是输入层问题，事件聚类是理解层问题。两个问题同时改，后续很难判断效果来自哪一部分。

## 后续建议

RSS 修复后，可以连续运行几次，观察 `source_health.json` 和 trace 指标。

如果某个来源连续失败很多次，可以考虑：

- 在 `sources.json` 中补充更准确的 `homepage_url`。
- 添加新的 `fallback_urls`。
- 暂时把该来源 `enabled` 设置为 `false`。
- 增加搜索 API 或网页抓取作为非 RSS fallback。

等 RSS 输入稳定后，再进入 Version 13，集中修复事件级聚类问题。
