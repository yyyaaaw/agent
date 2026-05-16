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

# database 模块负责 Version 6 的 SQLite 长期记忆、事件表和向量检索。
from ai_report_agent.database import (
    initialize_database,
    mark_unique_news_items,
    retrieve_related_events,
    retrieve_related_history,
    save_feedback_rules,
    save_events,
    save_raw_news_items,
    save_report_record,
    save_scored_news_items,
    save_source_errors,
    upsert_run_state,
)

# deduplicate_items 负责在分析前去掉重复资讯。
from ai_report_agent.deduplicator import deduplicate_items

# analyze_news 负责调用 DeepSeek 完成分批分析和最终汇总。
from ai_report_agent.deepseek_client import analyze_news

# load_profile 负责读取用户偏好 profile.json。
from ai_report_agent.profile import load_profile

# load_feedback 负责读取用户反馈 feedback.json。
from ai_report_agent.feedback import load_feedback

# cluster_scored_items 负责把入选新闻聚成事件。
from ai_report_agent.events import cluster_scored_items

# build_report_markdown / save_report 负责生成和保存 Markdown 报告。
from ai_report_agent.report import build_report_markdown, save_report

# score_items / select_items_for_analysis 负责按用户偏好给资讯评分筛选。
from ai_report_agent.scorer import score_items, select_items_for_analysis

# collect_news / load_sources / save_raw_items 负责资讯源读取、RSS 采集和原始数据保存。
from ai_report_agent.sources import collect_news, load_sources, save_raw_items

# create_run_state / save_run_state 负责记录本次运行的状态和决策轨迹。
from ai_report_agent.state import create_run_state, save_run_state


def run_daily_report(settings: Settings) -> Path:
    """运行一次 Version 6 日报 agent，并返回报告路径。"""
    # 初始化 SQLite 数据库；如果表已经存在，这一步不会破坏已有数据。
    initialize_database(settings.database_path)

    # 创建本次运行状态对象，用来记录采集数量、筛选数量、错误和决策。
    state = create_run_state()

    # 读取用户偏好，后续评分、prompt、自查都会用到它。
    profile = load_profile(settings.profile_path)

    # 读取用户反馈，后续会影响本地规则打分。
    feedback = load_feedback(settings.feedback_path)

    # 把“读取偏好”这一步写入运行轨迹，方便之后复盘。
    state.decisions.append(f"读取用户偏好：{settings.profile_path}")

    # 把刚创建的运行状态先写入数据库，后续阶段会持续更新。
    upsert_run_state(settings.database_path, state)

    # 保存本次运行使用的反馈规则快照，便于之后复盘。
    save_feedback_rules(settings.database_path, state.run_id, feedback)

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

    # 保存采集错误到数据库，后续可统计来源稳定性。
    save_source_errors(settings.database_path, state.run_id, errors)

    # 如果所有来源都失败或没有任何条目，就终止本次运行。
    if not items:
        # 失败前也同步状态到数据库，避免失败运行完全没有记录。
        upsert_run_state(settings.database_path, state)

        # 有错误时展示错误详情；没有错误时展示空采集说明。
        details = "\n".join(errors) if errors else "没有采集到任何条目"

        # 主动抛出异常，让命令行或定时器知道本次任务失败。
        raise RuntimeError(f"热点采集失败：{details}")

    # 保存原始采集结果，便于之后人工检查或复盘。
    raw_data_path = save_raw_items(items, settings.raw_data_dir)

    # 同时把原始资讯写入 SQLite，作为长期记忆的一部分。
    save_raw_news_items(settings.database_path, state.run_id, items)

    # 把原始数据路径写入运行状态。
    state.raw_data_path = str(raw_data_path)

    # 打印采集结果，方便命令行用户了解进度。
    print(f"已采集 {len(items)} 条资讯，原始数据保存至：{raw_data_path}")

    # 更新数据库中的运行状态。
    upsert_run_state(settings.database_path, state)

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

    # 把哪些资讯是唯一资讯写回数据库。
    mark_unique_news_items(settings.database_path, state.run_id, dedup_result)

    # 根据用户偏好、反馈规则和应用相关关键词给资讯打分。
    scored_items = score_items(dedup_result.unique_items, profile, feedback)

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

    # 保存每条唯一资讯的分数、理由和是否入选 DeepSeek。
    save_scored_news_items(
        settings.database_path,
        state.run_id,
        scored_items,
        selected_scored_items,
    )

    # 把入选新闻按语义相似度聚成事件。
    events = cluster_scored_items(selected_scored_items)

    # 保存事件聚类结果到数据库。
    save_events(settings.database_path, state.run_id, events)

    # 记录事件聚类结果。
    state.decisions.append(
        f"事件聚类完成：{len(selected_items)} 条入选资讯 -> {len(events)} 个事件"
    )

    # 更新数据库中的运行状态。
    upsert_run_state(settings.database_path, state)

    # 打印筛选阶段摘要，给用户一个进度反馈。
    print(
        f"去重后 {len(dedup_result.unique_items)} 条；"
        f"按偏好评分后选择 {len(selected_items)} 条进入 DeepSeek。"
    )

    # 提示用户即将开始调用模型。
    print("开始调用 DeepSeek 分析...")

    # 从历史数据库中做事件级向量检索，查找相关旧事件作为 RAG 上下文。
    history_context = retrieve_related_events(
        settings.database_path,
        current_run_id=state.run_id,
        events=events,
    )

    # 如果暂时还没有历史事件，退回新闻级检索作为兜底。
    if not history_context:
        history_context = retrieve_related_history(
            settings.database_path,
            current_run_id=state.run_id,
            selected_items=selected_items,
        )

    # 如果检索到了历史上下文，就记录到决策轨迹。
    if history_context:
        state.decisions.append("已从 SQLite 数据库完成事件级 RAG 检索，找到相关历史上下文用于最终汇总 prompt。")

    # 调用 DeepSeek，得到中文日报正文。
    analysis = analyze_news(settings, selected_items, profile, history_context, events)

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

    # 把最终报告正文和自查结果保存到 SQLite。
    save_report_record(
        settings.database_path,
        state.run_id,
        report_path,
        markdown,
        state.critic_result,
    )

    # 最后再同步一次完整状态到 SQLite。
    upsert_run_state(settings.database_path, state)

    # 打印最终报告路径。
    print(f"日报生成完成：{report_path}")

    # 打印运行状态日志路径。
    print(f"运行状态已保存：{state_path}")

    # 返回报告路径，方便命令行入口或定时器打印。
    return report_path
