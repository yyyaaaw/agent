"""Version 2 agent 编排模块。

Version 1 是固定流程：采集 -> DeepSeek 分析 -> 保存报告。

Version 2 在这个基础上增加了更像 agent 的能力：
1. 读取用户偏好 profile.json。
2. 记录本次运行状态 state。
3. 去重，减少重复热点。
4. 按“AI 应用相关性 + 用户偏好”评分筛选。
5. 生成报告后进行自查，必要时修订。
"""

from __future__ import annotations

# Path 用在返回值类型注解中，表示最终返回的是报告文件路径。
from pathlib import Path

# Settings 是配置对象类型，包含 API Key、目录、筛选阈值等运行参数。
from ai_report_agent.config import Settings

# critique_report / revise_report / should_revise 负责报告自查和必要时修订。
from ai_report_agent.critic import critique_report, revise_report, should_revise

# deduplicate_items 负责在分析前去掉重复资讯。
from ai_report_agent.deduplicator import deduplicate_items

# analyze_news 负责调用 DeepSeek 完成分批分析和最终汇总。
from ai_report_agent.deepseek_client import analyze_news

# load_profile 负责读取用户偏好 profile.json。
from ai_report_agent.profile import load_profile

# build_report_markdown / save_report 负责生成和保存 Markdown 报告。
from ai_report_agent.report import build_report_markdown, save_report

# score_items / select_items_for_analysis 负责按用户偏好给资讯评分筛选。
from ai_report_agent.scorer import score_items, select_items_for_analysis

# collect_news / load_sources / save_raw_items 负责资讯源读取、RSS 采集和原始数据保存。
from ai_report_agent.sources import collect_news, load_sources, save_raw_items

# create_run_state / save_run_state 负责记录本次运行的状态和决策轨迹。
from ai_report_agent.state import create_run_state, save_run_state


def run_daily_report(settings: Settings) -> Path:
    """运行一次 Version 2 日报 agent，并返回报告路径。"""
    # 创建本次运行状态对象，用来记录采集数量、筛选数量、错误和决策。
    state = create_run_state()

    # 读取用户偏好，后续评分、prompt、自查都会用到它。
    profile = load_profile(settings.profile_path)

    # 把“读取偏好”这一步写入运行轨迹，方便之后复盘。
    state.decisions.append(f"读取用户偏好：{settings.profile_path}")

    # 提示用户程序已经进入采集阶段。
    print("开始收集 AI 热点...")

    # 从 sources.json 读取启用的 RSS 来源。
    sources = load_sources(settings.sources_path)

    # 按配置抓取所有来源的 RSS 内容，成功条目进入 items，失败信息进入 errors。
    items, errors = collect_news(
        sources,
        limit_per_source=settings.max_items_per_source,
        timeout=settings.request_timeout,
    )

    # 记录原始采集数量。
    state.raw_item_count = len(items)

    # 把采集阶段的非致命错误保存进状态对象。
    state.errors.extend(errors)

    # 如果所有来源都失败或没有任何条目，就终止本次运行。
    if not items:
        # 有错误时展示错误详情；没有错误时展示空采集说明。
        details = "\n".join(errors) if errors else "没有采集到任何条目"

        # 主动抛出异常，让命令行或定时器知道本次任务失败。
        raise RuntimeError(f"热点采集失败：{details}")

    # 保存原始采集结果，便于之后人工检查或复盘。
    raw_data_path = save_raw_items(items, settings.raw_data_dir)

    # 把原始数据路径写入运行状态。
    state.raw_data_path = str(raw_data_path)

    # 打印采集结果，方便命令行用户了解进度。
    print(f"已采集 {len(items)} 条资讯，原始数据保存至：{raw_data_path}")

    # 对原始资讯做去重，减少重复热点进入后续分析。
    dedup_result = deduplicate_items(items)

    # 记录去重后的唯一资讯数量。
    state.unique_item_count = len(dedup_result.unique_items)

    # 记录被去掉的重复数量。
    state.duplicate_count = dedup_result.duplicate_count

    # 把去重结果写入决策轨迹。
    state.decisions.append(
        f"去重完成：{len(items)} 条原始资讯 -> {len(dedup_result.unique_items)} 条唯一资讯，"
        f"重复 {dedup_result.duplicate_count} 条"
    )

    # 根据用户偏好和应用相关关键词给资讯打分。
    scored_items = score_items(dedup_result.unique_items, profile)

    # 根据最低分和最大数量筛选进入 DeepSeek 的资讯。
    selected_scored_items = select_items_for_analysis(
        scored_items,
        min_score=settings.min_item_score,
        max_items=settings.max_analysis_items,
    )

    # DeepSeek 只需要原始 NewsItem，不需要评分包装对象。
    selected_items = [entry.item for entry in selected_scored_items]

    # 记录最终进入分析的资讯数量。
    state.selected_item_count = len(selected_items)

    # 把筛选策略和结果写入运行轨迹。
    state.decisions.append(
        f"评分筛选完成：选出 {len(selected_items)} 条进入 DeepSeek 分析，"
        f"最低分阈值 {settings.min_item_score}，最多 {settings.max_analysis_items} 条"
    )

    # 记录前 20 条入选资讯及其入选原因，避免状态文件过长。
    state.decisions.extend(
        f"入选：{entry.score} 分｜{entry.item.title}｜{'; '.join(entry.reasons)}"
        for entry in selected_scored_items[:20]
    )

    # 打印筛选阶段摘要，给用户一个进度反馈。
    print(
        f"去重后 {len(dedup_result.unique_items)} 条；"
        f"按偏好评分后选择 {len(selected_items)} 条进入 DeepSeek。"
    )

    # 提示用户即将开始调用模型。
    print("开始调用 DeepSeek 分析...")

    # 调用 DeepSeek，得到中文日报正文。
    analysis = analyze_news(settings, selected_items, profile)

    # 把模型输出、参考来源、采集错误整理成完整 Markdown。
    markdown = build_report_markdown(
        analysis=analysis,
        items=selected_items,
        errors=errors,
        raw_data_path=raw_data_path,
    )

    # 生成报告后，再进行一次质量自查。
    print("开始进行报告质量自查...")

    # 调用 DeepSeek 扮演质检员，检查报告是否符合偏好和事实约束。
    critique = critique_report(settings, markdown, profile)

    # 把自查结果保存到运行状态。
    state.critic_result = critique

    # 如果自查结论是 FAIL，则自动触发修订。
    if should_revise(critique):
        # 告知用户进入修订阶段。
        print("质量自查未通过，开始修订报告...")

        # 把修订决策写入运行轨迹。
        state.decisions.append("质量检查结论为 FAIL，已触发报告修订。")

        # 根据自查意见重新生成一版报告。
        markdown = revise_report(settings, markdown, critique, profile)
    else:
        # 如果自查通过，就只记录通过结果。
        state.decisions.append("质量检查结论为 PASS，无需修订。")

    # 保存最终 Markdown 报告。
    report_path = save_report(markdown, settings.report_dir)

    # 把报告路径写入运行状态。
    state.report_path = str(report_path)

    # 保存运行状态 JSON。
    state_path = save_run_state(state, settings.run_log_dir)

    # 打印最终报告路径。
    print(f"日报生成完成：{report_path}")

    # 打印运行状态日志路径。
    print(f"运行状态已保存：{state_path}")

    # 返回报告路径，方便命令行入口或定时器打印。
    return report_path
