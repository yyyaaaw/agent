"""Hotspot scoring module.

The scorer is a deterministic pre-filter before the LLM sees the news. It is
not meant to be a perfect editor, but it should encode the editorial direction
of this project: practical AI applications, useful products, enterprise impact,
domestic/global balance, source diversity, and user feedback.
"""

from __future__ import annotations

import email.utils
import re
from dataclasses import dataclass
from datetime import date, datetime

from ai_report_agent.feedback import FeedbackRules
from ai_report_agent.profile import UserProfile
from ai_report_agent.sources import NewsItem


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
    "launched",
    "release",
    "released",
    "feature",
    "customer",
    "developer",
    "automation",
    "copilot",
    "应用",
    "产品",
    "工具",
    "智能体",
    "工作流",
    "办公",
    "企业",
    "商业",
    "发布",
    "推出",
    "上线",
    "功能",
    "创作者",
    "自动化",
    "落地",
    "客服",
    "开发者",
]

BUSINESS_KEYWORDS = [
    "enterprise",
    "business",
    "customer",
    "pricing",
    "subscription",
    "revenue",
    "startup",
    "partnership",
    "case study",
    "企业",
    "商业",
    "客户",
    "定价",
    "订阅",
    "营收",
    "创业",
    "合作",
    "案例",
    "落地",
]

PRODUCT_KEYWORDS = [
    "launch",
    "release",
    "feature",
    "update",
    "beta",
    "preview",
    "plugin",
    "api",
    "sdk",
    "发布",
    "推出",
    "功能",
    "更新",
    "内测",
    "插件",
    "接口",
    "工具包",
]

RESEARCH_ONLY_KEYWORDS = [
    "paper",
    "benchmark",
    "algorithm",
    "theorem",
    "dataset",
    "arxiv",
    "论文",
    "基准",
    "算法",
    "数据集",
    "数学推导",
]

HIGH_SIGNAL_TAGS = {
    "product",
    "tool",
    "enterprise",
    "developer",
    "agent",
    "model",
    "应用",
    "产品",
    "工具",
    "企业",
    "开发者",
    "国内",
}

SOURCE_TYPE_WEIGHTS = {
    "general_news": 3,
    "general_tech": 3,
    "company": 2,
    "community": 1,
    "research": -2,
}

PREFERRED_DOMESTIC_REGION = "china"


@dataclass(frozen=True)
class ScoredNewsItem:
    """A news item with a deterministic score and human-readable reasons."""

    item: NewsItem
    score: int
    reasons: list[str]


def item_text(item: NewsItem) -> str:
    """Merge item fields into one lowercase text used by keyword matchers."""
    tags = " ".join(getattr(item, "tags", []) or [])
    return f"{item.title} {item.summary} {item.category} {item.source} {tags}".lower()


def match_keywords(text: str, keywords: list[str]) -> list[str]:
    """Return unique keyword matches while preserving keyword order."""
    matches: list[str] = []
    for keyword in keywords:
        normalized = keyword.lower().strip()
        if normalized and normalized in text and keyword not in matches:
            matches.append(keyword)
    return matches


def limited_points(count: int, limit: int) -> int:
    """Clamp a positive match count to a small scoring contribution."""
    return min(limit, max(0, count))


def read_priority(item: NewsItem) -> int:
    """Read source priority from NewsItem, keeping old fixtures compatible."""
    try:
        priority = int(getattr(item, "priority", 3))
    except (TypeError, ValueError):
        priority = 3
    return max(1, min(5, priority))


def parse_published_date(value: str) -> date | None:
    """Parse common RSS date formats into a date."""
    raw = (value or "").strip()
    if not raw:
        return None

    iso_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", raw)
    if iso_match:
        try:
            return datetime.strptime(iso_match.group(1), "%Y-%m-%d").date()
        except ValueError:
            return None

    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    return parsed.date()


def freshness_points(published: str, today: date | None = None) -> tuple[int, str]:
    """Score publication freshness without failing on unknown RSS dates."""
    parsed = parse_published_date(published)
    if parsed is None:
        return 0, "时效性：发布时间未知"

    today = today or date.today()
    age_days = (today - parsed).days
    if age_days < 0:
        return 1, f"时效性：疑似未来日期 {parsed.isoformat()}，仅轻微加分"
    if age_days <= 2:
        return 4, f"时效性：{age_days} 天内"
    if age_days <= 7:
        return 3, f"时效性：{age_days} 天内"
    if age_days <= 14:
        return 1, f"时效性：{age_days} 天内"
    if age_days > 45:
        return -3, f"时效性：超过 45 天"
    return -1, f"时效性：{age_days} 天前"


def source_metadata_points(item: NewsItem) -> tuple[int, list[str]]:
    """Score source type, region, language, priority, and tags."""
    score = 0
    reasons: list[str] = []

    source_type = str(getattr(item, "source_type", "") or "").strip()
    source_type_score = SOURCE_TYPE_WEIGHTS.get(source_type, 0)
    if source_type_score:
        score += source_type_score
        reasons.append(f"来源类型：{source_type} {source_type_score:+d}")

    region = str(getattr(item, "region", "") or "").strip()
    if region == PREFERRED_DOMESTIC_REGION:
        score += 3
        reasons.append("地域平衡：国内来源 +3")

    language = str(getattr(item, "language", "") or "").strip()
    if language == "zh":
        score += 1
        reasons.append("语言覆盖：中文来源 +1")

    priority = read_priority(item)
    priority_score = priority - 3
    if priority_score:
        score += priority_score
        reasons.append(f"来源优先级：{priority} ({priority_score:+d})")

    tags = {str(tag).strip().lower() for tag in (getattr(item, "tags", []) or [])}
    matched_tags = sorted(tags & {tag.lower() for tag in HIGH_SIGNAL_TAGS})
    if matched_tags:
        tag_score = min(2, len(matched_tags))
        score += tag_score
        reasons.append(f"来源标签匹配：{', '.join(matched_tags[:4])} +{tag_score}")

    return score, reasons


def category_points(item: NewsItem, profile: UserProfile) -> tuple[int, list[str]]:
    """Score configured category preference and research downranking."""
    score = 0
    reasons: list[str] = []

    if item.category in profile.preferred_categories:
        score += 3
        reasons.append(f"类别符合偏好：{item.category} +3")

    if item.category == "研究论文":
        score -= 3
        reasons.append("研究论文默认降权 -3")

    return score, reasons


def content_relevance_points(item: NewsItem, profile: UserProfile) -> tuple[int, list[str]]:
    """Score practical relevance from content and user profile."""
    text = item_text(item)
    score = 0
    reasons: list[str] = []

    matched_interests = [word for word in profile.interests if word.lower() in text]
    if matched_interests:
        interest_score = min(8, 2 * len(matched_interests))
        score += interest_score
        reasons.append(f"匹配兴趣：{', '.join(matched_interests[:5])} +{interest_score}")

    matched_application = match_keywords(text, APPLICATION_KEYWORDS)
    if matched_application:
        application_score = limited_points(len(matched_application), 5)
        score += application_score
        reasons.append(f"应用/产品信号：{', '.join(matched_application[:5])} +{application_score}")

    matched_business = match_keywords(text, BUSINESS_KEYWORDS)
    if matched_business:
        business_score = limited_points(len(matched_business), 3)
        score += business_score
        reasons.append(f"商业/落地信号：{', '.join(matched_business[:4])} +{business_score}")

    matched_product = match_keywords(text, PRODUCT_KEYWORDS)
    if matched_product:
        product_score = limited_points(len(matched_product), 3)
        score += product_score
        reasons.append(f"产品变化信号：{', '.join(matched_product[:4])} +{product_score}")

    matched_avoid = [word for word in profile.avoid if word.lower() in text]
    if matched_avoid:
        avoid_score = 4 * len(matched_avoid)
        score -= avoid_score
        reasons.append(f"命中降权词：{', '.join(matched_avoid[:5])} -{avoid_score}")

    matched_research_only = match_keywords(text, RESEARCH_ONLY_KEYWORDS)
    has_application_signal = bool(matched_application or matched_business or matched_product)
    if matched_research_only and not has_application_signal:
        score -= 4
        reasons.append(f"偏研究且缺少应用信号：{', '.join(matched_research_only[:4])} -4")

    return score, reasons


def feedback_points(
    item: NewsItem,
    feedback: FeedbackRules | None,
) -> tuple[int, list[str]]:
    """Apply explicit user feedback rules."""
    if feedback is None:
        return 0, []

    text = item_text(item)
    score = 0
    reasons: list[str] = []

    if item.category in feedback.liked_categories:
        score += 2
        reasons.append(f"反馈加分：喜欢类别 {item.category} +2")

    if item.category in feedback.disliked_categories:
        score -= 4
        reasons.append(f"反馈扣分：不喜欢类别 {item.category} -4")

    if item.source in feedback.liked_sources:
        score += 2
        reasons.append(f"反馈加分：喜欢来源 {item.source} +2")

    if item.source in feedback.disliked_sources:
        score -= 4
        reasons.append(f"反馈扣分：不喜欢来源 {item.source} -4")

    matched_liked = [word for word in feedback.liked_keywords if word.lower() in text]
    if matched_liked:
        liked_score = min(5, len(matched_liked))
        score += liked_score
        reasons.append(f"反馈加分：喜欢关键词 {', '.join(matched_liked[:5])} +{liked_score}")

    matched_disliked = [word for word in feedback.disliked_keywords if word.lower() in text]
    if matched_disliked:
        disliked_score = min(8, 3 * len(matched_disliked))
        score -= disliked_score
        reasons.append(f"反馈扣分：不喜欢关键词 {', '.join(matched_disliked[:5])} -{disliked_score}")

    return score, reasons


def score_item(
    item: NewsItem,
    profile: UserProfile,
    feedback: FeedbackRules | None = None,
) -> ScoredNewsItem:
    """Score one news item using multiple deterministic editorial dimensions."""
    score = 0
    reasons: list[str] = []

    for points, point_reasons in (
        category_points(item, profile),
        source_metadata_points(item),
        content_relevance_points(item, profile),
        feedback_points(item, feedback),
    ):
        score += points
        reasons.extend(point_reasons)

    freshness_score, freshness_reason = freshness_points(item.published)
    score += freshness_score
    reasons.append(f"{freshness_reason} {freshness_score:+d}")

    if not reasons:
        reasons.append("没有明显偏好信号")

    return ScoredNewsItem(item=item, score=score, reasons=reasons)


def apply_source_diversity(scored_items: list[ScoredNewsItem]) -> list[ScoredNewsItem]:
    """Apply a small ranking-time penalty when one source dominates."""
    source_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    adjusted: list[ScoredNewsItem] = []

    for entry in sorted(
        scored_items,
        key=lambda item: (
            item.score,
            read_priority(item.item),
            item.item.published,
            item.item.source,
            item.item.title,
        ),
        reverse=True,
    ):
        source_seen = source_counts.get(entry.item.source, 0)
        category_seen = category_counts.get(entry.item.category, 0)
        penalty = 0
        reasons = list(entry.reasons)

        if source_seen >= 3:
            penalty += min(6, 2 * (source_seen - 2))
        if category_seen >= 10:
            penalty += 1

        if penalty:
            reasons.append(f"多样性降权：同源/同类内容已较多 -{penalty}")

        source_counts[entry.item.source] = source_seen + 1
        category_counts[entry.item.category] = category_seen + 1
        adjusted.append(
            ScoredNewsItem(
                item=entry.item,
                score=entry.score - penalty,
                reasons=reasons,
            )
        )

    return sorted(
        adjusted,
        key=lambda item: (
            item.score,
            read_priority(item.item),
            item.item.published,
            item.item.source,
            item.item.title,
        ),
        reverse=True,
    )


def score_items(
    items: list[NewsItem],
    profile: UserProfile,
    feedback: FeedbackRules | None = None,
) -> list[ScoredNewsItem]:
    """Score and order news items from highest to lowest priority."""
    scored = [score_item(item, profile, feedback) for item in items]
    return apply_source_diversity(scored)


def select_items_for_analysis(
    scored_items: list[ScoredNewsItem],
    min_score: int,
    max_items: int,
) -> list[ScoredNewsItem]:
    """Select items for LLM analysis while keeping a non-empty fallback."""
    selected = [entry for entry in scored_items if entry.score >= min_score]

    if not selected:
        selected = scored_items

    if max_items > 0:
        return selected[:max_items]

    return selected
