"""RSS 信息源采集模块。

Version 12 重点修复 RSS 不稳定的问题。上一版的采集逻辑只会访问
`sources.json` 里写死的一个 URL：一旦站点改了 RSS 地址、返回重定向、
或者旧地址变成 404，本次运行就只能记录失败。

这一版把 RSS 采集改成“可自愈”的流程：
1. 仍然优先访问 sources.json 中配置的主 RSS。
2. 如果主 RSS 失败，尝试该来源的备用 RSS 地址。
3. 如果备用地址也失败，访问来源主页，从 HTML 中自动发现 RSS/Atom 链接。
4. 如果 HTML 发现不到，再尝试常见路径，例如 /feed/、/rss.xml、/atom.xml。
5. 每次成功或失败都会写入 data/source_health.json，方便后续运行优先尝试上次成功的地址。

这样做的目标不是“保证所有网站永远能抓到”，而是让 agent 遇到常见的 RSS
地址变更、永久重定向、临时不可达时，有一套明确的恢复策略。
"""

from __future__ import annotations

# html 用来还原 RSS 摘要里的 HTML 实体，例如把 &amp; 还原成 &。
import html

# HTMLParser 用来从网页源码里寻找 <link rel="alternate" type="application/rss+xml">。
from html.parser import HTMLParser

# json 用来读取 sources.json，以及保存来源健康状态 source_health.json。
import json

# re 用来清理 HTML 标签和多余空白。
import re

# socket.timeout 是 urllib 在网络超时时可能抛出的异常类型之一。
import socket

# urllib.error 里包含 HTTPError、URLError 等网络异常。
import urllib.error

# urllib.parse 用来拼接相对链接、拆解域名和规范化 URL。
import urllib.parse

# urllib.request 是 Python 标准库里的 HTTP 请求工具。
import urllib.request

# XML 解析器，用来解析 RSS 和 Atom feed。
import xml.etree.ElementTree as ET

# dataclass 用来定义轻量数据结构，asdict 用来把 NewsItem 转为字典保存 JSON。
from dataclasses import asdict, dataclass, field

# datetime 用来生成原始采集文件名和来源健康状态的更新时间。
from datetime import datetime

# Path 用来处理本地文件路径。
from pathlib import Path

# Iterable 表示可迭代对象，例如 list/tuple。
from typing import Iterable


# 来源健康状态默认保存位置。这里使用相对路径，是为了跟随当前运行目录。
# 在项目根目录运行 catch_ai.py 时，它会写到 data/source_health.json。
SOURCE_HEALTH_PATH = Path("data/source_health.json")


# 统一的请求头。很多站点会拒绝空 User-Agent 或看起来不像浏览器/正常客户端的请求。
# Accept 明确告诉站点：我们优先要 RSS、Atom、XML，也可以接受 HTML 以便做 feed 自动发现。
REQUEST_HEADERS = {
    "User-Agent": (
        "LocalAIReportAgent/12.0 "
        "(RSS collector; compatible; contact: local-use)"
    ),
    "Accept": (
        "application/rss+xml, application/atom+xml, application/xml, "
        "text/xml, text/html;q=0.8, */*;q=0.5"
    ),
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}


@dataclass(frozen=True)
class NewsSource:
    """一个可抓取的信息源配置。

    `url` 是主 RSS 地址。
    `homepage_url` 是来源主页，用于主 RSS 失败时自动发现 feed。
    `fallback_urls` 是人工维护的备用 RSS 地址列表。

    这三个字段组合起来，可以覆盖大多数 RSS 失效场景：
    - 站点 RSS 地址改了：homepage_url 自动发现新地址。
    - 旧地址 301/308 重定向：fetch_url 会记录最终地址，下次优先尝试。
    - 某个分类 feed 不稳定：fallback_urls 可以提供站点全站 feed 或其他分类 feed。
    """

    # 来源名称，会显示在日报和错误记录中。
    name: str

    # 主 RSS 地址。
    url: str

    # 来源分类，例如“产品与模型”“应用与商业”。
    category: str = "应用与产品"

    # 是否启用这个来源。
    enabled: bool = True

    # 来源主页。主 RSS 抓不到时，会访问主页寻找 RSS/Atom alternate link。
    homepage_url: str = ""

    # 备用 RSS 地址。主地址失败时按顺序尝试。
    fallback_urls: list[str] = field(default_factory=list)

    # 来源所在区域，用于后续评分和来源配额，例如 global、china。
    region: str = "global"

    # 来源主要语言，例如 en、zh。
    language: str = "en"

    # 来源类型，例如 company、general_news、research、community。
    source_type: str = "company"

    # 来源优先级，数字越大越重要。当前只记录和规划，不直接影响评分。
    priority: int = 3

    # 轻量主题标签，给后续评分、源规划和报告解释使用。
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NewsItem:
    """归一化后的新闻条目。

    不同 RSS/Atom 的字段名可能不同。采集模块把它们整理成统一结构，
    后续评分、去重、事件聚类和报告生成就不用关心来源格式差异。
    """

    # 新闻来自哪个来源。
    source: str

    # 来源分类。
    category: str

    # 文章标题。
    title: str

    # 原文链接。
    link: str

    # 发布时间。这里保留为字符串，因为不同 RSS 的时间格式不完全一致。
    published: str

    # 摘要或正文片段。
    summary: str

    # 来源所在区域，例如 global、china。旧测试和手工构造对象可使用默认值。
    region: str = "global"

    # 来源主要语言，例如 en、zh。
    language: str = "en"

    # 来源类型，例如 company、general_news、research、community。
    source_type: str = "company"

    # 来源优先级，来自 sources.json。
    priority: int = 3

    # 来源主题标签，供评分和后续解释使用。
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FetchResult:
    """一次 HTTP 抓取的结果。

    `final_url` 很重要：如果站点把旧 RSS 地址永久重定向到了新地址，
    我们会把 final_url 写入 source_health.json，下次运行优先尝试它。
    """

    # 响应内容字节。
    content: bytes

    # 请求最终落到的 URL，可能和原始 URL 不同。
    final_url: str

    # HTTP 状态码。某些情况下拿不到时记为 0。
    status_code: int

    # 响应 Content-Type，辅助判断内容是 XML 还是 HTML。
    content_type: str


class FeedLinkParser(HTMLParser):
    """从 HTML 页面里发现 RSS/Atom 链接。

    很多网站会在页面 head 中写：
    <link rel="alternate" type="application/rss+xml" href="/feed/">

    旧版采集器只能访问 sources.json 写死的 URL。新增这个解析器后，
    即使站点更换了 RSS 地址，只要主页还暴露 alternate feed，agent 就有机会自动恢复。
    """

    def __init__(self, base_url: str) -> None:
        # 调用父类初始化 HTML 解析状态。
        super().__init__()

        # 当前网页 URL，用来把 /feed/ 这种相对路径转换成绝对 URL。
        self.base_url = base_url

        # 收集发现到的 feed URL。
        self.feed_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """处理 HTML 开始标签，只关心 <link> 标签。"""
        if tag.lower() != "link":
            return

        # 把属性列表转换成字典，方便按属性名读取。
        attr_map = {key.lower(): value or "" for key, value in attrs}

        # rel 可能包含多个值，例如 "alternate stylesheet"。
        rel = attr_map.get("rel", "").lower()

        # type 用来判断这个 alternate 是否真的是 RSS/Atom/XML。
        content_type = attr_map.get("type", "").lower()

        # href 是 feed 地址，可能是绝对 URL，也可能是相对路径。
        href = attr_map.get("href", "").strip()

        # 不是 alternate 或没有 href 时，跳过。
        if "alternate" not in rel or not href:
            return

        # 常见 feed 类型。部分站点 type 可能为空，所以也允许 URL 看起来像 feed。
        looks_like_feed_type = any(
            marker in content_type
            for marker in ("rss", "atom", "xml", "rdf")
        )
        looks_like_feed_url = any(
            marker in href.lower()
            for marker in ("feed", "rss", "atom", ".xml")
        )

        # 只有像 RSS/Atom 的链接才加入候选，避免把普通 alternate 语言链接误当成 feed。
        if looks_like_feed_type or looks_like_feed_url:
            absolute_url = urllib.parse.urljoin(self.base_url, href)
            self.feed_urls.append(absolute_url)


# 如果 sources.json 不存在或所有来源都禁用，使用这组兜底来源。
# Version 12 给容易变化的来源补充了 homepage_url 和 fallback_urls。
FALLBACK_SOURCES = [
    NewsSource(
        "OpenAI Blog",
        "https://openai.com/news/rss.xml",
        "产品与模型",
        homepage_url="https://openai.com/news/",
        fallback_urls=["https://openai.com/blog/rss.xml"],
    ),
    NewsSource(
        "Google DeepMind Blog",
        "https://deepmind.google/discover/blog/rss.xml",
        "产品与研究",
        homepage_url="https://deepmind.google/discover/blog/",
        fallback_urls=[
            "https://deepmind.google/discover/blog/rss/",
            "https://deepmind.google/blog/rss.xml",
        ],
    ),
    NewsSource(
        "Microsoft AI Blog",
        "https://blogs.microsoft.com/ai/feed/",
        "企业应用",
        homepage_url="https://blogs.microsoft.com/ai/",
    ),
    NewsSource(
        "NVIDIA AI Blog",
        "https://blogs.nvidia.com/blog/category/deep-learning/feed/",
        "企业应用",
        homepage_url="https://blogs.nvidia.com/blog/category/deep-learning/",
        fallback_urls=["https://blogs.nvidia.com/feed/"],
    ),
    NewsSource(
        "VentureBeat AI",
        "https://venturebeat.com/category/ai/feed/",
        "应用与商业",
        homepage_url="https://venturebeat.com/category/ai/",
        fallback_urls=[
            "https://venturebeat.com/category/ai/feed",
            "https://venturebeat.com/feed/",
        ],
    ),
    NewsSource(
        "TechCrunch AI",
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "应用与商业",
        homepage_url="https://techcrunch.com/category/artificial-intelligence/",
        fallback_urls=["https://techcrunch.com/feed/"],
    ),
    NewsSource(
        "The Decoder",
        "https://the-decoder.com/feed/",
        "应用与产品",
        homepage_url="https://the-decoder.com/",
    ),
    NewsSource(
        "MIT Technology Review AI",
        "https://www.technologyreview.com/feed/",
        "趋势与影响",
        homepage_url="https://www.technologyreview.com/",
    ),
    NewsSource(
        "Arxiv CS AI",
        "https://export.arxiv.org/rss/cs.AI",
        "研究论文",
        homepage_url="https://arxiv.org/list/cs.AI/recent",
    ),
]

def parse_string_list(value: object) -> list[str]:
    """把可选 JSON 列表安全转换成清理后的字符串列表。"""
    # sources.json 中的 fallback_urls/tags 可能缺失或写错类型；这里统一兜底为空列表。
    if not isinstance(value, list):
        return []

    # str(item).strip() 可以兼容数字等非字符串值，同时过滤空字符串。
    return [str(item).strip() for item in value if str(item).strip()]


def parse_priority(value: object, default: int = 3) -> int:
    """读取来源优先级，并限制在 1-5 的可控范围。"""
    try:
        priority = int(value)
    except (TypeError, ValueError):
        priority = default

    # priority 太大或太小都会破坏评分权重，所以这里强制夹到 1-5。
    return max(1, min(5, priority))


def load_sources(config_path: Path) -> list[NewsSource]:
    """从 sources.json 加载信息源配置。

    Version 12 兼容旧格式：
    {
      "name": "...",
      "url": "...",
      "category": "...",
      "enabled": true
    }

    也支持新字段：
    - homepage_url：来源主页，用于自动发现 RSS。
    - fallback_urls：备用 RSS 地址列表。
    """
    if not config_path.exists():
        return FALLBACK_SOURCES

    raw_sources = json.loads(config_path.read_text(encoding="utf-8"))
    sources: list[NewsSource] = []

    for item in raw_sources:
        if not item.get("enabled", True):
            continue

        sources.append(
            NewsSource(
                name=str(item["name"]),
                url=str(item["url"]),
                category=str(item.get("category", "应用与产品")),
                enabled=bool(item.get("enabled", True)),
                homepage_url=str(item.get("homepage_url", "")),
                fallback_urls=parse_string_list(item.get("fallback_urls", [])),
                region=str(item.get("region", "global")).strip() or "global",
                language=str(item.get("language", "en")).strip() or "en",
                source_type=str(item.get("source_type", "company")).strip() or "company",
                priority=parse_priority(item.get("priority", 3)),
                tags=parse_string_list(item.get("tags", [])),
            )
        )

    return sources or FALLBACK_SOURCES


def load_source_health(path: Path = SOURCE_HEALTH_PATH) -> dict[str, dict[str, object]]:
    """读取来源健康状态。

    返回结构按来源名索引，例如：
    {
      "VentureBeat AI": {
        "working_url": "https://venturebeat.com/feed/",
        "success_count": 3,
        "failure_count": 1,
        "consecutive_failures": 0
      }
    }

    如果文件不存在或格式损坏，返回空字典。采集流程不应该因为健康状态文件坏了而中断。
    """
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    if not isinstance(data, dict):
        return {}

    return {
        str(source_name): value
        for source_name, value in data.items()
        if isinstance(value, dict)
    }


def save_source_health(
    health: dict[str, dict[str, object]],
    path: Path = SOURCE_HEALTH_PATH,
) -> None:
    """保存来源健康状态。

    这个文件是 agent 自我修复 RSS 的长期记忆之一。它不会替代 sources.json，
    只记录“上次哪个 URL 成功过、失败次数是多少”等运行事实。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(health, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def update_source_success(
    health: dict[str, dict[str, object]],
    source: NewsSource,
    working_url: str,
    item_count: int,
) -> None:
    """记录某个来源本次采集成功。

    成功时清零 consecutive_failures，并把最终可用 URL 写入 working_url。
    下次运行会优先尝试 working_url，从而绕开已经失效的旧地址。
    """
    previous = health.get(source.name, {})
    success_count = int(previous.get("success_count", 0)) + 1
    failure_count = int(previous.get("failure_count", 0))

    health[source.name] = {
        "source_name": source.name,
        "configured_url": source.url,
        "region": source.region,
        "language": source.language,
        "source_type": source.source_type,
        "priority": source.priority,
        "working_url": working_url,
        "last_status": "success",
        "last_success_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_error": "",
        "last_item_count": item_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "consecutive_failures": 0,
    }


def update_source_failure(
    health: dict[str, dict[str, object]],
    source: NewsSource,
    error: str,
) -> None:
    """记录某个来源本次采集失败。

    注意：失败不会删除 working_url。因为一次失败可能只是临时网络问题，
    之前成功过的 URL 仍然值得下次优先尝试。
    """
    previous = health.get(source.name, {})
    success_count = int(previous.get("success_count", 0))
    failure_count = int(previous.get("failure_count", 0)) + 1
    consecutive_failures = int(previous.get("consecutive_failures", 0)) + 1

    health[source.name] = {
        "source_name": source.name,
        "configured_url": source.url,
        "region": source.region,
        "language": source.language,
        "source_type": source.source_type,
        "priority": source.priority,
        "working_url": str(previous.get("working_url", "")),
        "last_status": "failure",
        "last_success_at": str(previous.get("last_success_at", "")),
        "last_error_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_error": error,
        "last_item_count": 0,
        "success_count": success_count,
        "failure_count": failure_count,
        "consecutive_failures": consecutive_failures,
    }


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    """去重并保持原始顺序。"""
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        normalized = normalize_url(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)

    return result


def normalize_url(url: str) -> str:
    """对 URL 做轻量规范化。

    这里只做不会改变语义的处理：去掉首尾空白，把协议和域名转小写，
    删除 fragment。不会删除 query，因为某些 RSS 地址可能依赖 query 参数。
    """
    cleaned = (url or "").strip()
    if not cleaned:
        return ""

    parsed = urllib.parse.urlparse(cleaned)

    # 如果不是标准 URL，直接返回原始清理结果，让后续请求抛出明确错误。
    if not parsed.scheme or not parsed.netloc:
        return cleaned

    return urllib.parse.urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            parsed.params,
            parsed.query,
            "",
        )
    )


def infer_homepage_url(feed_url: str) -> str:
    """从 RSS 地址推断站点主页。

    sources.json 最好显式配置 homepage_url，但为了兼容旧配置，这里提供兜底推断。
    例如 https://example.com/category/ai/feed/ 会推断为 https://example.com/。
    """
    parsed = urllib.parse.urlparse(feed_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))


def common_feed_candidates(homepage_url: str) -> list[str]:
    """根据主页构造常见 RSS/Atom 候选地址。

    这一步覆盖那些没有在 HTML 里暴露 alternate link、但仍使用常规路径的站点。
    """
    if not homepage_url:
        return []

    base = homepage_url.rstrip("/") + "/"
    return [
        urllib.parse.urljoin(base, "feed/"),
        urllib.parse.urljoin(base, "rss.xml"),
        urllib.parse.urljoin(base, "atom.xml"),
        urllib.parse.urljoin(base, "feed.xml"),
        urllib.parse.urljoin(base, "blog/feed/"),
    ]


def fetch_url(url: str, timeout: int | None, max_redirects: int = 5) -> FetchResult:
    """下载 URL 内容，并返回响应内容、最终 URL 和状态信息。

    urllib 默认会处理常见重定向，但一些站点的 308 Permanent Redirect
    在不同 Python/站点组合下可能仍会暴露为 HTTPError。这里额外做一层
    手动重定向处理，避免因为 308 就直接判定来源不可用。
    """
    current_url = normalize_url(url)

    for _ in range(max_redirects + 1):
        request = urllib.request.Request(current_url, headers=REQUEST_HEADERS)

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                status_code = getattr(response, "status", 0) or response.getcode()
                final_url = response.geturl()
                return FetchResult(
                    content=response.read(),
                    final_url=normalize_url(final_url),
                    status_code=int(status_code or 0),
                    content_type=content_type,
                )

        except urllib.error.HTTPError as exc:
            # 对 3xx 做手动跳转兜底，尤其是旧版运行记录里出现过的 308。
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location", "")
                if location:
                    current_url = normalize_url(urllib.parse.urljoin(current_url, location))
                    continue
            raise

    raise RuntimeError(f"重定向次数超过限制：{url}")


def clean_text(text: str) -> str:
    """清理 HTML 标签、HTML 实体和多余空白。"""
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def child_text(element: ET.Element, names: Iterable[str]) -> str:
    """按多个候选标签名读取子节点文本，兼容 RSS 和 Atom。"""
    for name in names:
        child = element.find(name)
        if child is not None and child.text:
            return clean_text(child.text)
    return ""


def child_attr(element: ET.Element, name: str, attr: str) -> str:
    """读取子节点属性，常用于 Atom feed 的 link href。"""
    child = element.find(name)
    if child is not None:
        return child.attrib.get(attr, "")
    return ""


def parse_feed(source: NewsSource, content: bytes, limit: int) -> list[NewsItem]:
    """解析 RSS 或 Atom feed，返回统一的 NewsItem 列表。

    如果 content 不是合法 XML，ET.fromstring 会抛出 ParseError，由上层决定是否
    尝试下一个候选 URL。
    """
    root = ET.fromstring(content)

    # RSS 使用 <item>，Atom 使用带命名空间的 <entry>。
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    parsed: list[NewsItem] = []
    for item in items[:limit]:
        title = child_text(item, ["title", "{http://www.w3.org/2005/Atom}title"])
        link = child_text(item, ["link"]) or child_attr(
            item, "{http://www.w3.org/2005/Atom}link", "href"
        )
        published = child_text(
            item,
            [
                "pubDate",
                "published",
                "updated",
                "{http://www.w3.org/2005/Atom}published",
                "{http://www.w3.org/2005/Atom}updated",
            ],
        )
        summary = child_text(
            item,
            [
                "description",
                "summary",
                "{http://www.w3.org/2005/Atom}summary",
                "{http://www.w3.org/2005/Atom}content",
            ],
        )

        if title:
            parsed.append(
                NewsItem(
                    source=source.name,
                    category=source.category,
                    title=title,
                    link=link,
                    published=published,
                    summary=summary[:600],
                    region=source.region,
                    language=source.language,
                    source_type=source.source_type,
                    priority=source.priority,
                    tags=source.tags,
                )
            )

    return parsed


def discover_feed_urls(source: NewsSource, timeout: int | None) -> list[str]:
    """访问来源主页，自动发现 RSS/Atom feed 地址。

    这个函数只负责“找候选”，不负责判断候选是否一定可用。
    可用性由 collect_news 后续逐个 fetch + parse 来验证。
    """
    homepage_url = source.homepage_url or infer_homepage_url(source.url)
    if not homepage_url:
        return []

    discovered: list[str] = []

    try:
        result = fetch_url(homepage_url, timeout=timeout)
        # 主页通常是 HTML，需要按响应声明的编码解码。没有声明时用 utf-8 兜底。
        charset = "utf-8"
        content_type = result.content_type.lower()
        match = re.search(r"charset=([\w.-]+)", content_type)
        if match:
            charset = match.group(1)

        html_text = result.content.decode(charset, errors="replace")
        parser = FeedLinkParser(result.final_url)
        parser.feed(html_text)
        discovered.extend(parser.feed_urls)

    except (urllib.error.URLError, TimeoutError, socket.timeout, RuntimeError, UnicodeError):
        # feed 发现失败不应该中断采集；后续仍会尝试常见路径。
        pass

    discovered.extend(common_feed_candidates(homepage_url))
    return unique_preserve_order(discovered)


def build_candidate_urls(
    source: NewsSource,
    health: dict[str, dict[str, object]],
    timeout: int | None,
) -> list[str]:
    """为一个来源构造 RSS 候选 URL 列表。

    候选顺序体现优先级：
    1. source_health.json 里上次成功过的 working_url。
    2. sources.json 中配置的主 URL。
    3. sources.json 中配置的备用 URL。
    4. 主页 HTML 自动发现到的 RSS/Atom URL。
    5. 常见路径推断出来的 URL。
    """
    health_entry = health.get(source.name, {})
    learned_url = str(health_entry.get("working_url", "") or "")

    candidates = [
        learned_url,
        source.url,
        *source.fallback_urls,
        *discover_feed_urls(source, timeout=timeout),
    ]

    return unique_preserve_order(candidates)


def error_text(exc: BaseException) -> str:
    """把异常转换成适合写入日志的短文本。"""
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}: {exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        return f"URL error: {exc.reason}"
    return str(exc)


def collect_one_source(
    source: NewsSource,
    limit_per_source: int,
    timeout: int | None,
    health: dict[str, dict[str, object]],
) -> tuple[list[NewsItem], str]:
    """采集单个来源。

    返回值：
    - 成功时：([NewsItem, ...], "")
    - 失败时：([], "错误说明")

    函数会按候选 URL 顺序尝试，只要某个候选能解析出新闻条目，就认为该来源成功。
    """
    candidate_urls = build_candidate_urls(source, health, timeout)
    attempt_errors: list[str] = []

    for candidate_url in candidate_urls:
        try:
            fetch_result = fetch_url(candidate_url, timeout=timeout)
            items = parse_feed(source, fetch_result.content, limit_per_source)

            # 有些 URL 能返回 XML，但不是新闻 feed，解析后没有条目。继续尝试下一个候选。
            if not items:
                attempt_errors.append(f"{candidate_url} -> 解析成功但没有发现新闻条目")
                continue

            update_source_success(
                health,
                source,
                working_url=fetch_result.final_url or candidate_url,
                item_count=len(items),
            )
            return items, ""

        except (urllib.error.URLError, ET.ParseError, TimeoutError, socket.timeout, RuntimeError) as exc:
            attempt_errors.append(f"{candidate_url} -> {error_text(exc)}")

    combined_error = "；".join(attempt_errors) if attempt_errors else "没有可尝试的 RSS 候选地址"
    update_source_failure(health, source, combined_error)
    return [], combined_error


def short_error_text(error: str, max_chars: int = 160) -> str:
    """压缩错误文本，让终端进度输出保持可读。"""
    # 详细错误仍会写入 JSON；终端只展示短摘要，避免一行太长。
    cleaned = re.sub(r"\s+", " ", error or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3] + "..."


def print_source_progress(
    status: str,
    index: int,
    total: int,
    source: NewsSource,
    item_count: int = 0,
    error: str = "",
) -> None:
    """打印单个 RSS 来源的简洁采集进度。"""
    prefix = f"[{index}/{total}] {source.name}"
    metadata = f"{source.region}/{source.source_type}/{source.language}"

    # status 分为 start/success/failure 三种，保持命令行输出稳定。
    if status == "start":
        print(f"{prefix} ({metadata}) ...")
    elif status == "success":
        print(f"{prefix} OK: {item_count} items")
    else:
        print(f"{prefix} FAIL: {short_error_text(error)}")


def build_source_plan(
    sources: list[NewsSource],
    health: dict[str, dict[str, object]],
) -> dict[str, object]:
    """根据来源配置和健康状态生成轻量来源规划建议。

    这个函数不会修改 sources.json，只会生成一个可复盘的 source_plan.json。
    它的作用是提示后续是否需要：
    - 扩充国内/中文来源；
    - 替换连续失败的来源；
    - 给高优先级失败来源补备用 RSS。
    """
    region_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    language_counts: dict[str, int] = {}
    recommendations: list[dict[str, object]] = []

    for source in sources:
        # 按区域、类型、语言统计来源覆盖。
        region_counts[source.region] = region_counts.get(source.region, 0) + 1
        type_counts[source.source_type] = type_counts.get(source.source_type, 0) + 1
        language_counts[source.language] = language_counts.get(source.language, 0) + 1

        # 读取该来源上次健康状态，用来生成可靠性建议。
        health_entry = health.get(source.name, {})
        try:
            consecutive_failures = int(health_entry.get("consecutive_failures", 0) or 0)
        except (TypeError, ValueError):
            consecutive_failures = 0
        last_status = str(health_entry.get("last_status", "unknown") or "unknown")

        # 连续失败很多次时，建议人工考虑停用或替换。
        if consecutive_failures >= 5:
            recommendations.append(
                {
                    "action": "review_disable_or_replace",
                    "source": source.name,
                    "reason": f"consecutive_failures={consecutive_failures}",
                    "priority": "high",
                }
            )
        # 高优先级来源最近失败时，建议优先补 fallback URL。
        elif last_status == "failure" and source.priority >= 4:
            recommendations.append(
                {
                    "action": "review_fallback_urls",
                    "source": source.name,
                    "reason": "high-priority source failed in the latest run",
                    "priority": "medium",
                }
            )

    china_count = region_counts.get("china", 0)
    zh_count = language_counts.get("zh", 0)
    general_count = type_counts.get("general_news", 0) + type_counts.get("general_tech", 0)

    # 国内/中文来源不足时提示扩充，避免信息源长期偏海外。
    if china_count < 6 or zh_count < 6:
        recommendations.append(
            {
                "action": "expand_domestic_sources",
                "source": "",
                "reason": f"china_sources={china_count}, zh_sources={zh_count}; target>=6",
                "priority": "high",
            }
        )

    # 综合新闻源不足时提示扩充，避免只看公司官方博客。
    if general_count < 5:
        recommendations.append(
            {
                "action": "expand_general_news_sources",
                "source": "",
                "reason": f"general_news_sources={general_count}; target>=5",
                "priority": "medium",
            }
        )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_count": len(sources),
        "region_counts": region_counts,
        "language_counts": language_counts,
        "source_type_counts": type_counts,
        "recommendations": recommendations,
    }


def save_source_plan(plan: dict[str, object], path: Path) -> None:
    """保存来源规划建议文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def collect_news(
    sources: list[NewsSource],
    limit_per_source: int,
    timeout: int | None,
    source_health_path: Path = SOURCE_HEALTH_PATH,
    source_plan_path: Path | None = None,
    show_progress: bool = True,
) -> tuple[list[NewsItem], list[str]]:
    """抓取所有信息源。

    Version 12 的主要变化在这里：
    - 不再把单个 RSS URL 失败视为整个来源失败。
    - 每个来源会尝试多个候选 URL。
    - 成功地址会写入 source_health.json，下次优先使用。
    - 失败详情会包含所有候选地址的失败原因，便于排查。
    """
    all_items: list[NewsItem] = []
    errors: list[str] = []

    # 读取历史健康状态，作为本次候选 URL 排序依据。
    health = load_source_health(source_health_path)

    total_sources = len(sources)
    if show_progress:
        print(f"RSS collection: {total_sources} sources, limit {limit_per_source} per source.")

    for index, source in enumerate(sources, start=1):
        if show_progress:
            print_source_progress("start", index, total_sources, source)

        items, error = collect_one_source(
            source=source,
            limit_per_source=limit_per_source,
            timeout=timeout,
            health=health,
        )

        if items:
            all_items.extend(items)
            if show_progress:
                print_source_progress("success", index, total_sources, source, len(items))
        else:
            errors.append(f"{source.name}: {error}")
            if show_progress:
                print_source_progress("failure", index, total_sources, source, error=error)

    # 无论本次是否有失败，都保存健康状态。这样成功 URL 和连续失败次数都会被沉淀下来。
    save_source_health(health, source_health_path)

    if source_plan_path is not None:
        save_source_plan(build_source_plan(sources, health), source_plan_path)

    if show_progress:
        print(f"RSS collection done: {len(all_items)} items, {len(errors)} failed sources.")

    return all_items, errors


def save_raw_items(items: list[NewsItem], output_dir: Path, run_id: str = "") -> Path:
    """保存原始采集结果，便于后续排查和复盘。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    run_suffix = f"_{run_id}" if run_id else ""
    output_path = output_dir / f"ai_news_raw_{datetime.now().strftime('%Y-%m-%d')}{run_suffix}.json"
    payload = [asdict(item) for item in items]
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path
