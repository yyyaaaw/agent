"""热点源采集模块。

这个文件负责三件事：
1. 从 sources.json 读取 RSS 资讯源配置。
2. 下载每个 RSS 源的内容。
3. 把不同 RSS 格式整理成统一的 NewsItem 数据结构。

RSS 可以理解成网站提供的一种“机器可读新闻列表”。
相比直接爬网页，RSS 更稳定，也更适合做日报采集。
"""

from __future__ import annotations

# html 用来处理 HTML 实体，例如把 &amp; 还原成 &。
import html

# json 用来读取 sources.json，以及保存原始采集结果。
import json

# re 是正则表达式模块，用来清理 HTML 标签和多余空白。
import re

# urllib.error 里有网络请求可能抛出的错误类型。
import urllib.error

# urllib.request 是 Python 标准库里的 HTTP 请求工具。
import urllib.request

# ElementTree 是 Python 标准库里的 XML 解析工具。
# RSS 和 Atom feed 本质上都是 XML。
import xml.etree.ElementTree as ET

# asdict 可以把 dataclass 对象转换成普通字典，便于保存成 JSON。
# dataclass 用来定义简单的数据类。
from dataclasses import asdict, dataclass

# datetime 用来生成日期文件名。
from datetime import datetime

# Path 用来处理文件路径。
from pathlib import Path

# Iterable 表示“可迭代对象”，比如 list、tuple 等。
from typing import Iterable


@dataclass(frozen=True)
class NewsSource:
    """一个可抓取的资讯源。

    这个类对应 sources.json 里的每一项。
    例如：
    {
      "name": "TechCrunch AI",
      "url": "https://...",
      "category": "应用与商业",
      "enabled": true
    }
    """

    # 来源名称，会显示在日报中。
    name: str

    # RSS 地址。
    url: str

    # 来源分类，默认是“应用与产品”。
    # `= "应用与产品"` 表示如果创建对象时没传 category，就使用这个默认值。
    category: str = "应用与产品"

    # 是否启用这个来源。
    enabled: bool = True


@dataclass(frozen=True)
class NewsItem:
    """归一化后的热点条目。

    不同网站的 RSS 字段可能不同。
    我们把它们整理成统一字段，后面 DeepSeek 和报告模块就不用关心来源差异。
    """

    # 来自哪个资讯源。
    source: str

    # 来源分类，例如“应用与商业”。
    category: str

    # 文章标题。
    title: str

    # 原文链接。
    link: str

    # 发布时间。这里保留为字符串，因为不同 RSS 的时间格式不完全一致。
    published: str

    # 摘要或正文片段。
    summary: str


# 如果 sources.json 不存在，或者里面所有来源都被 disabled，
# 程序会使用这个内置兜底来源列表。
FALLBACK_SOURCES = [
    NewsSource("OpenAI Blog", "https://openai.com/news/rss.xml", "产品与模型"),
    NewsSource("Google DeepMind", "https://deepmind.google/discover/blog/rss.xml", "产品与研究"),
    NewsSource("VentureBeat AI", "https://venturebeat.com/category/ai/feed/", "应用与商业"),
    NewsSource("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "应用与商业"),
    NewsSource("The Decoder", "https://the-decoder.com/feed/", "应用与产品"),
    NewsSource("MIT Technology Review AI", "https://www.technologyreview.com/feed/", "趋势与影响"),
    NewsSource("Arxiv CS AI", "https://export.arxiv.org/rss/cs.AI", "研究论文"),
]


def load_sources(config_path: Path) -> list[NewsSource]:
    """从 sources.json 加载资讯源配置。

    参数：
    - config_path: sources.json 的路径

    返回：
    - list[NewsSource]，也就是 NewsSource 对象组成的列表
    """
    # 如果 sources.json 文件不存在，就使用内置兜底来源。
    if not config_path.exists():
        return FALLBACK_SOURCES

    # read_text 读取 JSON 文件文本。
    # json.loads 把 JSON 字符串转换成 Python 数据，通常是 list/dict。
    raw_sources = json.loads(config_path.read_text(encoding="utf-8"))

    # 这里使用“列表推导式”创建 sources 列表。
    # 它等价于先创建空列表，然后 for 循环 append。
    sources = [
        NewsSource(
            # item["name"] 表示读取字典里的 name 字段。
            # str(...) 确保最终值是字符串。
            name=str(item["name"]),
            url=str(item["url"]),

            # item.get("category", "应用与产品") 表示：
            # 如果有 category 字段就取它，否则用默认值。
            category=str(item.get("category", "应用与产品")),

            # enabled 默认 True。
            enabled=bool(item.get("enabled", True)),
        )
        # 对 raw_sources 里的每个 item 执行上面的 NewsSource(...)
        for item in raw_sources
        # 只保留 enabled 为 true 的来源。
        if item.get("enabled", True)
    ]

    # `sources or FALLBACK_SOURCES` 的意思是：
    # 如果 sources 非空，就返回 sources；如果 sources 是空列表，就返回 FALLBACK_SOURCES。
    return sources or FALLBACK_SOURCES


def fetch_url(url: str, timeout: int | None) -> bytes:
    """下载 RSS 内容。

    返回 bytes，因为网络响应最原始的内容是字节数据。
    后续 XML 解析器可以直接处理 bytes。
    """
    # urllib.request.Request 用来构造 HTTP 请求。
    # 设置 User-Agent 是为了让网站知道这是一个正常客户端请求。
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "LocalAIReportAgent/1.0 (+https://localhost)",
        },
    )

    # urlopen 发起网络请求。
    # timeout 可以是整数，也可以是 None。
    # with 是上下文管理器写法，能确保 response 用完后自动关闭。
    with urllib.request.urlopen(request, timeout=timeout) as response:
        # read() 读取完整响应内容。
        return response.read()


def clean_text(text: str) -> str:
    """清理 HTML 标签、HTML 实体和多余空白。

    有些 RSS 摘要里会带 HTML 标签，比如 <p>...</p>。
    这里把它们清掉，让 DeepSeek 看到更干净的文本。
    """
    # text or "" 表示：如果 text 是空值，就用空字符串替代。
    text = html.unescape(text or "")

    # re.sub(pattern, replacement, text) 表示用 replacement 替换匹配 pattern 的内容。
    # <[^>]+> 是一个简单的 HTML 标签匹配模式。
    text = re.sub(r"<[^>]+>", " ", text)

    # \s+ 表示一个或多个空白字符。
    # 把连续空白合并成一个空格。
    text = re.sub(r"\s+", " ", text)

    # 去掉开头和结尾的空格。
    return text.strip()


def child_text(element: ET.Element, names: Iterable[str]) -> str:
    """按多个可能的标签名读取子节点文本，兼容 RSS 和 Atom。

    RSS 里标题可能叫 title，Atom 里可能带命名空间。
    所以这里允许传入多个候选标签名，找到第一个有文本的就返回。
    """
    # 遍历所有候选标签名。
    for name in names:
        # element.find(name) 查找当前 XML 节点下面的子节点。
        child = element.find(name)

        # 如果找到了 child，并且 child.text 不是空，就清理后返回。
        if child is not None and child.text:
            return clean_text(child.text)

    # 如果所有候选标签都没找到，就返回空字符串。
    return ""


def child_attr(element: ET.Element, name: str, attr: str) -> str:
    """读取子节点属性，常用于 Atom feed 的 link href。

    Atom 格式里链接常常长这样：
    <link href="https://example.com/article" />
    这时链接不是节点文本，而是 href 属性。
    """
    # 查找指定名称的子节点。
    child = element.find(name)

    # 找到子节点时，尝试读取指定属性。
    if child is not None:
        # attrib 是 XML 节点的属性字典。
        return child.attrib.get(attr, "")

    # 没找到子节点时返回空字符串。
    return ""


def parse_feed(source: NewsSource, content: bytes, limit: int) -> list[NewsItem]:
    """解析 RSS 或 Atom feed，返回指定数量的热点条目。

    参数：
    - source: 当前资讯源配置
    - content: 下载到的 RSS/Atom 原始字节内容
    - limit: 最多解析多少条
    """
    # ET.fromstring 把 XML 字节内容解析成 XML 树的根节点。
    root = ET.fromstring(content)

    # RSS 常用 <item> 表示一篇文章。
    # ".//item" 表示在整个 XML 树中查找所有 item 节点。
    items = root.findall(".//item")

    # 如果没找到 RSS item，则尝试 Atom 格式的 entry。
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    # 创建一个空列表，用来放解析后的 NewsItem。
    parsed: list[NewsItem] = []

    # items[:limit] 是列表切片，表示只取前 limit 条。
    for item in items[:limit]:
        # 读取标题。
        title = child_text(item, ["title", "{http://www.w3.org/2005/Atom}title"])

        # 读取链接。
        # `a or b` 表示如果 a 有值就用 a，否则用 b。
        link = child_text(item, ["link"]) or child_attr(
            item, "{http://www.w3.org/2005/Atom}link", "href"
        )

        # 读取发布时间，兼容多种字段名。
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

        # 读取摘要，兼容 description、summary、content 等字段。
        summary = child_text(
            item,
            [
                "description",
                "summary",
                "{http://www.w3.org/2005/Atom}summary",
                "{http://www.w3.org/2005/Atom}content",
            ],
        )

        # 如果没有标题，这条内容价值不大，跳过。
        if title:
            # append 表示把一个元素追加到列表末尾。
            parsed.append(
                NewsItem(
                    source=source.name,
                    category=source.category,
                    title=title,
                    link=link,
                    published=published,
                    # summary[:600] 表示只保留摘要前 600 个字符，避免 prompt 太长。
                    summary=summary[:600],
                )
            )

    # 返回这个来源解析出来的所有条目。
    return parsed


def collect_news(
    sources: list[NewsSource],
    limit_per_source: int,
    timeout: int | None,
) -> tuple[list[NewsItem], list[str]]:
    """抓取所有资讯源。

    返回值是一个 tuple，也就是元组：
    - 第一个元素：成功解析出的 NewsItem 列表
    - 第二个元素：失败来源的错误说明列表
    """
    # 用来收集所有成功抓到的资讯。
    all_items: list[NewsItem] = []

    # 用来记录失败的来源和错误信息。
    errors: list[str] = []

    # 逐个抓取资讯源。
    for source in sources:
        try:
            # 下载 RSS 内容。
            content = fetch_url(source.url, timeout=timeout)

            # 解析 RSS，并把结果追加到 all_items。
            # extend 表示把另一个列表里的元素逐个加入当前列表。
            all_items.extend(parse_feed(source, content, limit_per_source))

        # except 用来捕获异常，避免某一个来源失败导致整个程序中断。
        # as exc 表示把异常对象保存到变量 exc。
        except (urllib.error.URLError, ET.ParseError, TimeoutError) as exc:
            # 把失败来源名称和错误详情写入 errors，最终会显示在报告底部。
            errors.append(f"{source.name}: {exc}")

    # 返回两个结果。
    return all_items, errors


def save_raw_items(items: list[NewsItem], output_dir: Path) -> Path:
    """保存原始采集结果，便于后续排查和复盘。

    保存成 JSON 的好处是：
    1. 可以查看当天到底抓到了什么。
    2. 如果 DeepSeek 分析出问题，可以不重新抓取，先看原始数据。
    """
    # 生成输出文件路径，例如 data/raw/ai_news_raw_2026-05-08.json。
    output_path = output_dir / f"ai_news_raw_{datetime.now().strftime('%Y-%m-%d')}.json"

    # asdict(item) 把 NewsItem 对象转换成普通字典。
    # 这里用列表推导式，把所有 NewsItem 都转成字典。
    payload = [asdict(item) for item in items]

    # json.dumps 把 Python 数据转换成 JSON 字符串。
    # ensure_ascii=False 表示保留中文，不转成 \uXXXX。
    # indent=2 表示格式化缩进，方便阅读。
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 返回保存的文件路径。
    return output_path
