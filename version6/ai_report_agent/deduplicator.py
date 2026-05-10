"""资讯去重模块。

这个模块负责在调用 DeepSeek 之前减少重复资讯。

RSS 来源之间经常会转载同一件事：
- 同一个链接可能出现在多个来源里。
- 同一个标题可能因为大小写、标点或空格不同而看起来不完全一样。

这里采用保守策略：
1. 先按归一化后的链接去重。
2. 如果链接缺失或不同，再按归一化后的标题去重。
3. 不做模糊语义去重，避免误删不同事件。
"""

from __future__ import annotations

# re 是正则表达式模块，用来统一清理标题中的标点和空白。
import re

# urlparse / urlunparse 用来拆解和重新组合 URL，方便去掉追踪参数。
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# dataclass 用来快速创建“只存数据”的结果类型。
from dataclasses import dataclass

# NewsItem 是 sources.py 中定义的标准资讯条目。
from ai_report_agent.sources import NewsItem


# 这些 URL 参数通常只用于广告追踪或统计，不代表文章本身。
TRACKING_QUERY_PREFIXES = ("utm_",)

# 这些 URL 参数也常见于分享追踪，可以安全忽略。
TRACKING_QUERY_NAMES = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref"}


@dataclass(frozen=True)
class DeduplicationResult:
    """资讯去重结果。"""

    # 去重后保留下来的资讯列表，保持原始顺序。
    unique_items: list[NewsItem]

    # 被判定为重复而跳过的资讯数量。
    duplicate_count: int


def normalize_link(link: str) -> str:
    """把链接整理成适合比较的形式。

    同一篇文章的链接可能会带不同追踪参数。
    去掉这些参数后，更容易识别重复内容。
    """
    # 如果链接为空，直接返回空字符串。
    if not link:
        return ""

    # strip 去掉首尾空白，避免复制或 RSS 解析带来的多余空格影响比较。
    cleaned = link.strip()

    # urlparse 把 URL 拆成 scheme、netloc、path、query 等部分。
    parsed = urlparse(cleaned)

    # 如果不是标准 URL，urlparse 可能拆不出域名，这时退回小写字符串比较。
    if not parsed.netloc:
        return cleaned.lower()

    # 域名大小写不敏感，所以统一转成小写。
    netloc = parsed.netloc.lower()

    # path 末尾的斜杠通常不影响文章身份，去掉可以减少重复。
    path = parsed.path.rstrip("/")

    # parse_qsl 把 query 字符串拆成键值对列表。
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)

    # 过滤掉常见追踪参数，保留真正可能影响内容的参数。
    filtered_pairs = [
        (key, value)
        for key, value in query_pairs
        if not key.lower().startswith(TRACKING_QUERY_PREFIXES)
        and key.lower() not in TRACKING_QUERY_NAMES
    ]

    # urlencode 把过滤后的参数重新拼回 query 字符串。
    query = urlencode(filtered_pairs)

    # fragment 是 # 后面的页面锚点，通常不代表不同文章，这里清空。
    return urlunparse((parsed.scheme.lower(), netloc, path, "", query, ""))


def normalize_title(title: str) -> str:
    """把标题整理成适合比较的形式。"""
    # 标题为空时返回空字符串，调用方会自然跳过标题键。
    if not title:
        return ""

    # lower 统一大小写；strip 去掉首尾空白。
    text = title.lower().strip()

    # 把常见英文标点和中文标点替换成空格。
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)

    # 把连续空白压缩成一个空格，避免因为排版差异导致无法匹配。
    text = re.sub(r"\s+", " ", text)

    # 返回最终标题键。
    return text.strip()


def item_keys(item: NewsItem) -> tuple[str, str]:
    """为一条资讯生成链接键和标题键。"""
    # 链接键用于优先判断完全相同或近似相同的 URL。
    link_key = normalize_link(item.link)

    # 标题键用于处理不同来源转载同一标题的情况。
    title_key = normalize_title(item.title)

    # 返回两个键，调用方会分别检查。
    return link_key, title_key


def deduplicate_items(items: list[NewsItem]) -> DeduplicationResult:
    """对资讯列表去重，并保留第一次出现的条目。

    参数：
    - items: 原始资讯列表

    返回：
    - DeduplicationResult，包含唯一资讯和重复数量
    """
    # seen_links 保存已经出现过的链接键。
    seen_links: set[str] = set()

    # seen_titles 保存已经出现过的标题键。
    seen_titles: set[str] = set()

    # unique_items 按原始顺序保存通过去重的条目。
    unique_items: list[NewsItem] = []

    # duplicate_count 记录被跳过的重复条目数量。
    duplicate_count = 0

    # 逐条检查原始资讯。
    for item in items:
        # 为当前条目生成可比较的链接键和标题键。
        link_key, title_key = item_keys(item)

        # 如果链接键已经见过，说明这条资讯重复。
        link_seen = bool(link_key and link_key in seen_links)

        # 如果标题键已经见过，也认为这条资讯重复。
        title_seen = bool(title_key and title_key in seen_titles)

        # 只要链接或标题任一命中，就跳过当前条目。
        if link_seen or title_seen:
            duplicate_count += 1
            continue

        # 当前条目是新内容，加入输出列表。
        unique_items.append(item)

        # 有链接键时记录链接键。
        if link_key:
            seen_links.add(link_key)

        # 有标题键时记录标题键。
        if title_key:
            seen_titles.add(title_key)

    # 返回结构化结果，方便 agent.py 读取数量和列表。
    return DeduplicationResult(unique_items=unique_items, duplicate_count=duplicate_count)
