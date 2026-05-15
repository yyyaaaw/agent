# 本地 AI 热点日报 Agent - Version 13

Version 13 基于 Version 12，专门解决“RAG/REG 事件级聚合不成功，几乎一个新闻一个事件”的问题。

Version 12 已经修复了 RSS 来源不稳定的问题；Version 13 不继续扩大 RSS 改动，而是集中处理事件粗聚类质量。这样可以清楚区分：输入层由 Version 12 负责，事件理解层由 Version 13 负责。

## 现象

之前运行记录里出现过类似结果：

```text
Event rough clustering: 30 selected items -> 30 candidate events.
LLM 事件整合结果：30 个候选事件 -> 29 个最终事件。
```

还有一次更典型：

```text
Event rough clustering: 40 selected items -> 39 candidate events.
```

这意味着事件聚类几乎没有压缩效果。入选 30 条新闻，粗聚类仍然得到 30 个候选事件，本质上还是“新闻级日报”，不是“事件级日报”。

## 为什么会出现这个问题

### 1. 旧版只依赖 embedding 单阈值

旧版 `cluster_scored_items` 的核心逻辑是：

```text
如果新闻 embedding 和已有事件 embedding 的余弦相似度 >= 0.78，就加入已有事件；
否则创建新事件。
```

这个策略的问题是：科技新闻里，同一个事件经常会被不同来源从不同角度报道。

例如：

- 官方公告：OpenAI 发布 GPT-5.5。
- 媒体解读：GPT-5.5 输入成本上涨。
- 安全文章：GPT-5.5-Cyber 被用于安全访问场景。

这些新闻可能都围绕同一产品进展，但标题、摘要和叙述角度差异很大，纯 embedding 相似度不一定能超过 0.78。

### 2. 阈值太保守

`0.78` 对“重复新闻”比较合适，但对“同一事件的不同角度报道”太高。

事件级聚合需要的不是只找重复，而是把“同一主体、同一时间段、同一核心进展”的多篇报道归到一起。这个任务天然比去重更宽。

### 3. 贪心聚类容易错过链式关系

旧版是按分数从高到低逐条处理。每条新闻只尝试加入已有事件。

如果 A 和 B 相似，B 和 C 相似，但 A 和 C 不够相似，贪心逻辑可能无法稳定把 A/B/C 放到同一个候选事件里。

Version 13 改用“成对判断 + 并查集”，只要 A-B、B-C 能连起来，就能形成一个候选事件簇。

### 4. LLM 二次合并太晚

旧版虽然有 LLM 事件整合，但它拿到的是粗聚类结果。如果粗聚类已经把 30 条新闻拆成 30 个单条候选事件，LLM 就只能在一堆“孤立单条”之间尝试合并。

LLM 不是不能合并，而是它看到的候选结构太差：候选事件没有把相邻新闻先召回到一起。

所以真正的问题发生在 LLM 之前。

## 修改方案

Version 13 把粗聚类从“纯 embedding 阈值”升级为“混合特征事件聚类”。

修改文件：

```text
ai_report_agent/events.py
ai_report_agent/agent.py
ai_report_agent/config.py
README.md
```

## 核心改动一：重写 events.py

新文件：

```text
ai_report_agent/events.py
```

旧版逻辑：

```text
embedding 相似度 >= 0.78 -> 合并
否则 -> 新建事件
```

新版逻辑：

```text
抽取每条新闻的事件特征
    -> 计算两两新闻的混合相似度
    -> 根据规则判断是否属于同一候选事件
    -> 用并查集合并连通新闻
    -> 生成候选事件
    -> 交给 LLM 做二次整合和命名
```

## 核心改动二：新增实体抽取

新版会从标题和摘要里抽取公司、产品、模型等实体。

示例实体：

```text
OpenAI
GPT-5.5
Codex
Anthropic
Claude
Google DeepMind
Gemini
Microsoft
NVIDIA
Rubin
ByteDance
Palo Alto Networks
METR
```

原因：事件聚合最重要的问题不是“两个句子语义像不像”，而是“两个新闻是否围绕同一个主体”。

例如：

```text
OpenAI 发布 GPT-5.5
GPT-5.5 成本上涨分析
GPT-5.5-Cyber 安全访问案例
```

它们的语义角度不同，但共同实体 `GPT-5.5` 是很强的聚合信号。

## 核心改动三：新增动作类型抽取

新版会抽取新闻动作类型，例如：

```text
发布
开源
定价
安全
融资交易
合作
监管伦理
研究评测
应用案例
```

原因：同一家公司每天可能有很多新闻，只靠公司名会误合并。动作类型可以帮助区分：

```text
Microsoft 开源工具包
Microsoft 企业案例
Microsoft CTO 访谈
```

它们都有 Microsoft，但动作不同，不应该轻易合并。

## 核心改动四：新增关键词重叠

新版会抽取标题和摘要中的区分性关键词，并过滤弱词：

```text
ai
model
agent
new
tool
future
```

这些词太泛，不能用来判断同一事件。

保留的关键词更偏事实，例如：

```text
pricing
codex
rubin
cyber
fellowship
blackmail
```

原因：有些新闻没有明显实体，但标题事实词高度重叠，也可能是同一事件的复述。

## 核心改动五：成对判断 + 并查集合并

新版不再使用贪心聚类，而是对入选新闻做两两判断。

如果两条新闻满足任一条件，就把它们连起来：

1. 语义相似度极高。
2. 共享产品/模型实体，并且语义相似度达到中等水平。
3. 共享实体、共享动作类型，并且语义相似度达到中等水平。
4. 标题事实词高度重叠，并且语义相似度达到中等水平。
5. 混合分达到阈值，并且有实体、动作或关键词上的可解释重叠。

然后用并查集把连通的新闻合并成候选事件。

这样可以处理链式关系：

```text
A 与 B 相似
B 与 C 相似
A 与 C 不够相似
```

旧版可能拆成两个事件，新版会把 A/B/C 放进同一个候选事件。

## 核心改动六：降低默认粗聚类阈值

旧版默认：

```python
similarity_threshold = 0.78
```

新版默认：

```python
similarity_threshold = 0.58
```

注意：新版的 `similarity_threshold` 不再是纯 embedding 阈值，而是混合分阈值。混合分包含：

```text
52% embedding 相似度
24% 实体重叠
14% 动作重叠
10% 关键词重叠
```

所以它不能和旧版 0.78 直接比较。

## 核心改动七：增加事件压缩率记录

`agent.py` 新增了候选事件压缩率记录：

```text
Event rough clustering compression ratio: 1.82 (selected items / candidate events).
```

含义：

```text
事件压缩率 = 入选新闻数 / 候选事件数
```

判断方式：

- 接近 `1.00`：聚类失败，基本一条新闻一个事件。
- `1.30` 以上：开始有压缩效果。
- `2.00` 左右：说明多源报道被较明显地合并。

这个指标会写入：

```text
run_state_*.json
trace_*.json
```

## 默认数据库

Version 13 默认数据库改为：

```text
data/agent_v13.sqlite3
```

原因：避免和 Version 12 的运行数据混在一起，便于对比事件聚类修复前后的效果。

## 如何运行

生成一次日报：

```powershell
cd C:\Users\18352\Desktop\agent\version13
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --run-once
```

运行后重点查看：

```text
data/runs/run_state_*.json
data/traces/trace_*.json
data/agent_v13.sqlite3
```

重点指标：

```text
Event rough clustering: N selected items -> M candidate events.
Event rough clustering compression ratio: X.XX
LLM 事件整合结果：M 个候选事件 -> K 个最终事件。
```

如果看到：

```text
40 selected items -> 25 candidate events
compression ratio: 1.60
```

就说明粗聚类已经比旧版明显改善。

## MCP Server

MCP 用法继承 Version 12：

```powershell
cd C:\Users\18352\Desktop\agent\version13
C:\Users\18352\Desktop\agent\.venv\Scripts\python.exe catch_ai.py --mcp
```

MCP 客户端配置中的路径需要改成 `version13`：

```json
{
  "mcpServers": {
    "ai-report-agent": {
      "command": "C:\\Users\\18352\\Desktop\\agent\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\Users\\18352\\Desktop\\agent\\version13\\catch_ai.py",
        "--mcp"
      ],
      "cwd": "C:\\Users\\18352\\Desktop\\agent\\version13"
    }
  }
}
```

## 这次修改没有做什么

本版没有修改 RSS 采集。RSS 自愈逻辑沿用 Version 12。

本版没有把 LLM 改成“可拆分事件”。当前 LLM 二次整合仍然主要负责合并候选事件和生成标题。如果粗聚类过度合并，LLM 现在还不能把一个候选事件拆回多个事件。

因此 Version 13 的规则故意保留了防误合并条件：

- 只有同公司但没有共同动作，不轻易合并。
- 没有实体、动作或关键词交集，不只凭低语义相似度合并。
- 共享泛词如 `AI`、`model`、`agent` 不算强证据。

## 后续建议

如果 Version 13 运行后压缩率仍然低，可以继续做三件事：

1. 扩充实体词典：把经常出现的公司、产品、模型加入 `KNOWN_ENTITY_PATTERNS`。
2. 调整动作词典：把常见新闻动词加入 `ACTION_KEYWORDS`。
3. 引入 LLM 事件裁判：让模型不仅合并候选事件，也能判断候选事件内部是否需要拆分。

如果 Version 13 出现误合并，则优先调高 `similarity_threshold`，例如从 `0.58` 调到 `0.62`。

## 面试/简历表述建议

可以这样描述 Version 13：

> 针对 AI 日报 Agent 中“事件聚类退化为新闻级列表”的问题，将原本单一 embedding 阈值聚类升级为实体、动作类型、关键词重叠和语义向量融合的事件候选召回，并使用并查集合并连通新闻簇，同时新增事件压缩率指标用于评估事件级聚合效果。

## 问题、解决思路以及测试

q：v12 的运行记录里还有一条典型的失败：40 selected items -> 39 candidate events。这说明问题发生在 LLM 之前：粗聚类几乎没有给模型提供“可合并候选”，后面的 LLM 只能在一堆单条事件里小修小补。

a: 重写事件粗聚类为“embedding + 实体 + 动作 + 关键词重叠”的混合聚类，而不是只靠 0.78 的向量阈值

t: 一个本地聚类样例：用几条模拟新闻验证 GPT-5.5 相关内容能聚成同一候选事件，而 Microsoft 不同主题不会被粗暴合并。

q: 本地样例暴露出一个很有用的问题：新版把两个 Microsoft 但主题不同的应用类新闻合并了，说明“同一公司 + 应用案例”这个信号还是太宽。

a: 马上收紧规则：应用案例属于弱动作，不能只靠同公司合并，必须再有更强的产品实体、关键词重叠或更高语义相似度。

t: 修正后样例结果符合预期：GPT-5.5 两条合并，两个 Microsoft 不同主题保持独立。接下来我用已有 v12 历史数据库里的一次真实 selected 新闻做离线对比，不调用 DeepSeek，只看新版粗聚类能把候选事件数压下来多少。

q: 真实数据对比显示新版确实从 40 -> 12，但出现了一个过合并：27 条 NVIDIA 相关新闻被吸成一个大事件。这正好说明事件聚合需要“高召回，但不能让大公司名变成黑洞”。

a: 继续收紧规则：NVIDIA/OpenAI/Microsoft 这类高频公司名只作为弱实体；如果没有具体产品、模型、动作和事实词支撑，不允许通过链式关系吞掉一整批新闻。

q: 大簇的原因找到了：一些长摘要里同时提到 Codex、NVIDIA、agentic、released 等高频词，链式合并把多个本来不同的新闻串到一起了。

a: 把产品实体规则再收紧：像 Codex 这种可能出现在很多案例里的实体，不能单独作为合并依据，必须同时有更高语义相似度、共同动作或更多事实词。

t: 现在的真实历史数据离线对比是 40 -> 23，压缩率 1.74，比旧版 40 -> 39 明显改善；同时我避免了刚才那种 27 条大团的过合并。

总结：这次主要解决事件聚合失败的根因：旧版只靠 embedding >= 0.78 做粗聚类，太像“重复新闻检测”，不是“事件归并”。所以常见结果会变成 40 selected -> 39 candidate events，LLM 后面也救不回来。
