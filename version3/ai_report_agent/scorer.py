"""热点评分模块。

这个模块让 agent 在调用 LLM 前先做一轮“偏好感知”的粗筛。
它不是替代 DeepSeek，而是帮 DeepSeek 少看低价值内容，把注意力集中在 AI 应用热点上。
"""

from __future__ import annotations

# dataclass 用来定义评分后的资讯数据结构。
from dataclasses import dataclass

# UserProfile 保存用户偏好。
from ai_report_agent.profile import UserProfile

# NewsItem 是采集模块输出的标准资讯条目。
from ai_report_agent.sources import NewsItem


# 这些关键词代表“应用、产品、工具、商业落地”等信号。
# 命中越多，说明资讯越符合这个 agent 的日报方向。
APPLICATION_KEYWORDS = [
    "app",
    "application",
    "agent",
    "workflow",
    "product",
    "tool",
    "assistant",
    "enterprise",
    "business",
    "launch",
    "feature",
    "应用",
    "产品",
    "工具",
    "智能体",
    "工作流",
    "办公",
    "企业",
    "商业",
    "发布",
    "功能",
    "创作者",
]


@dataclass(frozen=True)
class ScoredNewsItem:
    """带评分和理由的资讯条目。"""

    # 原始资讯条目。
    item: NewsItem

    # 评分数值，越高越优先进入 DeepSeek 分析。
    score: int

    # 为什么得到这个分数，写入 state 日志便于复盘。
    reasons: list[str]


def item_text(item: NewsItem) -> str:
    """把一条资讯合并成用于关键词匹配的文本。"""
    # 把标题、摘要、类别、来源合并后转小写，方便做大小写不敏感匹配。
    return f"{item.title} {item.summary} {item.category} {item.source}".lower()


def score_item(item: NewsItem, profile: UserProfile) -> ScoredNewsItem:
    """根据用户偏好和应用关键词给单条资讯打分。"""
    # text 是后续关键词匹配的统一文本。
    text = item_text(item)

    # score 从 0 开始，命中正向信号加分，命中避开项扣分。
    score = 0

    # reasons 记录加减分原因。
    reasons: list[str] = []

    # 来源类别符合偏好时，加 3 分。
    if item.category in profile.preferred_categories:
        score += 3
        reasons.append(f"来源类别符合偏好：{item.category}")

    # 检查用户兴趣词是否出现在资讯文本中。
    matched_interests = [word for word in profile.interests if word.lower() in text]

    # 每命中一个兴趣词加 2 分。
    if matched_interests:
        score += 2 * len(matched_interests)
        reasons.append(f"匹配兴趣：{', '.join(matched_interests)}")

    # 检查是否包含应用/产品相关关键词。
    matched_application_words = [word for word in APPLICATION_KEYWORDS if word.lower() in text]

    # 应用信号最多加 4 分，避免单条资讯因为关键词堆叠过度加分。
    if matched_application_words:
        score += min(4, len(matched_application_words))
        reasons.append("包含应用/产品信号")

    # 检查是否命中用户不希望重点关注的内容。
    matched_avoid = [word for word in profile.avoid if word.lower() in text]

    # 每命中一个避开词扣 3 分。
    if matched_avoid:
        score -= 3 * len(matched_avoid)
        reasons.append(f"命中降权词：{', '.join(matched_avoid)}")

    # 研究论文来源默认降权，因为这个 agent 更关注应用落地。
    if item.category == "研究论文":
        score -= 2
        reasons.append("研究论文来源降权")

    # 如果没有任何信号，也写入一个原因，避免日志空白。
    if not reasons:
        reasons.append("没有明显偏好信号")

    # 返回带分数和解释的结构化对象。
    return ScoredNewsItem(item=item, score=score, reasons=reasons)


def score_items(items: list[NewsItem], profile: UserProfile) -> list[ScoredNewsItem]:
    """给资讯列表评分，并按分数从高到低排序。"""
    # 先给每条资讯打分。
    scored = [score_item(item, profile) for item in items]

    # 再按 score 倒序排列，让高价值内容排在前面。
    return sorted(scored, key=lambda entry: entry.score, reverse=True)


def select_items_for_analysis(
    scored_items: list[ScoredNewsItem],
    min_score: int,
    max_items: int,
) -> list[ScoredNewsItem]:
    """选择进入 DeepSeek 分析的资讯，保证至少有一批内容可分析。"""
    # 优先选择达到最低分阈值的资讯。
    selected = [entry for entry in scored_items if entry.score >= min_score]

    # 如果没有任何资讯达到阈值，就退回使用全部资讯，避免后续没有内容可分析。
    if not selected:
        selected = scored_items

    # max_items > 0 时限制最多进入 DeepSeek 的条数。
    if max_items > 0:
        return selected[:max_items]

    # max_items <= 0 表示不限制数量。
    return selected
