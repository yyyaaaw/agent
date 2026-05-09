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

from pathlib import Path

from ai_report_agent.config import Settings
from ai_report_agent.critic import critique_report, revise_report, should_revise
from ai_report_agent.deduplicator import deduplicate_items
from ai_report_agent.deepseek_client import analyze_news
from ai_report_agent.profile import load_profile
from ai_report_agent.report import build_report_markdown, save_report
from ai_report_agent.scorer import score_items, select_items_for_analysis
from ai_report_agent.sources import collect_news, load_sources, save_raw_items
from ai_report_agent.state import create_run_state, save_run_state


def run_daily_report(settings: Settings) -> Path:
    """运行一次 Version 2 日报 agent，并返回报告路径。"""
    state = create_run_state()
    profile = load_profile(settings.profile_path)
    state.decisions.append(f"读取用户偏好：{settings.profile_path}")

    print("开始收集 AI 热点...")
    sources = load_sources(settings.sources_path)
    items, errors = collect_news(
        sources,
        limit_per_source=settings.max_items_per_source,
        timeout=settings.request_timeout,
    )
    state.raw_item_count = len(items)
    state.errors.extend(errors)

    if not items:
        details = "\n".join(errors) if errors else "没有采集到任何条目"
        raise RuntimeError(f"热点采集失败：{details}")

    raw_data_path = save_raw_items(items, settings.raw_data_dir)
    state.raw_data_path = str(raw_data_path)
    print(f"已采集 {len(items)} 条资讯，原始数据保存至：{raw_data_path}")

    dedup_result = deduplicate_items(items)
    state.unique_item_count = len(dedup_result.unique_items)
    state.duplicate_count = dedup_result.duplicate_count
    state.decisions.append(
        f"去重完成：{len(items)} 条原始资讯 -> {len(dedup_result.unique_items)} 条唯一资讯，"
        f"重复 {dedup_result.duplicate_count} 条"
    )

    scored_items = score_items(dedup_result.unique_items, profile)
    selected_scored_items = select_items_for_analysis(
        scored_items,
        min_score=settings.min_item_score,
        max_items=settings.max_analysis_items,
    )
    selected_items = [entry.item for entry in selected_scored_items]
    state.selected_item_count = len(selected_items)
    state.decisions.append(
        f"评分筛选完成：选出 {len(selected_items)} 条进入 DeepSeek 分析，"
        f"最低分阈值 {settings.min_item_score}，最多 {settings.max_analysis_items} 条"
    )
    state.decisions.extend(
        f"入选：{entry.score} 分｜{entry.item.title}｜{'; '.join(entry.reasons)}"
        for entry in selected_scored_items[:20]
    )

    print(
        f"去重后 {len(dedup_result.unique_items)} 条；"
        f"按偏好评分后选择 {len(selected_items)} 条进入 DeepSeek。"
    )

    print("开始调用 DeepSeek 分析...")
    analysis = analyze_news(settings, selected_items, profile)

    markdown = build_report_markdown(
        analysis=analysis,
        items=selected_items,
        errors=errors,
        raw_data_path=raw_data_path,
    )

    print("开始进行报告质量自查...")
    critique = critique_report(settings, markdown, profile)
    state.critic_result = critique
    if should_revise(critique):
        print("质量自查未通过，开始修订报告...")
        state.decisions.append("质量检查结论为 FAIL，已触发报告修订。")
        markdown = revise_report(settings, markdown, critique, profile)
    else:
        state.decisions.append("质量检查结论为 PASS，无需修订。")

    report_path = save_report(markdown, settings.report_dir)
    state.report_path = str(report_path)
    state_path = save_run_state(state, settings.run_log_dir)

    print(f"日报生成完成：{report_path}")
    print(f"运行状态已保存：{state_path}")
    return report_path
