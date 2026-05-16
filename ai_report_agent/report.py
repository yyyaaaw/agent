"""报告生成模块。

这个文件负责把 DeepSeek 生成的日报正文，整理成 Markdown 文件。

Markdown 是一种轻量文本格式。
例如：
- `# 标题` 表示一级标题
- `## 标题` 表示二级标题
- `[文字](链接)` 表示超链接
"""

from __future__ import annotations

# datetime 用来获取当前日期和时间。
from datetime import datetime

# Path 用来表示文件路径。
from pathlib import Path

# NewsItem 是采集模块中的资讯条目类型。
from ai_report_agent.sources import NewsItem


def build_report_markdown(
    analysis: str,
    items: list[NewsItem],
    errors: list[str],
    raw_data_path: Path,
) -> str:
    """生成最终 Markdown 日报文本。

    参数：
    - analysis: DeepSeek 生成的日报正文
    - items: 原始资讯条目，用来生成“参考来源”
    - errors: 抓取失败的来源说明
    - raw_data_path: 原始 JSON 数据文件路径

    返回：
    - str: Markdown 文本
    """
    # 获取当前时间。
    now = datetime.now()

    # 生成参考来源列表。
    # 这里使用列表推导式，每个 item 生成一行 Markdown。
    source_lines = [
        # 这是条件表达式，也叫三元表达式：
        # 如果 item.link 有值，就生成带链接的 Markdown；
        # 否则生成普通文本。
        f"- [{item.title}]({item.link}) - {item.source} / {item.category}"
        if item.link
        else f"- {item.title} - {item.source} / {item.category}"
        for item in items
    ]

    # 如果 errors 非空，就把每个错误变成 "- xxx" 的列表。
    # 如果 errors 为空，就显示 "- 无"。
    error_block = "\n".join(f"- {error}" for error in errors) if errors else "- 无"

    # 返回完整 Markdown 文本。
    # f"""...""" 是多行格式化字符串。
    # now.strftime(...) 用来把时间格式化成字符串。
    return f"""# AI 热点日报 - {now.strftime('%Y-%m-%d')}

生成时间：{now.strftime('%Y-%m-%d %H:%M:%S')}

## 今日摘要

{analysis}

## 参考来源

{chr(10).join(source_lines)}

## 采集状态

原始数据：`{raw_data_path}`

采集失败：
{error_block}
"""


def save_report(markdown: str, report_dir: Path, run_id: str = "") -> Path:
    """保存 Markdown 日报文件。

    参数：
    - markdown: 要写入文件的 Markdown 文本
    - report_dir: 报告输出目录

    返回：
    - Path: 实际保存的报告文件路径
    """
    report_dir.mkdir(parents=True, exist_ok=True)

    # 生成报告文件名，例如 reports/ai_hotspots_2026-05-08_20260508_090000.md。
    run_suffix = f"_{run_id}" if run_id else ""
    output_path = report_dir / f"ai_hotspots_{datetime.now().strftime('%Y-%m-%d')}{run_suffix}.md"

    # write_text 把字符串写入文件。
    # encoding="utf-8" 确保中文正常保存。
    output_path.write_text(markdown, encoding="utf-8")

    # 返回文件路径。
    return output_path
