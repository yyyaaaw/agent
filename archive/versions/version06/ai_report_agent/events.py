"""事件聚类模块。

Version 6 的核心优化是：从“新闻条目级日报”升级为“事件级日报”。

RSS 里经常会出现多条新闻在讲同一件事：
- 官方博客发布产品
- 科技媒体跟进报道
- 另一个来源补充商业影响

如果直接把新闻条目送给 LLM，日报容易重复。
这里用 BGE embedding 的余弦相似度，把相似新闻合并成事件。
"""

"""
用一个示例讲解如何把新闻聚合成一个event：

假设今天筛选后有 5 条新闻：
新闻 A：
标题：OpenAI launches realtime voice agents
摘要：OpenAI 发布实时语音智能体，可用于客服和会议。

新闻 B：
标题：AI voice support agents become more natural
摘要：新的语音客服智能体可以处理客户电话。

新闻 C：
标题：Parloa builds service agents with OpenAI
摘要：Parloa 使用 OpenAI 模型构建企业客服代理。

新闻 D：
标题：NVIDIA improves robotics simulation
摘要：NVIDIA 发布物理 AI 仿真技术，用于机器人训练。

新闻 E：
标题：New GPU platform for autonomous driving
摘要：NVIDIA 发布自动驾驶相关 GPU 平台。


人的直觉会这样分：
事件 1：AI 语音客服 / 语音智能体
- 新闻 A
- 新闻 B
- 新闻 C

事件 2：NVIDIA 物理 AI / 自动驾驶 / 仿真
- 新闻 D
- 新闻 E

event.py代码就是在模拟这个过程。

关键函数在 cluster_scored_items()，它会：
1. 按新闻分数从高到低排序
2. 逐条拿新闻出来
3. 把新闻转成 embedding 向量
4. 和已有 event 的向量比较相似度
5. 相似度高，就加入已有 event
6. 相似度低，就创建新 event
最后得到的事件列表会按重要程度排序（最高分和平均分），方便后续生成日报。

比如第一条新闻 A：OpenAI launches realtime voice agents
- 转成向量后没有事件，创建事件 1，包含 A。
事件 1 的 embedding 就大概代表：OpenAI + realtime voice + agents + customer service

第二条新闻 B：AI voice support agents become more natural
代码会把新闻 B 也转成 embedding，然后和事件 1 的 embedding 算余弦相似度。
因为它们都在说：
voice
agents
customer support
所以相似度会很高，超过阈值，就把 B 加入事件 1。（代码中的阈值默认是similarity_threshold = 0.78）
然后事件 1 的 embedding 会重新计算，让它同时代表 A 和 B。

第三条新闻 C：Parloa builds service agents with OpenAI
它虽然标题不完全一样，但语义上仍然是：
企业客服 agent
OpenAI
service agents
所以它和事件 1 的相似度也会很高，也会被归入事件 1。

第四条新闻 D：NVIDIA improves robotics simulation
和事件1比较：语音客服 vs 机器人仿真
相似度会很低，不会加入事件 1。
因为没有其他事件了，所以它会创建事件 2，包含 D。

第五条新闻 E：New GPU platform for autonomous driving
和事件 1 比较：语音客服 vs GPU 自动驾驶，相似度很低，不加入事件 1。
和事件 2 比较：自动驾驶/GPU vs 机器人仿真/物理 AI，相似度可能比较高。

代码中的关键点：
每条新闻转成 embedding，也就是把：标题 + 摘要 + 类别 + 来源，拼成一段文本，送入 bge-m3 模型生成向量。
和每个事件的 embedding 比较，计算余弦相似度。如果它和多个事件都像，就选最像的那个加入。
事件的 embedding 是由它包含的所有新闻重新生成的，这样它能更好地代表这个事件的语义。比如事件 1 的 embedding 就会同时包含 A、B、C 的信息。
最后生成 NewsEvent 对象，events = [build_event(index + 1, cluster) for index, cluster in enumerate(clusters)]
build_event() 会生成：
event_id
title
summary
scored_items
embedding
average_score
max_score
sources
categories
representative_link
比如事件1：
event_id: event_1
title: OpenAI launches realtime voice agents
sources: OpenAI Blog, The Decoder, TechCrunch AI
categories: 产品与模型, 应用与产品, 应用与商业
max_score: 10
average_score: 8.7
representative_link: https://...

事件标题怎么来的？
目前很简单：使用最高分新闻的标题作为事件标题。
以后可以优化成让 LLM 给事件起一个更自然的标题，比如：OpenAI 语音 Agent 与企业客服落地加速。
"""

from __future__ import annotations

# dataclass 用来定义事件结构。
from dataclasses import dataclass

# cosine_similarity / embed_text 用于计算事件向量和新闻向量的相似度。
from ai_report_agent.embeddings import cosine_similarity, embed_text

# ScoredNewsItem 是带评分和理由的资讯条目。
from ai_report_agent.scorer import ScoredNewsItem

# NewsItem 是原始资讯结构。
from ai_report_agent.sources import NewsItem


@dataclass
class NewsEvent:
    """聚类后的事件。"""

    # 事件 ID，只在本次运行内使用。
    event_id: str

    # 事件标题，默认使用最高分新闻的标题。
    title: str

    # 事件摘要，由多条新闻标题和摘要拼接压缩而来。
    summary: str

    # 事件包含的评分新闻。
    scored_items: list[ScoredNewsItem]

    # 事件向量，用于后续事件级 RAG。
    embedding: list[float]

    # 事件平均分。
    average_score: float

    # 事件最高分。
    max_score: int

    # 事件来源列表。
    sources: list[str]

    # 事件类别列表。
    categories: list[str]

    # 代表链接，通常是最高分新闻的链接。
    representative_link: str


def item_event_text(item: NewsItem) -> str:
    """把一条新闻整理成用于事件聚类的文本。"""
    # 标题和摘要是主要语义；类别和来源提供少量上下文。
    return f"{item.title} {item.summary} {item.category} {item.source}"


def event_summary_text(items: list[ScoredNewsItem]) -> str:
    """生成事件摘要文本。"""
    # 取前几条新闻拼接，避免摘要过长。
    parts = []
    for entry in items[:4]:
        parts.append(f"{entry.item.title}：{entry.item.summary[:180]}")

    # 用换行连接，方便 prompt 阅读。
    return "\n".join(parts)


def unique_preserve_order(values: list[str]) -> list[str]:
    """去重但保持原始顺序。"""
    # dict.fromkeys 会保留插入顺序。
    return list(dict.fromkeys(value for value in values if value))


def build_event(event_index: int, items: list[ScoredNewsItem]) -> NewsEvent:
    """根据一组评分新闻构造事件对象。"""
    # 按分数从高到低排序，最高分新闻作为事件代表。
    sorted_items = sorted(items, key=lambda entry: entry.score, reverse=True)

    # 代表新闻。
    representative = sorted_items[0]

    # 事件语义文本。
    event_text = " ".join(item_event_text(entry.item) for entry in sorted_items)

    # 用 BGE 生成事件向量。
    embedding = embed_text(event_text)

    # 分数列表。
    scores = [entry.score for entry in sorted_items]

    # 来源列表。
    sources = unique_preserve_order([entry.item.source for entry in sorted_items])

    # 类别列表。
    categories = unique_preserve_order([entry.item.category for entry in sorted_items])

    # 返回事件对象。
    return NewsEvent(
        event_id=f"event_{event_index}",
        title=representative.item.title,
        summary=event_summary_text(sorted_items),
        scored_items=sorted_items,
        embedding=embedding,
        average_score=sum(scores) / len(scores),
        max_score=max(scores),
        sources=sources,
        categories=categories,
        representative_link=representative.item.link,
    )


def cluster_scored_items(
    scored_items: list[ScoredNewsItem],
    similarity_threshold: float = 0.78,
) -> list[NewsEvent]:
    """把评分新闻聚成事件。

    逻辑：
    1. 按新闻分数从高到低处理。
    2. 每条新闻和已有事件比较相似度。
    3. 相似度超过阈值就加入该事件。
    4. 否则创建新事件。
    """
    # 事件桶，先用 list[list[ScoredNewsItem]] 表示。
    clusters: list[list[ScoredNewsItem]] = []

    # 每个事件桶的向量，用于快速比较。
    cluster_embeddings: list[list[float]] = []

    # 高分新闻优先成为事件代表。
    sorted_items = sorted(scored_items, key=lambda entry: entry.score, reverse=True)

    # 逐条分配到事件桶。
    for entry in sorted_items:
        # 生成当前新闻向量。
        item_embedding = embed_text(item_event_text(entry.item))

        # 默认没有匹配事件。
        best_index = -1
        best_similarity = 0.0

        # 和已有事件逐个比较。
        for index, cluster_embedding in enumerate(cluster_embeddings):
            similarity = cosine_similarity(item_embedding, cluster_embedding)
            if similarity > best_similarity:
                best_similarity = similarity
                best_index = index

        # 相似度足够高，加入已有事件。
        if best_index >= 0 and best_similarity >= similarity_threshold:
            clusters[best_index].append(entry)

            # 更新事件向量：简单用加入后的所有新闻重新生成事件向量。
            merged_text = " ".join(item_event_text(item.item) for item in clusters[best_index])
            cluster_embeddings[best_index] = embed_text(merged_text)

        # 相似度不够高，创建新事件。
        else:
            clusters.append([entry])
            cluster_embeddings.append(item_embedding)

    # 把事件桶转换成 NewsEvent 对象。
    events = [build_event(index + 1, cluster) for index, cluster in enumerate(clusters)]

    # 按最高分和平均分排序，让重要事件排前面。
    return sorted(events, key=lambda event: (event.max_score, event.average_score), reverse=True)


def format_events_for_prompt(events: list[NewsEvent], max_events: int = 12) -> str:
    """把事件列表格式化为 DeepSeek prompt 文本。"""
    # 没有事件时返回提示。
    if not events:
        return "暂无事件。"

    # 逐个事件格式化。
    blocks = []
    for index, event in enumerate(events[:max_events], start=1):
        item_lines = [
            f"- [{entry.item.source}｜{entry.item.category}] {entry.item.title} ({entry.score} 分)"
            for entry in event.scored_items[:5]
        ]
        blocks.append(
            "\n".join(
                [
                    f"## 事件 {index}: {event.title}",
                    f"来源：{', '.join(event.sources)}",
                    f"类别：{', '.join(event.categories)}",
                    f"最高分：{event.max_score}，平均分：{event.average_score:.1f}",
                    f"代表链接：{event.representative_link or '无'}",
                    "相关新闻：",
                    *item_lines,
                    "事件摘要材料：",
                    event.summary or "无",
                ]
            )
        )

    # 事件之间用空行分隔。
    return "\n\n".join(blocks)
