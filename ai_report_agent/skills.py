"""Agent v16 skill registry.

Skill 层不替代现有日报主流程，而是把已有能力整理成可查询、可规划、
可被 MCP 或 CLI 暴露的“能力卡片”。这样项目可以继续保持确定性 pipeline，
同时具备更接近真实 Agent 系统的技能选择入口。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


SideEffect = Literal["read_only", "write_local", "expensive_run"]
CostLevel = Literal["none", "low", "medium", "high"]


@dataclass(frozen=True)
class SkillStep:
    """一个 skill 推荐执行计划中的单步。"""

    order: int
    action: str
    tool: str
    expected_output: str


@dataclass(frozen=True)
class SkillDefinition:
    """描述一个可被 Agent 选择的技能。"""

    name: str
    title: str
    summary: str
    goal: str
    category: str
    entrypoints: list[str]
    mcp_tools: list[str]
    inputs: list[str]
    outputs: list[str]
    steps: list[SkillStep]
    side_effect: SideEffect
    cost_level: CostLevel
    requires_llm: bool
    requires_network: bool
    interview_value: str


@dataclass(frozen=True)
class SkillPlan:
    """针对某个目标生成的 skill 执行计划。"""

    skill: SkillDefinition
    objective: str
    dry_run: bool
    warnings: list[str]
    plan_steps: list[SkillStep]
    next_command: str


def default_skill_catalog() -> list[SkillDefinition]:
    """返回项目内置 skill 列表。"""

    return [
        SkillDefinition(
            name="daily_report",
            title="AI 日报生成",
            summary="采集 AI 资讯，完成去重、评分、事件聚类、RAG、生成和 critic。",
            goal="把分散资讯压缩成一份可追溯的中文 AI 热点日报。",
            category="generation",
            entrypoints=[
                "python catch_ai.py --run-once",
                "MCP tool: generate_daily_report",
            ],
            mcp_tools=["generate_daily_report", "get_latest_report"],
            inputs=["sources.json", "profile.json", "feedback.json", "environment config"],
            outputs=["reports/*.md", "data/raw/*.json", "data/runs/*.json", "data/traces/*.json", "SQLite records"],
            steps=[
                SkillStep(1, "加载配置和用户偏好", "load_settings/load_profile/load_feedback", "Settings、profile、feedback rules"),
                SkillStep(2, "采集并保存原始资讯", "collect_news/save_raw_news_items", "raw items 和 source errors"),
                SkillStep(3, "去重、评分、筛选", "deduplicate_items/score_items/select_items_for_analysis", "selected news items"),
                SkillStep(4, "聚类并合并事件", "cluster_scored_items/refine_events_with_llm", "final events"),
                SkillStep(5, "检索历史记忆并生成日报", "retrieve_related_events/analyze_news", "Markdown analysis"),
                SkillStep(6, "质量自查、必要时修订并保存", "critique_report/revise_report/save_report", "report、run state、trace"),
            ],
            side_effect="expensive_run",
            cost_level="high",
            requires_llm=True,
            requires_network=True,
            interview_value="展示完整 Agent pipeline、RAG、critic、trace 和成本观测。",
        ),
        SkillDefinition(
            name="run_evaluation",
            title="离线质量评估",
            summary="读取 SQLite 和 trace，评估最近运行的健康度，不调用真实 LLM。",
            goal="回答最近几次 Agent 是否稳定、哪里退化、哪里需要优化。",
            category="evaluation",
            entrypoints=[
                "python catch_ai.py --eval --eval-limit 5",
                "MCP tool: evaluate_recent_runs",
            ],
            mcp_tools=["evaluate_recent_runs", "list_recent_runs", "get_run_trace"],
            inputs=["data/agent.sqlite3", "data/traces/*.json", "data/source_health.json"],
            outputs=["data/eval/eval_report_*.md", "data/eval/eval_report_*.json"],
            steps=[
                SkillStep(1, "读取最近运行记录", "latest_run_ids/fetch_run", "run id 列表"),
                SkillStep(2, "计算单次运行指标", "evaluate_single_run", "score、findings、token/cost metrics"),
                SkillStep(3, "汇总项目级 KPI", "build_evaluation_summary", "success rate、critic pass rate、RAG hit rate"),
                SkillStep(4, "写出评估报告", "build_evaluation_markdown", "Markdown 和 JSON 报告"),
            ],
            side_effect="write_local",
            cost_level="low",
            requires_llm=False,
            requires_network=False,
            interview_value="展示可解释评估体系，而不是只展示一次成功 demo。",
        ),
        SkillDefinition(
            name="memory_search",
            title="长期记忆检索",
            summary="查询历史事件、历史运行和 RAG 相关上下文。",
            goal="让外部 Agent 可以复盘某个主题在历史日报中的演进。",
            category="memory",
            entrypoints=[
                "MCP tool: search_events",
                "MCP tool: list_recent_events",
                "MCP tool: get_run_details",
            ],
            mcp_tools=["search_events", "list_recent_events", "get_run_details", "get_latest_report"],
            inputs=["query", "data/agent.sqlite3"],
            outputs=["events", "run details", "report markdown"],
            steps=[
                SkillStep(1, "按关键词检索历史事件", "search_events", "matched events"),
                SkillStep(2, "读取事件所属运行详情", "get_run_details", "run decisions 和 errors"),
                SkillStep(3, "必要时读取最新报告正文", "get_latest_report", "Markdown report"),
            ],
            side_effect="read_only",
            cost_level="none",
            requires_llm=False,
            requires_network=False,
            interview_value="展示 SQLite 长期记忆和事件级 RAG 的可查询性。",
        ),
        SkillDefinition(
            name="source_diagnosis",
            title="资讯源治理",
            summary="检查 RSS 来源健康、失败来源和来源覆盖规划。",
            goal="定位采集失败、来源覆盖不足和需要人工维护的信息源。",
            category="operations",
            entrypoints=[
                "MCP tool: get_source_health",
                "MCP tool: get_source_plan",
            ],
            mcp_tools=["get_source_health", "get_source_plan"],
            inputs=["sources.json", "data/source_health.json", "data/source_plan.json"],
            outputs=["source health summary", "failing sources", "source plan recommendations"],
            steps=[
                SkillStep(1, "读取来源健康状态", "get_source_health", "success/failure counters"),
                SkillStep(2, "筛出连续失败来源", "get_source_health", "failing source list"),
                SkillStep(3, "读取来源规划建议", "get_source_plan", "coverage recommendations"),
            ],
            side_effect="read_only",
            cost_level="none",
            requires_llm=False,
            requires_network=False,
            interview_value="展示 Agent 对输入质量和采集可靠性的自我诊断能力。",
        ),
        SkillDefinition(
            name="feedback_learning",
            title="反馈学习",
            summary="把用户对事件的喜欢、点踩和备注沉淀成下一轮评分规则。",
            goal="让 Agent 根据历史反馈逐步贴近用户偏好。",
            category="learning",
            entrypoints=[
                "python catch_ai.py --feedback",
                "MCP tool: submit_event_feedback",
            ],
            mcp_tools=["submit_event_feedback", "list_recent_events"],
            inputs=["event_id", "feedback_type", "note", "feedback.json", "SQLite event_feedback"],
            outputs=["updated feedback.json", "event_feedback rows"],
            steps=[
                SkillStep(1, "列出最近事件", "list_recent_events/load_events_for_feedback", "feedback candidates"),
                SkillStep(2, "保存用户反馈", "submit_event_feedback/save_event_feedback", "event_feedback record"),
                SkillStep(3, "从反馈历史生成规则", "build_feedback_rules_from_history", "dynamic FeedbackRules"),
                SkillStep(4, "合并并保存反馈规则", "merge_feedback_rules/save_feedback", "updated feedback.json"),
            ],
            side_effect="write_local",
            cost_level="low",
            requires_llm=False,
            requires_network=False,
            interview_value="展示人类反馈闭环和个性化评分规则。",
        ),
        SkillDefinition(
            name="mcp_control",
            title="MCP 控制面",
            summary="通过 MCP 暴露 Agent 能力，供外部客户端按工具方式调用。",
            goal="让项目可以被支持 MCP 的客户端编排，而不是只能从命令行运行。",
            category="integration",
            entrypoints=[
                "python catch_ai.py --mcp",
                "python test_mcp_client.py",
            ],
            mcp_tools=["list_agent_skills", "plan_agent_skill", "recommend_agent_skills"],
            inputs=["stdio MCP client requests"],
            outputs=["structured tool results"],
            steps=[
                SkillStep(1, "启动 stdio MCP server", "run_mcp_server/create_mcp_app", "MCP server process"),
                SkillStep(2, "列出可用工具和 skill", "list_tools/list_agent_skills", "tool catalog"),
                SkillStep(3, "按目标选择 skill 并规划调用", "recommend_agent_skills/plan_agent_skill", "skill plan"),
            ],
            side_effect="read_only",
            cost_level="none",
            requires_llm=False,
            requires_network=False,
            interview_value="展示工具协议、外部编排和 Agent 能力发现。",
        ),
    ]


SKILL_CATALOG = {
    skill.name: skill
    for skill in default_skill_catalog()
}


def list_skills() -> list[SkillDefinition]:
    """按注册顺序返回所有 skill。"""

    return list(SKILL_CATALOG.values())


def get_skill(name: str) -> SkillDefinition:
    """按名称读取 skill，不存在时抛出清晰错误。"""

    normalized = name.strip().lower()
    try:
        return SKILL_CATALOG[normalized]
    except KeyError as exc:
        valid_names = ", ".join(SKILL_CATALOG)
        raise ValueError(f"未知 skill：{name}。可选值：{valid_names}") from exc


def skill_to_dict(skill: SkillDefinition) -> dict[str, object]:
    """把 skill dataclass 转成适合 MCP/JSON 返回的 dict。"""

    return asdict(skill)


def list_skills_payload() -> list[dict[str, object]]:
    """返回所有 skill 的 JSON 友好结构。"""

    return [skill_to_dict(skill) for skill in list_skills()]


def build_skill_plan(
    skill_name: str,
    objective: str = "",
    dry_run: bool = True,
) -> SkillPlan:
    """基于 skill 元数据生成一个可解释执行计划。"""

    skill = get_skill(skill_name)
    warnings: list[str] = []

    if skill.side_effect == "expensive_run":
        warnings.append("该 skill 会触发完整运行，可能访问网络并调用真实 LLM。")
    elif skill.side_effect == "write_local":
        warnings.append("该 skill 会写入本地文件或 SQLite。")

    if skill.requires_network:
        warnings.append("该 skill 需要访问外部网络。")
    if skill.requires_llm:
        warnings.append("该 skill 需要有效的 LLM API 配置。")
    if dry_run:
        warnings.append("当前是 dry-run 计划，不会真正执行工具。")

    return SkillPlan(
        skill=skill,
        objective=objective.strip() or skill.goal,
        dry_run=dry_run,
        warnings=warnings,
        plan_steps=skill.steps,
        next_command=skill.entrypoints[0] if skill.entrypoints else "",
    )


def plan_to_dict(plan: SkillPlan) -> dict[str, object]:
    """把 SkillPlan 转成 JSON 友好结构。"""

    return asdict(plan)


def recommend_skills(query: str, limit: int = 3) -> list[dict[str, object]]:
    """根据简单关键词匹配推荐 skill。

    这里故意不用 LLM，让推荐在测试和离线环境中保持确定性。
    """

    normalized_query = query.strip().lower()
    if not normalized_query:
        return []

    matches: list[tuple[int, SkillDefinition]] = []
    for skill in list_skills():
        haystack = " ".join(
            [
                skill.name,
                skill.title,
                skill.summary,
                skill.goal,
                skill.category,
                " ".join(skill.mcp_tools),
                " ".join(skill.entrypoints),
            ]
        ).lower()

        score = 0
        for token in normalized_query.split():
            if token and token in haystack:
                score += 2
        if normalized_query in haystack:
            score += 3

        # 中文查询经常没有空格，这里补充几个常见意图的轻量映射。
        intent_keywords = {
            "日报": "daily_report",
            "生成": "daily_report",
            "最近": "run_evaluation",
            "怎么样": "run_evaluation",
            "健康": "run_evaluation",
            "评估": "run_evaluation",
            "质量": "run_evaluation",
            "记忆": "memory_search",
            "历史": "memory_search",
            "来源": "source_diagnosis",
            "rss": "source_diagnosis",
            "反馈": "feedback_learning",
            "偏好": "feedback_learning",
            "mcp": "mcp_control",
            "工具": "mcp_control",
        }
        for keyword, skill_name in intent_keywords.items():
            if keyword in normalized_query and skill.name == skill_name:
                score += 5

        if score:
            matches.append((score, skill))

    ranked = sorted(matches, key=lambda item: (-item[0], item[1].name))[:limit]
    return [
        {
            "name": skill.name,
            "title": skill.title,
            "score": score,
            "summary": skill.summary,
            "side_effect": skill.side_effect,
            "cost_level": skill.cost_level,
        }
        for score, skill in ranked
    ]


def format_skill_catalog(skills: list[SkillDefinition] | None = None) -> str:
    """把 skill catalog 格式化成 CLI 友好的文本。"""

    selected_skills = skills or list_skills()
    lines = ["Agent v16 skills:", ""]
    for skill in selected_skills:
        lines.append(f"- {skill.name} | {skill.title}")
        lines.append(f"  {skill.summary}")
        lines.append(f"  side_effect={skill.side_effect}, cost={skill.cost_level}")
    return "\n".join(lines)


def format_skill_plan(plan: SkillPlan) -> str:
    """把 SkillPlan 格式化成 CLI 友好的文本。"""

    lines = [
        f"Skill: {plan.skill.name} | {plan.skill.title}",
        f"Objective: {plan.objective}",
        f"Dry run: {str(plan.dry_run).lower()}",
        "",
        "Warnings:",
    ]

    if plan.warnings:
        lines.extend(f"- {warning}" for warning in plan.warnings)
    else:
        lines.append("- none")

    lines.extend(["", "Plan:"])
    for step in plan.plan_steps:
        lines.append(
            f"{step.order}. {step.action} -> {step.tool} -> {step.expected_output}"
        )

    if plan.next_command:
        lines.extend(["", f"Suggested command: {plan.next_command}"])

    return "\n".join(lines)
