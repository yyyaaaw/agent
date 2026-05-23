"""Version 9 的 Agent 主编排模块。

这个文件可以理解成整个项目的“导演”：
它本身不负责具体采集、去重、打分、调用模型或写数据库，
而是把这些能力按正确顺序组织起来，形成一次完整的日报生成流程。

Version 9 相比 Version 8 的核心变化是：
1. 保留原来的日报生成能力。
2. 给每个关键步骤加上 trace 记录。
3. 让一次运行可以被复盘、评测和调试。

一次完整运行大致会经历：
读取配置 -> 采集新闻 -> 去重 -> 评分筛选 -> 事件聚类 -> LLM 事件合并
-> 历史记忆检索 -> 生成日报 -> 质量自查 -> 必要时修订 -> 保存结果。
"""

# 让类型注解延迟解析，避免某些类在运行时还没定义就被解析。
from __future__ import annotations

# Path 用来表示文件路径，返回报告路径时会用到。
from pathlib import Path

# Settings 是项目的配置对象，里面包含数据库路径、模型配置、目录路径等。
from ai_report_agent.config import Settings

# critic 模块负责报告质量自查、判断是否要修订，以及根据自查结果修订报告。
from ai_report_agent.critic import (
    critique_report,
    revise_report_with_plan,
    should_revise,
    validate_revision_report,
)

# database 模块负责 SQLite 初始化、写入运行状态、保存新闻/事件/报告等长期数据。
from ai_report_agent.database import (
    # 初始化 SQLite 数据库和所有需要的表。
    initialize_database,
    # 把去重结果写回 news_items 表，标记哪些新闻是唯一新闻。
    mark_unique_news_items,
    # 根据本次事件，从历史事件库里检索相关事件，用于事件级 RAG。
    retrieve_related_events,
    # 如果事件级 RAG 没命中，就回退到新闻级历史检索。
    retrieve_related_history,
    # 保存最终事件聚类结果。
    save_events,
    # 保存本次运行使用的用户反馈规则快照。
    save_feedback_rules,
    # 把原始新闻写入 SQLite。
    save_raw_news_items,
    # 保存最终 Markdown 报告和 critic 结果。
    save_report_record,
    # 保存每条新闻的评分、入选状态和评分理由。
    save_scored_news_items,
    # 保存采集失败的信息源错误。
    save_source_errors,
    # 插入或更新本次运行状态。
    upsert_run_state,
)

# deduplicator 模块负责去除重复新闻，减少后续 LLM 输入噪声。
from ai_report_agent.deduplicator import deduplicate_items

# deepseek_client 模块负责调用 DeepSeek 生成日报、合并候选事件，并记录 token usage。
from ai_report_agent.deepseek_client import (
    analyze_news,
    deepseek_balance_delta,
    fetch_deepseek_balance,
    llm_usage_delta,
    reset_llm_usage,
    refine_events_with_llm,
    summarize_llm_usage,
)

# events 模块负责把新闻聚类成事件，并把事件格式化写入 run_state。
from ai_report_agent.events import (
    cluster_scored_items,
    event_compression_ratio,
    format_events_for_state,
)

# feedback 模块负责读取用户历史反馈规则。
from ai_report_agent.feedback import load_feedback

# observability 模块是 Version 9 新增能力，负责记录每个阶段的 trace。
from ai_report_agent.observability import TraceRecorder, trace_dir_from_data_path

# profile 模块负责读取用户偏好，例如关注方向、不想看的内容、报告风格等。
from ai_report_agent.profile import load_profile

# report 模块负责把 LLM 输出拼成 Markdown，并保存最终报告文件。
from ai_report_agent.report import build_report_markdown, save_report

# scorer 模块负责给新闻打分，并筛选进入 LLM 分析的新闻。
from ai_report_agent.scorer import score_items, select_items_for_analysis

# sources 模块负责读取 RSS 源、采集新闻、保存原始采集文件。
from ai_report_agent.sources import collect_news, load_sources, save_raw_items

# state 模块负责创建和保存一次运行的 JSON 状态文件。
from ai_report_agent.state import create_run_state, save_run_state

# taxonomy_builder 模块负责从本次新闻里自动发现词典候选。
from ai_report_agent.taxonomy_builder import update_event_taxonomy_from_items


def attach_llm_usage_metrics(span, before_usage: dict[str, int | float]) -> None:
    """把某个阶段新增的 LLM 用量写入当前 trace span。

    调用方式通常是：
    1. 在调用 LLM 前先 summarize_llm_usage() 得到 before_usage。
    2. 调用 LLM。
    3. 用这个函数计算前后差值，并写入当前 span.metrics。

    这样 trace 里既能看到整次运行的 token，也能看到每个阶段各自消耗了多少。
    """

    # llm_usage_delta 会把调用前后的 token/cost 汇总做差。
    for name, value in llm_usage_delta(before_usage).items():
        # span.metrics 最终会写入 data/traces/trace_<run_id>.json。
        span.metrics[name] = value


def attach_run_llm_usage_metrics(trace: TraceRecorder) -> dict[str, int | float]:
    """把整次运行的 LLM 总用量写入 run-level trace metrics。"""

    # summarize_llm_usage 读取当前进程内所有 LLM 调用记录。
    usage = summarize_llm_usage()

    # run-level metric 不属于某个阶段，而是整次运行的总指标。
    for name, value in usage.items():
        trace.set_metric(name, value)

    # 返回 usage，方便调用方继续拼接 run_state 决策说明。
    return usage


def attach_balance_cost_metrics(
    trace: TraceRecorder,
    settings: Settings,
    balance_before: dict[str, int | float | str | bool],
) -> dict[str, int | float | str | bool]:
    """把 DeepSeek 余额差额成本指标写入 run-level trace metrics。

    DeepSeek 的 chat completion 响应通常只给 token usage，不直接给本次扣费。
    如果 settings.deepseek_cost_mode == "balance_delta"，这里会读取运行结束后的余额，
    与运行前的 balance_before 相减，得到更接近真实账单的成本。
    """

    # 如果没有启用余额差额模式，就写入一组明确的不可用指标。
    # 这样 evaluation.py 读取 trace 时不需要判断字段是否缺失。
    if settings.deepseek_cost_mode != "balance_delta":
        metrics: dict[str, int | float | str | bool] = {
            "llm_cost_mode": settings.deepseek_cost_mode,
            "llm_actual_cost_available": False,
            "llm_actual_cost": 0.0,
            "llm_actual_cost_currency": settings.deepseek_cost_currency,
            "llm_balance_before": 0.0,
            "llm_balance_after": 0.0,
            "llm_balance_delta": 0.0,
            "llm_balance_error": "balance_delta_disabled",
        }
    else:
        # 启用余额差额模式时，在运行末尾再读一次余额。
        balance_after = fetch_deepseek_balance(settings)

        # deepseek_balance_delta 会处理余额不可用、币种不一致、余额增加等异常情况。
        metrics = deepseek_balance_delta(settings, balance_before, balance_after)

    # 把成本相关字段统一写入 run-level metrics。
    for name, value in metrics.items():
        trace.set_metric(name, value)

    # 返回 metrics，供 agent.py 拼接最终的 LLM usage 决策文本。
    return metrics

"""
    try except 语法：
    try: 只运行到哪里出错了 except 就捕获哪里出错的异常，并执行 except 里的代码。
    except: 捕获所有异常，不管是什么类型的错误都会被捕获到。如果except后面没有写raise或者其他处理方式，程序会继续往下执行，不会因为异常而中断。
"""
"""
        with 是 Python 的上下文管理器语法，常用来“进入一个资源使用场景，并在结束后自动清理”。
        with 适合用在“开始使用某个资源，结束后必须收尾”的场景。

        最常见例子是打开文件：
        with open("data.txt", "r", encoding="utf-8") as file:
            content = file.read()
            print(content)

        也就是说，with 的好处是：不管中间有没有报错，都会自动做收尾工作，比如关闭文件、关闭数据库连接、释放锁、结束 trace 记录等。

        在你的项目里经常看到这种：
        with trace.span("collect_news") as span:
            items, errors = collect_news(...)
            span.metrics["raw_items"] = len(items)
        意思是：
        进入一个名叫 "collect_news" 的 trace 阶段。
        as span 把这个阶段对象赋值给变量 span。
        with 里面的代码执行。
        代码结束后，自动记录这个阶段的结束时间、耗时、状态。
        如果里面报错，也能自动记录错误信息.

        trace 严格说不是“资源”，它更像是一个运行记录器 / 监控记录本。
        通过 with trace.span()，你可以把整个 Agent 运行过程切分成多个阶段，每个阶段的开始和结束都会被 trace 自动记录下来。
        上面例子的意思是：
        请 trace 帮我记录一个阶段，名字叫 collect_news。span 就是这个阶段的小记录条目。它不是文件、数据库连接那种真实资源，但它用了 with 语法，是因为它也需要“进入时记录开始时间，退出时记录结束时间”。所以它借用了 with 的上下文管理能力。
        用 with 自动记录这个阶段的开始、结束、耗时和错误。
 """

def run_daily_report(settings: Settings) -> Path:
    """运行一次完整的 AI 热点日报 Agent，并返回最终报告路径。

    参数：
    - settings：项目配置对象，包含数据库路径、报告目录、模型参数等。

    返回：
    - Path：最终生成的 Markdown 日报文件路径。
    """

    # 创建本次运行的状态对象，里面会记录 run_id、采集数量、筛选数量、决策轨迹等。
    state = create_run_state()

    # 创建 trace 记录器；run_id 用来把 trace、run_state、数据库记录对应起来。
    trace = TraceRecorder(state.run_id)

    # 清空本进程内上一轮可能遗留的 LLM usage 记录。
    reset_llm_usage()

    # 运行前余额。只有 balance_delta 模式会填充它；
    # 其他模式保持空字典，后续 attach_balance_cost_metrics 会写入不可用原因。
    balance_before: dict[str, int | float | str | bool] = {}

    # try 包住完整流程，这样即使中途失败，也能在 except 里保存失败 trace。
    try:
        # 如果启用余额差额成本统计，先记录运行前余额。
        # 这一步在数据库初始化之前执行，是为了尽量覆盖整次运行的所有 LLM 成本。
        if settings.deepseek_cost_mode == "balance_delta":
            balance_before = fetch_deepseek_balance(settings)

        # 用一个 trace span 包住数据库初始化阶段，记录这个阶段耗时和是否成功。
        with trace.span("initialize_database"):
            # 初始化 SQLite 数据库；如果表已经存在，这一步不会破坏旧数据。
            initialize_database(settings.database_path)

        # 用一个 trace span 包住用户偏好和反馈规则加载阶段。
        with trace.span("load_profile_and_feedback"):
            # 读取 profile.json，得到用户关注方向、报告风格和过滤偏好。
            profile = load_profile(settings.profile_path)

            # 读取 feedback.json，得到历史反馈沉淀出的加分/扣分规则。
            feedback = load_feedback(settings.feedback_path)

        # 把“已读取用户偏好”写入本次运行的决策轨迹，方便之后复盘。
        state.decisions.append(f"Loaded user profile: {settings.profile_path}")

        # 先把初始运行状态写入数据库，避免后续失败时完全没有记录。
        upsert_run_state(settings.database_path, state)

        # 保存本次运行使用的反馈规则快照，方便以后分析“当时用了哪些偏好”。
        save_feedback_rules(settings.database_path, state.run_id, feedback)

        # 记录 feedback.json 已经参与本次评分。
        state.decisions.append("Loaded feedback.json as scoring rules for this run.")

        # 给命令行用户一个进度提示：开始采集新闻。
        print("Start collecting AI news...")

        # 读取 RSS 信息源配置，并记录信息源数量。
        with trace.span("load_sources") as span:
            # 从 sources.json 读取启用的信息源列表。
            sources = load_sources(settings.sources_path)

            # 在 trace 里记录本次加载了多少个信息源。
            span.metrics["source_count"] = len(sources)

        # 采集 RSS 新闻，并记录采集数量和失败源数量。
        with trace.span("collect_news") as span:
            # collect_news 会逐个请求 RSS 源，并返回成功解析的新闻和错误列表。
            # source_health_path 记录每个来源上次成功 URL、失败次数等长期健康信息。
            source_health_path = settings.raw_data_dir.parent / "source_health.json"

            # source_plan_path 记录来源覆盖和维护建议，例如是否要扩充中文来源。
            source_plan_path = settings.raw_data_dir.parent / "source_plan.json"
            items, errors = collect_news(
                # 要采集的信息源列表。
                sources,
                # 每个源最多采集多少条，避免单个源占满上下文。
                limit_per_source=settings.max_items_per_source,
                # 网络请求超时时间。
                timeout=settings.request_timeout,
                source_health_path=source_health_path,
                source_plan_path=source_plan_path,
            )

            # 在 trace 里记录原始新闻条数。
            span.metrics["raw_items"] = len(items)

            # 在 trace 里记录采集失败的信息源数量。
            span.metrics["source_errors"] = len(errors)

            # 把健康状态和来源规划文件路径也写入 trace，方便从一次运行反查。
            span.metrics["source_health_path"] = str(source_health_path)
            span.metrics["source_plan_path"] = str(source_plan_path)

        # 把原始采集数量写入 run_state。
        state.raw_item_count = len(items)

        # 把采集错误追加到 run_state.errors，最终会写入 JSON 状态文件。
        state.errors.extend(errors)

        # 把采集错误也写入 SQLite，方便长期统计哪些源不稳定。
        save_source_errors(settings.database_path, state.run_id, errors)

        # 如果没有采集到任何新闻，后续分析没有意义，直接终止本次运行。
        if not items:
            # 失败前先同步一次数据库状态，保留失败现场。
            upsert_run_state(settings.database_path, state)

            # 如果有具体错误，就拼成多行；如果没有错误，就给出空采集说明。
            details = "\n".join(errors) if errors else "No news items were collected."

            # 主动抛出异常，让命令行和调度器知道本次运行失败。
            raise RuntimeError(f"News collection failed: {details}")

        # 保存原始采集 JSON 文件，方便以后人工检查模型到底看到了哪些材料。
        with trace.span("save_raw_items"):
            # save_raw_items 会把采集到的 NewsItem 列表写入 data/raw。
            raw_data_path = save_raw_items(items, settings.raw_data_dir, state.run_id)

        # 把原始新闻写入 SQLite，并生成新闻级 embedding。
        with trace.span("save_raw_news_items"):
            # 这一步是长期记忆的基础，后续 RAG 会用到历史新闻和 embedding。
            save_raw_news_items(settings.database_path, state.run_id, items)

        # 把原始 JSON 文件路径写入 run_state。
        state.raw_data_path = str(raw_data_path)

        # 打印采集结果，便于命令行观察进度。
        print(f"Collected {len(items)} items. Raw data saved to: {raw_data_path}")

        # 从本次 RSS 新闻里自动发现实体、产品和动作别名。
        # 高置信候选会写入 generated 词典；低置信候选会提示人工修正。
        with trace.span("update_event_taxonomy") as span:
            try:
                # 这一步只更新本地词典文件，不调用 LLM。
                taxonomy_result = update_event_taxonomy_from_items(items)

                # 记录自动写入的实体、产品、动作别名数量。
                span.metrics["auto_entity_aliases"] = taxonomy_result.auto_entity_aliases
                span.metrics["auto_product_aliases"] = taxonomy_result.auto_product_aliases
                span.metrics["auto_action_aliases"] = taxonomy_result.auto_action_aliases

                # 需要人工复核的候选数量和文件路径也写入 trace。
                span.metrics["review_candidates"] = taxonomy_result.review_candidates
                span.metrics["taxonomy_review_path"] = taxonomy_result.review_path
                span.metrics["taxonomy_report_path"] = taxonomy_result.report_path

                # 同步写入 run_state.decisions，方便不打开 trace 也能看到词典更新结果。
                state.decisions.append(
                    "Taxonomy auto-update: "
                    f"{taxonomy_result.auto_entity_aliases} entity aliases, "
                    f"{taxonomy_result.auto_product_aliases} product aliases, "
                    f"{taxonomy_result.auto_action_aliases} action aliases generated; "
                    f"{taxonomy_result.review_candidates} candidates need review."
                )
                if taxonomy_result.review_candidates:
                    # 有人工复核候选时，把 review 文件路径写入决策轨迹。
                    state.decisions.append(
                        f"Taxonomy manual review file: {taxonomy_result.review_path}"
                    )
            except Exception as exc:
                # 词典自动更新是辅助能力，失败时不应该中断日报主流程。
                span.metrics["taxonomy_update_error"] = str(exc)
                print(f"Taxonomy auto-update skipped: {exc}")
                state.decisions.append(f"Taxonomy auto-update skipped: {exc}")

        # 再次同步运行状态，记录采集阶段结果。
        upsert_run_state(settings.database_path, state)

        # 对新闻做去重，减少同一新闻被多个 RSS 源重复报道带来的噪声。
        with trace.span("deduplicate_items") as span:
            # dedup_result 包含 unique_items 和 duplicate_count。
            dedup_result = deduplicate_items(items)

            # 在 trace 里记录去重后剩余多少条唯一新闻。
            span.metrics["unique_items"] = len(dedup_result.unique_items)

            # 在 trace 里记录去掉了多少条重复新闻。
            span.metrics["duplicate_count"] = dedup_result.duplicate_count

        # 把唯一新闻数量写入 run_state。
        state.unique_item_count = len(dedup_result.unique_items)

        # 把重复新闻数量写入 run_state。
        state.duplicate_count = dedup_result.duplicate_count

        # 把去重决策写入运行轨迹，方便之后解释“为什么数量变少了”。
        state.decisions.append(
            # 第一段：原始新闻数量。
            f"Deduplication: {len(items)} raw items -> "
            # 第二段：去重后唯一新闻数量。
            f"{len(dedup_result.unique_items)} unique items; "
            # 第三段：重复新闻数量。
            f"{dedup_result.duplicate_count} duplicates removed."
        )

        # 把哪些新闻是唯一新闻写回 SQLite。
        mark_unique_news_items(settings.database_path, state.run_id, dedup_result)

        # 给唯一新闻打分，决定哪些内容更值得进入 LLM 分析。
        with trace.span("score_items") as span:
            # score_items 会结合用户 profile、feedback 和应用相关关键词进行评分。
            scored_items = score_items(dedup_result.unique_items, profile, feedback)

            # 在 trace 中记录参与评分的新闻条数。
            span.metrics["scored_items"] = len(scored_items)

        # 从评分结果中筛选进入 DeepSeek 分析的新闻。
        with trace.span("select_items_for_analysis") as span:
            # select_items_for_analysis 会使用最低分和最大条数限制做筛选。
            selected_scored_items = select_items_for_analysis(
                # 全部评分后的新闻。
                scored_items,
                # 低于这个分数的新闻优先不进入分析。
                min_score=settings.min_item_score,
                # 最多送入 LLM 的新闻数量。
                max_items=settings.max_analysis_items,
            )

            # 在 trace 中记录最终入选新闻条数。
            span.metrics["selected_items"] = len(selected_scored_items)

        # LLM 分析只需要原始 NewsItem，不需要评分包装对象。
        selected_items = [entry.item for entry in selected_scored_items]

        # 把最终入选数量写入 run_state。
        state.selected_item_count = len(selected_items)

        # 记录筛选策略和筛选结果。
        state.decisions.append(
            # 记录入选数量。
            f"Scoring selection: selected {len(selected_items)} items for DeepSeek; "
            # 记录最低分阈值和最大条数，方便复盘参数设置。
            f"min score={settings.min_item_score}, max items={settings.max_analysis_items}."
        )

        # 记录前 20 条入选新闻及其入选理由，避免 run_state 过长。
        state.decisions.extend(
            # 每条记录包含分数、标题、评分理由。
            f"Selected: {entry.score} points | {entry.item.title} | {'; '.join(entry.reasons)}"
            # 遍历前 20 条入选新闻。
            for entry in selected_scored_items[:20]
        )

        # 把每条新闻的分数、理由、是否入选写入 SQLite。
        save_scored_news_items(
            # 数据库路径。
            settings.database_path,
            # 本次运行 ID。
            state.run_id,
            # 所有评分新闻。
            scored_items,
            # 最终入选新闻。
            selected_scored_items,
        )

        # 先用 embedding 对入选新闻做事件粗聚类。
        with trace.span("cluster_scored_items") as span:
            # candidate_events 是候选事件，还没有经过 LLM 二次合并。
            candidate_events = cluster_scored_items(selected_scored_items)

            # 在 trace 里记录候选事件数量。
            span.metrics["candidate_events"] = len(candidate_events)

            # Version 13 新增：记录粗聚类压缩率。
            # 压缩率 = 入选新闻数 / 候选事件数；越接近 1，越说明仍然是一条新闻一个事件。
            span.metrics["candidate_event_compression_ratio"] = event_compression_ratio(
                len(selected_items),
                len(candidate_events),
            )

        # 把粗聚类结果写入 run_state。
        state.decisions.append(
            # 记录“多少条新闻 -> 多少个候选事件”。
            f"Event rough clustering: {len(selected_items)} selected items -> "
            f"{len(candidate_events)} candidate events."
        )

        # Version 13 新增：把候选事件压缩率写入 run_state，方便不打开 trace 也能判断聚类质量。
        state.decisions.append(
            "Event rough clustering compression ratio: "
            f"{event_compression_ratio(len(selected_items), len(candidate_events)):.2f} "
            "(selected items / candidate events)."
        )

        # 命令行提示：开始让 LLM 做事件二次合并。
        print("Start LLM event refinement...")

        # 用 LLM 判断哪些候选事件其实属于同一真实事件，并重新命名事件标题。
        with trace.span("refine_events_with_llm") as span:
            # 记录调用前累计用量，后面用差值计算本 span 消耗。
            usage_before = summarize_llm_usage()

            # events 是最终事件列表，event_decisions 是 LLM 合并过程说明。
            events, event_decisions = refine_events_with_llm(settings, candidate_events)

            # 在 trace 中记录最终事件数量。
            span.metrics["final_events"] = len(events)
            attach_llm_usage_metrics(span, usage_before)

        # 把 LLM 事件合并过程写入 run_state。
        state.decisions.extend(event_decisions)

        # 给 run_state 中的最终事件列表加一个标题。
        state.decisions.append("Final event list:")

        # 把最终事件格式化成可读文本，并写入 run_state。
        state.decisions.extend(format_events_for_state(events))

        # 把最终事件和事件-新闻关系写入 SQLite。
        save_events(settings.database_path, state.run_id, events)

        # 同步数据库中的运行状态。
        upsert_run_state(settings.database_path, state)

        # 打印去重和筛选阶段摘要。
        print(
            # 去重后唯一新闻数量。
            f"After deduplication: {len(dedup_result.unique_items)} unique items; "
            # 最终进入 DeepSeek 的新闻数量。
            f"{len(selected_items)} selected for DeepSeek."
        )

        # 优先做事件级 RAG：用本次事件去检索历史相似事件。
        with trace.span("retrieve_related_events") as span:
            # 如果历史库中有相似事件，会返回可放进 prompt 的上下文文本。
            history_context = retrieve_related_events(
                # 数据库路径。
                settings.database_path,
                # 排除本次运行，避免把刚保存的事件又检索回来。
                current_run_id=state.run_id,
                # 本次最终事件列表。
                events=events,
            )

            # 在 trace 中记录事件级 RAG 是否命中。
            span.metrics["rag_hit"] = bool(history_context)

        # 如果事件级 RAG 没命中，就回退到新闻级历史检索。
        if not history_context:
            # 用 fallback span 单独记录回退检索阶段。
            with trace.span("retrieve_related_history_fallback") as span:
                # 从历史新闻中检索和本次入选新闻相似的内容。
                history_context = retrieve_related_history(
                    # 数据库路径。
                    settings.database_path,
                    # 排除本次运行。
                    current_run_id=state.run_id,
                    # 本次入选新闻。
                    selected_items=selected_items,
                )

                # 在 trace 中记录回退 RAG 是否命中。
                span.metrics["rag_hit"] = bool(history_context)

        # 如果 RAG 找到了历史上下文，就把这件事写入决策轨迹。
        if history_context:
            # 这条记录会被 evaluation.py 用来判断 RAG 是否参与了本次运行。
            state.decisions.append(
                "RAG memory hit: retrieved related historical context for the final prompt."
            )

        # 命令行提示：开始生成日报正文。
        print("Start DeepSeek report generation...")

        # 调用 DeepSeek 生成日报正文。
        with trace.span("analyze_news") as span:
            # 记录生成日报正文前的累计 LLM 用量。
            usage_before = summarize_llm_usage()

            # analyze_news 会做分批分析和最终汇总。
            analysis = analyze_news(settings, selected_items, profile, history_context, events)

            # 在 trace 里记录模型输出正文长度，便于发现异常短输出。
            span.metrics["analysis_chars"] = len(analysis)
            attach_llm_usage_metrics(span, usage_before)

        # 把 LLM 正文、参考来源、采集状态拼装成完整 Markdown。
        with trace.span("build_report_markdown") as span:
            # build_report_markdown 返回最终待保存的 Markdown 字符串。
            markdown = build_report_markdown(
                # DeepSeek 生成的正文分析。
                analysis=analysis,
                # 本次送入模型分析的新闻，用于生成参考来源。
                items=selected_items,
                # 采集错误，写入报告底部。
                errors=errors,
                # 原始采集 JSON 路径。
                raw_data_path=raw_data_path,
            )

            # 在 trace 里记录 Markdown 总长度。
            span.metrics["markdown_chars"] = len(markdown)

        # 命令行提示：开始质量自查。
        print("Start report quality critique...")

        # 调用 critic 对报告做质量检查。
        with trace.span("critique_report") as span:
            # 记录质量自查前的累计 LLM 用量。
            usage_before = summarize_llm_usage()

            # critique_report 会返回 PASS/FAIL 和修改建议。
            critique = critique_report(settings, markdown, profile)

            # should_revise 会判断 critic 结果是否需要触发自动修订。
            span.metrics["critic_failed"] = should_revise(critique)
            attach_llm_usage_metrics(span, usage_before)

        # 把 critic 原始结果写入 run_state。
        state.critic_result = critique

        # 如果 critic 认为报告需要修订，就触发 revision 流程。
        if should_revise(critique):
            # 命令行提示：报告没有通过质量检查。
            print("Critic failed the report. Start revision...")

            # 把修订决策写入 run_state。
            state.decisions.append("Quality check result: FAIL. Revision triggered.")

            # 调用 DeepSeek 根据 critic 意见修订报告。
            with trace.span("revise_report") as span:
                # 记录修订前的累计 LLM 用量。
                usage_before = summarize_llm_usage()

                # 保留修订前的完整报告。LLM 修订有概率返回半截内容，
                # 不能让短输出直接覆盖一份已经完整生成的日报。
                original_markdown = markdown

                # 新修订链路先生成结构化计划，再只修订被点名的区块。
                revision_result = revise_report_with_plan(settings, markdown, critique, profile)
                revised_markdown = revision_result.markdown

                # 在 trace 中记录修订后文本长度。
                span.metrics["revised_markdown_chars"] = len(revised_markdown)

                # revision_plan_valid 表示模型生成的“修订计划”是否有可执行区块。
                span.metrics["revision_plan_valid"] = revision_result.plan_valid
                span.metrics["revision_plan_reason"] = revision_result.plan_reason

                # 记录真正被修订和被本地校验拒绝的区块数量。
                span.metrics["revised_section_count"] = len(revision_result.revised_sections)
                span.metrics["rejected_section_count"] = len(revision_result.rejected_sections)
                attach_llm_usage_metrics(span, usage_before)

                if revision_result.revised_sections:
                    # 记录哪些区块被模型成功更新。
                    state.decisions.append(
                        "Revision sections updated: "
                        f"{', '.join(revision_result.revised_sections)}"
                    )
                if revision_result.rejected_sections:
                    # 记录哪些区块的修订被本地完整性校验拒绝。
                    state.decisions.append(
                        "Revision sections rejected: "
                        f"{'; '.join(revision_result.rejected_sections)}"
                    )

                # Version 13 稳定性补丁：校验修订稿是否完整。
                # 如果修订稿过短或缺少关键结构，保留原报告，避免最终报告被截断。
                if revision_result.plan_valid:
                    revision_ok, revision_reason = validate_revision_report(
                        original_markdown,
                        revised_markdown,
                    )
                else:
                    revision_ok = False
                    revision_reason = revision_result.plan_reason

                # revision_accepted 是最终是否采用修订版报告。
                span.metrics["revision_accepted"] = revision_ok
                span.metrics["revision_validation_reason"] = revision_reason

                if revision_ok:
                    # 只有通过完整性校验时，才用修订版覆盖原报告。
                    markdown = revised_markdown
                    state.decisions.append(f"Revision accepted: {revision_reason}")
                else:
                    # 修订失败时保留原报告，避免短输出或坏结构破坏最终结果。
                    markdown = original_markdown
                    state.decisions.append(
                        "Revision rejected and original report kept: "
                        f"{revision_reason}"
                    )

                    # 把被拒绝的修订输出保存下来，方便事后排查模型到底返回了什么。
                    rejected_dir = settings.raw_data_dir.parent / "debug"
                    rejected_dir.mkdir(parents=True, exist_ok=True)
                    rejected_path = rejected_dir / f"{state.run_id}_rejected_revision.md"
                    rejected_path.write_text(revised_markdown, encoding="utf-8")
                    state.decisions.append(f"Rejected revision saved: {rejected_path}")

        # 如果 critic 通过，就不再额外修订。
        else:
            # 把通过结果写入 run_state。
            state.decisions.append("Quality check result: PASS. No revision needed.")

        # 保存最终 Markdown 报告。
        with trace.span("save_report"):
            # save_report 会把 markdown 写入 reports 目录，并返回路径。
            report_path = save_report(markdown, settings.report_dir, state.run_id)

        # 把最终报告路径写入 run_state。
        state.report_path = str(report_path)

        # 下面这些是 run-level metrics，表示整个运行级别的核心指标。
        trace.set_metric("raw_items", state.raw_item_count)

        # 记录去重后唯一新闻数量。
        trace.set_metric("unique_items", state.unique_item_count)

        # 记录最终入选 LLM 分析的新闻数量。
        trace.set_metric("selected_items", state.selected_item_count)

        # 记录重复新闻数量。
        trace.set_metric("duplicate_count", state.duplicate_count)

        # 记录最终事件数量。
        trace.set_metric("final_events", len(events))

        # 记录本次运行整体 LLM token 和成本估算。
        llm_usage = attach_run_llm_usage_metrics(trace)
        cost_metrics = attach_balance_cost_metrics(trace, settings, balance_before)
        if llm_usage["llm_call_count"]:
            # 如果余额差额可用，优先展示更接近账单的实际成本。
            if cost_metrics.get("llm_actual_cost_available"):
                cost_text = (
                    f"actual cost {cost_metrics['llm_actual_cost_currency']} "
                    f"{float(cost_metrics['llm_actual_cost']):.6f}"
                )
            else:
                # 否则展示按 token 单价估算的成本；默认单价为 0 时这里会显示 0。
                cost_text = f"estimated cost ${llm_usage['llm_estimated_cost_usd']:.6f}"

                # 如果余额差额不可用，把原因也写进决策轨迹。
                balance_error = str(cost_metrics.get("llm_balance_error", "") or "")
                if balance_error:
                    cost_text = f"{cost_text}; balance delta unavailable: {balance_error}"

            # 写入 run_state，方便用户不打开 trace 也能看到本次 LLM 调用规模。
            state.decisions.append(
                "LLM usage: "
                f"{llm_usage['llm_call_count']} calls, "
                f"{llm_usage['llm_total_tokens']} total tokens, "
                f"{cost_text}."
            )

        # 标记 trace 正常结束。
        trace.finish("ok")

        # 保存 trace 文件到 data/traces。
        trace_path = trace.save(trace_dir_from_data_path(settings.raw_data_dir))

        # 把 trace 路径写入 run_state，方便从 run_state 反查 trace。
        state.decisions.append(f"Trace saved: {trace_path}")

        # 保存 run_state JSON 文件。
        state_path = save_run_state(state, settings.run_log_dir)

        # 把最终报告正文和 critic 结果保存到 SQLite。
        save_report_record(
            # 数据库路径。
            settings.database_path,
            # 本次运行 ID。
            state.run_id,
            # 报告文件路径。
            report_path,
            # 最终 Markdown 正文。
            markdown,
            # critic 检查结果。
            state.critic_result,
        )

        # 最后再同步一次完整运行状态到 SQLite。
        upsert_run_state(settings.database_path, state)

        # 打印最终报告路径。
        print(f"Daily report generated: {report_path}")

        # 打印 run_state 文件路径。
        print(f"Run state saved: {state_path}")

        # 打印 trace 文件路径。
        print(f"Trace saved: {trace_path}")

        # 返回最终报告路径，方便 CLI 或调度器继续使用。
        return report_path

    # 捕获任意异常，确保失败运行也能留下 trace 和 run_state。
    except Exception:
        # 失败运行也尽量保留已完成 LLM 调用的用量信息。
        attach_run_llm_usage_metrics(trace)
        attach_balance_cost_metrics(trace, settings, balance_before)

        # 即使失败，也把 trace 标记为 error。
        trace.finish("error")

        # 保存失败 trace，这样可以知道失败发生在哪个 span。
        trace_path = trace.save(trace_dir_from_data_path(settings.raw_data_dir))

        # 把失败 trace 路径写入 run_state。
        state.decisions.append(f"Trace saved after failure: {trace_path}")

        # 保存失败时的 run_state JSON。
        save_run_state(state, settings.run_log_dir)

        # 尝试把失败状态也写入 SQLite。
        try:
            # 如果数据库可用，就保存失败状态。
            upsert_run_state(settings.database_path, state)

        # 如果数据库本身就是失败原因，不要用这里的异常覆盖原始异常。
        except Exception:
            # pass 表示忽略这里的二次异常，让下面的 raise 抛出原始错误。
            pass

        # 重新抛出原始异常，让命令行或调度器知道本次运行失败。
        raise
