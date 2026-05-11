"""agent 编排模块。

这个文件相当于“工作流总控”。
它不负责具体抓取、具体调 API、具体写 Markdown，而是把各模块串起来。

完整流程：
1. 读取资讯源。
2. 抓取热点资讯。
3. 保存原始 JSON 数据。
4. 调用 DeepSeek 生成分析。
5. 保存 Markdown 日报。
"""

from __future__ import annotations

# Path 是路径类型，这里用于标注函数返回值是一个文件路径。
from pathlib import Path

# Settings 是配置对象类型。
from ai_report_agent.config import Settings

# analyze_news 会调用 DeepSeek，对资讯进行分批分析和最终汇总。
from ai_report_agent.deepseek_client import analyze_news

# build_report_markdown 负责生成 Markdown 文本。
# save_report 负责把 Markdown 文本写入文件。
from ai_report_agent.report import build_report_markdown, save_report

# collect_news 负责抓取资讯。
# load_sources 负责读取 sources.json。
# save_raw_items 负责保存原始抓取结果。
from ai_report_agent.sources import collect_news, load_sources, save_raw_items


def run_daily_report(settings: Settings) -> Path:
    """运行一次完整日报生成流程，并返回报告路径。

    参数：
    - settings: 从 .env 读取出来的配置对象

    返回：
    - Path: 生成的 Markdown 报告文件路径
    """
    # 打印进度，方便你在终端知道程序运行到哪一步。
    print("开始收集 AI 热点...")

    # 从 sources.json 加载启用的资讯源。
    sources = load_sources(settings.sources_path)

    # 抓取所有资讯源。
    # collect_news 返回两个值：
    # items 是成功抓到的资讯列表。
    # errors 是失败来源的错误信息列表。
    items, errors = collect_news(
        sources,
        limit_per_source=settings.max_items_per_source,
        timeout=settings.request_timeout,
    )

    # 如果一条资讯都没抓到，就直接报错。
    # 这样避免后面拿空数据调用 DeepSeek。
    if not items:
        # "\n".join(errors) 把错误列表拼成多行字符串。
        details = "\n".join(errors) if errors else "没有采集到任何条目"
        raise RuntimeError(f"热点采集失败：{details}")

    # 保存原始 JSON 数据，方便后续排查和复盘。
    raw_data_path = save_raw_items(items, settings.raw_data_dir)

    # 告诉用户抓到了多少条，以及原始数据保存在哪里。
    print(f"已采集 {len(items)} 条资讯，原始数据保存至：{raw_data_path}")

    # 调用 DeepSeek 分析资讯。
    # 这里内部会自动分批，不会只分析前几条。
    print("开始调用 DeepSeek 分析...")
    analysis = analyze_news(settings, items)

    # 把 DeepSeek 分析结果、参考来源、错误信息整理成 Markdown 文本。
    markdown = build_report_markdown(
        analysis=analysis,
        items=items,
        errors=errors,
        raw_data_path=raw_data_path,
    )

    # 保存 Markdown 文件。
    report_path = save_report(markdown, settings.report_dir)

    # 打印最终报告路径。
    print(f"日报生成完成：{report_path}")

    # 返回报告路径，给入口文件或 scheduler 使用。
    return report_path
