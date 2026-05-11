"""事件聚类模块。

Version 6 的核心优化是：从“新闻条目级日报”升级为“事件级日报”。

RSS 里经常会出现多条新闻在讲同一件事：
- 官方博客发布产品
- 科技媒体跟进报道
- 另一个来源补充商业影响

如果直接把新闻条目送给 LLM，日报容易重复。
这里用 BGE embedding 的余弦相似度，把相似新闻合并成事件。
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
