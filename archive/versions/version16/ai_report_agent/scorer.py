"""热点资讯评分模块。

评分器是 LLM 之前的一层“确定性预筛选”：
它不追求像编辑一样完美判断新闻价值，而是用稳定、可解释的规则，
把更符合项目方向的资讯排在前面。

本项目的编辑方向包括：
- 更关注可落地的 AI 应用，而不是纯论文或底层算法。
- 更关注产品、工具、工作流和企业影响。
- 兼顾国内/全球来源与来源多样性。
- 接收用户 profile.json 和 feedback.json 的偏好反馈。
"""

from __future__ import annotations

# email.utils 可以解析 RSS 中常见的 RFC 2822 时间格式，例如 Tue, 21 May 2026 10:00:00 GMT。
import email.utils

# re 用于从发布时间字符串中提取 ISO 日期，也用于后续轻量文本匹配。
import re

# dataclass 用于定义带分数的新闻结果对象。
from dataclasses import dataclass

# date/datetime 用于计算新闻发布时间距离今天有多久。
from datetime import date, datetime

# FeedbackRules 是用户历史反馈沉淀出的加分/扣分规则。
from ai_report_agent.feedback import FeedbackRules

# UserProfile 是用户静态偏好，例如关注方向、不想看的主题、偏好类别。
from ai_report_agent.profile import UserProfile

# NewsItem 是 RSS 采集阶段得到的标准资讯结构。
from ai_report_agent.sources import NewsItem


# 应用相关关键词。命中这些词说明新闻更可能和“能直接使用的 AI 应用”有关。
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

# 商业与落地关键词。命中后说明新闻可能和企业采用、收入、合作、客户案例有关。
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

# 产品变化关键词。命中后说明新闻可能是发布、更新、接口、插件等产品层变化。
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

# 偏研究、偏论文的关键词。如果没有应用信号，会被降权。
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

# 来源标签中这些值属于高信号标签，能帮助补充 sources.json 的元数据偏好。
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

# 不同来源类型的基础权重。研究源默认降权，是为了让日报更偏应用落地。
SOURCE_TYPE_WEIGHTS = {
    "general_news": 3,
    "general_tech": 3,
    "company": 2,
    "community": 1,
    "research": -2,
}

# 期望补足的国内来源区域标识。命中后加分，避免日报完全偏海外来源。
PREFERRED_DOMESTIC_REGION = "china"


@dataclass(frozen=True)
class ScoredNewsItem:
    """带确定性分数和可读理由的新闻条目。"""

    # 原始新闻条目。
    item: NewsItem

    # 综合规则计算出的整数分数，越高越优先进入 LLM。
    score: int

    # 每一项加分/扣分原因，便于写入数据库和 run_state 复盘。
    reasons: list[str]


def item_text(item: NewsItem) -> str:
    """把新闻多个字段合并成小写文本，供关键词规则统一匹配。"""
    # tags 是 sources.json 中的轻量标签；旧对象可能没有这个字段，所以用 getattr 兼容。
    tags = " ".join(getattr(item, "tags", []) or [])

    # 统一 lower 后，后续英文关键词匹配就不用区分大小写。
    return f"{item.title} {item.summary} {item.category} {item.source} {tags}".lower()


def match_keywords(text: str, keywords: list[str]) -> list[str]:
    """按顺序返回命中的唯一关键词。"""
    matches: list[str] = []
    for keyword in keywords:
        # 对关键词也做小写和空白清理。
        normalized = keyword.lower().strip()

        # keyword not in matches 用于去重，同时保留关键词表原始顺序。
        if normalized and normalized in text and keyword not in matches:
            matches.append(keyword)
    return matches


def limited_points(count: int, limit: int) -> int:
    """把命中数量限制在一个较小加分范围内。"""
    # 避免关键词堆叠导致某一类信号无限加分，破坏整体权重平衡。
    return min(limit, max(0, count))


def read_priority(item: NewsItem) -> int:
    """读取来源优先级，并兼容旧测试样例。"""
    try:
        # 旧版 NewsItem 或测试 fixture 可能没有 priority 字段。
        priority = int(getattr(item, "priority", 3))
    except (TypeError, ValueError):
        priority = 3

    # priority 约定范围是 1-5，越大越重要。
    return max(1, min(5, priority))


def parse_published_date(value: str) -> date | None:
    """把常见 RSS 发布时间格式解析成 date。"""
    raw = (value or "").strip()
    if not raw:
        return None

    # 优先支持 YYYY-MM-DD，因为有些来源会在字符串里嵌入这个格式。
    iso_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", raw)
    if iso_match:
        try:
            return datetime.strptime(iso_match.group(1), "%Y-%m-%d").date()
        except ValueError:
            return None

    # 再尝试解析 RFC 2822 等 RSS 常见格式。
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    return parsed.date()


def freshness_points(published: str, today: date | None = None) -> tuple[int, str]:
    """根据发布时间给时效性加分/扣分。"""
    parsed = parse_published_date(published)
    if parsed is None:
        return 0, "时效性：发布时间未知"

    today = today or date.today()
    age_days = (today - parsed).days

    # 未来日期通常是 RSS 时区或来源错误，不直接重罚，但只给轻微加分。
    if age_days < 0:
        return 1, f"时效性：疑似未来日期 {parsed.isoformat()}，仅轻微加分"

    # 越接近今天，越适合进入“日报”。
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
    """根据来源元数据加分或扣分。"""
    score = 0
    reasons: list[str] = []

    # 来源类型来自 sources.json，例如 company、general_news、research。
    source_type = str(getattr(item, "source_type", "") or "").strip()
    source_type_score = SOURCE_TYPE_WEIGHTS.get(source_type, 0)
    if source_type_score:
        score += source_type_score
        reasons.append(f"来源类型：{source_type} {source_type_score:+d}")

    # 国内来源加分，用来提高中文/国内生态覆盖。
    region = str(getattr(item, "region", "") or "").strip()
    if region == PREFERRED_DOMESTIC_REGION:
        score += 3
        reasons.append("地域平衡：国内来源 +3")

    # 中文来源轻微加分，避免全部由英文来源支配。
    language = str(getattr(item, "language", "") or "").strip()
    if language == "zh":
        score += 1
        reasons.append("语言覆盖：中文来源 +1")

    # priority 由人工配置，适合表达“这个来源本来就更重要”。
    priority = read_priority(item)
    priority_score = priority - 3
    if priority_score:
        score += priority_score
        reasons.append(f"来源优先级：{priority} ({priority_score:+d})")

    # tags 是更细粒度的来源标签，命中高信号标签时小幅加分。
    tags = {str(tag).strip().lower() for tag in (getattr(item, "tags", []) or [])}
    matched_tags = sorted(tags & {tag.lower() for tag in HIGH_SIGNAL_TAGS})
    if matched_tags:
        tag_score = min(2, len(matched_tags))
        score += tag_score
        reasons.append(f"来源标签匹配：{', '.join(matched_tags[:4])} +{tag_score}")

    return score, reasons


def category_points(item: NewsItem, profile: UserProfile) -> tuple[int, list[str]]:
    """根据用户偏好类别和研究论文类别调整分数。"""
    score = 0
    reasons: list[str] = []

    # 用户在 profile.json 里配置的偏好类别优先。
    if item.category in profile.preferred_categories:
        score += 3
        reasons.append(f"类别符合偏好：{item.category} +3")

    # 研究论文不是完全不要，但默认降低优先级，除非后面有强应用信号拉回来。
    if item.category == "研究论文":
        score -= 3
        reasons.append("研究论文默认降权 -3")

    return score, reasons


def content_relevance_points(item: NewsItem, profile: UserProfile) -> tuple[int, list[str]]:
    """根据新闻内容和用户偏好计算应用相关性分数。"""
    text = item_text(item)
    score = 0
    reasons: list[str] = []

    # profile.interests 是用户主动关心的方向，命中越多加分越高，但设置上限。
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

    # 商业落地信号单独计分，因为它是日报“能不能直接用/影响业务”的核心。
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

    # profile.avoid 是用户明确不想重点看的方向，命中后强扣分。
    matched_avoid = [word for word in profile.avoid if word.lower() in text]
    if matched_avoid:
        avoid_score = 4 * len(matched_avoid)
        score -= avoid_score
        reasons.append(f"命中降权词：{', '.join(matched_avoid[:5])} -{avoid_score}")

    matched_research_only = match_keywords(text, RESEARCH_ONLY_KEYWORDS)
    has_application_signal = bool(matched_application or matched_business or matched_product)

    # 只有研究词、没有应用/商业/产品信号时，才认为偏离项目定位。
    if matched_research_only and not has_application_signal:
        score -= 4
        reasons.append(f"偏研究且缺少应用信号：{', '.join(matched_research_only[:4])} -4")

    return score, reasons


def feedback_points(
    item: NewsItem,
    feedback: FeedbackRules | None,
) -> tuple[int, list[str]]:
    """应用用户显式反馈规则。"""
    if feedback is None:
        return 0, []

    text = item_text(item)
    score = 0
    reasons: list[str] = []

    if item.category in feedback.liked_categories:
        score += 2
        reasons.append(f"反馈加分：喜欢类别 {item.category} +2")

    # 反馈扣分通常比加分更重，因为“不想看”的内容更应该被过滤掉。
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
    """按多个确定性编辑维度给单条新闻打分。"""
    score = 0
    reasons: list[str] = []

    # 每个子函数都返回“分数变化 + 原因列表”，这里统一累加。
    for points, point_reasons in (
        category_points(item, profile),
        source_metadata_points(item),
        content_relevance_points(item, profile),
        feedback_points(item, feedback),
    ):
        score += points
        reasons.extend(point_reasons)

    # 时效性单独追加，确保每条新闻都能看到时间判断理由。
    freshness_score, freshness_reason = freshness_points(item.published)
    score += freshness_score
    reasons.append(f"{freshness_reason} {freshness_score:+d}")

    # 理论上至少会有时效性原因；这里保留兜底，便于以后修改评分项后仍可解释。
    if not reasons:
        reasons.append("没有明显偏好信号")

    return ScoredNewsItem(item=item, score=score, reasons=reasons)


def apply_source_diversity(scored_items: list[ScoredNewsItem]) -> list[ScoredNewsItem]:
    """在排序阶段对过度集中的来源做轻微降权。"""
    source_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    adjusted: list[ScoredNewsItem] = []

    # 先按原始分数和稳定字段排序，再从高到低观察来源是否过度重复。
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

        # 同一个来源进入候选太多时，后面的同源新闻逐渐降权。
        # 这样不是禁止同源，而是给其他来源留出一点空间。
        if source_seen >= 3:
            penalty += min(6, 2 * (source_seen - 2))
        if category_seen >= 10:
            penalty += 1

        if penalty:
            reasons.append(f"多样性降权：同源/同类内容已较多 -{penalty}")

        source_counts[entry.item.source] = source_seen + 1
        category_counts[entry.item.category] = category_seen + 1

        # 生成新的 ScoredNewsItem，而不是修改原对象；dataclass frozen=True 也鼓励这种不可变风格。
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
    """给新闻列表打分，并按优先级从高到低排序。"""
    # 第一轮：逐条计算确定性分数。
    scored = [score_item(item, profile, feedback) for item in items]

    # 第二轮：应用来源多样性降权，并返回最终顺序。
    return apply_source_diversity(scored)


def select_items_for_analysis(
    scored_items: list[ScoredNewsItem],
    min_score: int,
    max_items: int,
) -> list[ScoredNewsItem]:
    """筛选进入 LLM 分析的新闻，同时保留非空兜底。"""
    # 先按最低分筛选。
    selected = [entry for entry in scored_items if entry.score >= min_score]

    # 如果所有新闻都低于阈值，仍然把已排序列表交给 LLM。
    # 这样可以避免一次运行因为阈值过严而完全没有日报内容。
    if not selected:
        selected = scored_items

    # max_items <= 0 表示不限制数量。
    if max_items > 0:
        return selected[:max_items]

    return selected
