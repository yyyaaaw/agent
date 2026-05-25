"""AI报告 agent的离线评估。

版本 9 增加了一个实用的评估层。它不需要调用另一个大型语言模型；相反，它读取现有的 SQLite 数据库、运行状态 JSON 文件和追踪 JSON 文件，以回答一个简单但重要的问题：

“这个代理随着时间推移是否在变得更健康？”

这些指标故意设计为可解释的。它们并不是完美的学术基准，但对于简历项目来说是很好的工程信号：
- 数据收集是否成功？
- 去重是否减少了噪声？
- 事件聚类是否将许多新闻条目压缩成更少的事件？
- RAG 是否找到了历史上下文？
- 批评者是否通过了报告？
- 来源失败是否在可控范围内？
- 每个阶段花费了多长时间？
"""

from __future__ import annotations

# json 用来读取 run_state/trace 中的结构化字段，也用于生成评估 JSON。
import json

# math 用于计算 P95 等统计指标时的向上取整。
import math

# sqlite3.Row 是 fetch_run 的返回类型之一。
import sqlite3

# asdict 把 dataclass 转成普通 dict；dataclass 用来定义评估结果结构。
from dataclasses import asdict, dataclass

# datetime 用来生成评估报告时间戳。
from datetime import datetime

# Path 用来处理报告输出路径和 trace 文件路径。
from pathlib import Path

# Settings 提供数据库路径、data 目录等配置。
from ai_report_agent.config import Settings

# connect / initialize_database 复用数据库连接和建表逻辑。
from ai_report_agent.database import connect, initialize_database


@dataclass(frozen=True)
class EvaluationResult:
    """单次运行的结构化评估结果。

    这个对象不是直接给用户看的 Markdown，而是先把所有指标整理成稳定字段。
    后续可以同时写 JSON、写 Markdown，也方便面试时解释每个指标从哪里来。
    """

    # 本次运行的唯一 ID，通常和 trace_*.json 文件名中的 ID 一致。
    run_id: str

    # 离线评估得到的总分，范围限制在 0-100。
    score: int

    # 本次运行是否干净完成：trace 状态为 ok，并且数据库里记录了 report_path。
    run_success: bool

    # trace 文件中的整体状态；如果找不到 trace 文件，则是 missing。
    trace_status: str

    # 本次日报最终生成的 Markdown 文件路径。
    report_path: str

    # 采集阶段拿到的原始新闻条目数量。
    raw_items: int

    # 去重后剩下的新闻条目数量。
    unique_items: int

    # 进入 LLM 分析或事件聚类的精选新闻条目数量。
    selected_items: int

    # 去重阶段识别出的重复条目数量。
    duplicate_count: int

    # 粗聚类阶段形成的候选事件数量。
    candidate_event_count: int

    # selected_items / candidate_event_count，用来衡量候选事件压缩效果。
    candidate_event_compression_ratio: float

    # 最终写入 events 表的事件数量。
    event_count: int

    # 平均每个最终事件包含多少条被选中的新闻。
    avg_items_per_event: float

    # 本次采集中失败的来源数量，来自 source_errors 表。
    source_error_count: int

    # 本次运行是否命中过长期记忆/RAG 上下文。
    rag_hit: bool

    # critic 自查是否通过。
    critic_passed: bool

    # critic 是否提示了“无来源支撑、编造、幻觉”等事实风险。
    critic_has_unsupported_fact: bool

    # 是否触发过报告修订流程。
    revision_triggered: bool

    # 修订结果是否被系统接受；没有触发修订时为 None。
    revision_accepted: bool | None

    # 用户对本次事件留下的反馈数量。
    feedback_count: int

    # trace 记录的整次运行耗时，单位毫秒。
    trace_duration_ms: float

    # 本次运行调用 LLM 的次数。
    llm_call_count: int

    # prompt 输入 token 数。
    llm_prompt_tokens: int

    # completion 输出 token 数。
    llm_completion_tokens: int

    # 输入和输出合计 token 数。
    llm_total_tokens: int

    # 根据配置价格估算的美元成本。
    llm_estimated_cost_usd: float

    # 是否拿到了供应商余额差额计算出来的实际成本。
    llm_actual_cost_available: bool

    # 通过余额差额计算出的实际成本。
    llm_actual_cost: float

    # 实际成本的币种，例如 CNY、USD；没有实际成本时为空字符串。
    llm_actual_cost_currency: str

    # LLM 调用前后账户余额的变化量。
    llm_balance_delta: float

    # 成本统计模式，例如 actual、estimated 或 unavailable。
    llm_cost_mode: str

    # 查询余额或计算成本时的错误信息；正常时为空。
    llm_balance_error: str

    # trace 中耗时最长的 span 名称，用来定位性能瓶颈。
    slowest_span: str

    # 耗时最长 span 的耗时，单位毫秒。
    slowest_span_duration_ms: float

    # 离线评估器给出的扣分原因或正向提示。
    findings: list[str]


@dataclass(frozen=True)
class SourceHealthSummary:
    """RSS 来源健康状态的汇总指标。"""

    # source_health.json 中追踪的来源总数。
    source_count: int

    # 最近状态为 success 的来源数量。
    successful_sources: int

    # 最近状态不是 success 的来源数量。
    failing_sources: int

    # 所有来源累计成功采集次数。
    total_success_count: int

    # 所有来源累计失败采集次数。
    total_failure_count: int

    # 来源累计成功率，单位是百分比。
    source_success_rate: float

    # 当前失败来源的名称列表。
    failing_source_names: list[str]


@dataclass(frozen=True)
class EvaluationSummary:
    """多次运行聚合后的项目级 KPI。"""

    # 生成评估报告的时间。
    generated_at: str

    # 本次纳入评估的运行次数。
    evaluated_runs: int

    # 多次运行的平均离线评分。
    average_score: float

    # 运行成功率，单位是百分比。
    run_success_rate: float

    # critic 通过率，单位是百分比。
    critic_pass_rate: float

    # 幻觉风险代理指标：critic 提到 unsupported/fabricated 等问题的比例。
    hallucination_proxy_rate: float

    # RSS 来源健康成功率，来自 source_health.json。
    source_success_rate: float

    # 多次运行中命中过 RAG 的比例。
    rag_hit_rate: float

    # 候选事件平均压缩比。
    average_event_compression_ratio: float

    # 最终事件平均包含的新闻条目数。
    average_items_per_event: float

    # 平均运行耗时，单位毫秒。
    average_duration_ms: float

    # P95 运行耗时，表示大多数运行不会超过这个时长。
    p95_duration_ms: float

    # 多次运行累计 LLM 调用次数。
    total_llm_calls: int

    # 多次运行累计 LLM token 数。
    total_llm_tokens: int

    # 有实际成本数据的运行次数。
    actual_llm_cost_available_runs: int

    # 多次运行累计实际成本。
    actual_llm_cost_total: float

    # 实际成本币种；混合币种时标记为 mixed。
    actual_llm_cost_currency: str

    # 多次运行累计估算美元成本。
    estimated_llm_cost_usd: float

    # 单次运行平均估算美元成本。
    average_llm_cost_per_run_usd: float

    # 在触发修订的运行中，修订结果被接受的比例。
    revision_accept_rate: float


def run_evaluation(settings: Settings, limit: int = 5) -> Path:
    """评估最近若干次 Agent 运行，并保存 Markdown/JSON 报告。

    这是 `python catch_ai.py --eval` 调用的入口。
    它不会采集新闻，也不会调用 LLM，只读取已有数据库和 trace。
    """

    # 先确保数据库表存在。即使还没有运行记录，也能生成“没有记录”的评估报告。
    initialize_database(settings.database_path)

    # 从 SQLite 中按 started_at 倒序读取最近的 run_id。
    run_ids = latest_run_ids(settings.database_path, limit)

    # 逐个 run_id 计算可解释指标。
    results = [
        evaluate_single_run(settings, run_id)
        for run_id in run_ids
    ]

    # 来源健康状态保存在 data/source_health.json。
    source_health = read_source_health_summary(settings.raw_data_dir.parent / "source_health.json")

    # 把多次运行指标聚合成总览 KPI。
    summary = build_evaluation_summary(results, source_health)

    # 评估报告统一写到 data/eval。
    output_dir = settings.raw_data_dir.parent / "eval"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 使用时间戳生成文件名，避免覆盖旧评估报告。
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    markdown_path = output_dir / f"eval_report_{timestamp}.md"
    json_path = output_dir / f"eval_report_{timestamp}.json"

    # Markdown 面向人工阅读，JSON 面向后续自动分析。
    markdown_path.write_text(
        build_evaluation_markdown(results, summary, source_health),
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps(
            {
                "summary": asdict(summary),
                "source_health": asdict(source_health),
                "runs": [asdict(result) for result in results],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return markdown_path


def latest_run_ids(database_path: Path, limit: int) -> list[str]:
    """从 SQLite 读取最近的 run_id，最新的排在前面。"""

    # 这里只读取 runs 表的 ID，不加载完整记录，避免评估大量历史运行时做无谓的数据搬运。
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT run_id
            FROM runs
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    # sqlite3.Row 支持按列名访问；统一转成 str，方便后续拼 trace 文件名。
    return [str(row["run_id"]) for row in rows]


def evaluate_single_run(settings: Settings, run_id: str) -> EvaluationResult:
    """计算单次运行的可解释健康指标。"""

    # runs 表保存主流程的计数、路径、决策轨迹和 critic 结果。
    run = fetch_run(settings.database_path, run_id)

    # events / source_errors / event_feedback 分别衡量事件产出、采集失败和用户反馈。
    event_count = count_rows(settings.database_path, "events", run_id)
    source_error_count = count_rows(settings.database_path, "source_errors", run_id)
    feedback_count = count_feedback_for_run(settings.database_path, run_id)

    # SQLite 里取出的数值可能是 int，也可能表现为可转换对象；这里统一转 int。
    raw_items = int(run["raw_item_count"])
    unique_items = int(run["unique_item_count"])
    selected_items = int(run["selected_item_count"])
    duplicate_count = int(run["duplicate_count"])
    decisions = json.loads(run["decisions_json"] or "[]")
    critic_result = str(run["critic_result"] or "")
    report_path = str(run["report_path"] or "")

    # trace 记录阶段耗时和 span 级指标；如果缺失，则用空 dict 兜底。
    trace_payload = read_trace_payload(settings.raw_data_dir.parent / "traces", run_id)
    trace_status = str(trace_payload.get("status", "missing")) if trace_payload else "missing"
    trace_duration_ms = float(trace_payload.get("duration_ms", 0.0)) if trace_payload else 0.0
    trace_metrics = trace_payload.get("metrics", {}) if trace_payload else {}
    if not isinstance(trace_metrics, dict):
        trace_metrics = {}

    # 候选事件压缩率来自 cluster_scored_items span，用来判断粗聚类是否把新闻合成事件。
    candidate_event_count = int(trace_span_metric(trace_payload, "cluster_scored_items", "candidate_events", 0))
    candidate_event_compression_ratio = float(
        trace_span_metric(trace_payload, "cluster_scored_items", "candidate_event_compression_ratio", 0.0)
    )

    # 兼容旧 trace：如果 span 没记录压缩率，但有 selected/event 数量，就现场计算。
    if not candidate_event_compression_ratio and selected_items and candidate_event_count:
        candidate_event_compression_ratio = round(selected_items / candidate_event_count, 2)

    # 最终事件平均包含多少条新闻，越高通常说明事件合并越有效。
    avg_items_per_event = round(selected_items / event_count, 2) if event_count else 0.0

    # RAG 是否命中通过 decisions 文本判断，因为 agent.py 会写入明确的 RAG 记录。
    rag_hit = any("RAG" in str(decision) for decision in decisions)

    # critic_passed 是质量自查是否通过；unsupported_fact 是幻觉风险代理指标。
    critic_passed = is_critic_passed(critic_result)
    critic_has_unsupported_fact = has_unsupported_fact_issue(critic_result)

    # 修订流程是否触发和是否被接受来自 trace span。
    revision_triggered = trace_has_span(trace_payload, "revise_report")
    revision_accepted = trace_optional_bool_metric(trace_payload, "revise_report", "revision_accepted")

    # 找出最慢阶段，便于定位性能瓶颈。
    slowest_span, slowest_span_duration_ms = slowest_trace_span(trace_payload)

    # 成功运行需要 trace 状态 OK 且确实记录了报告路径。
    run_success = trace_status == "ok" and bool(report_path)

    # 把指标转成 0-100 分和发现项。
    score, findings = score_run(
        run_success=run_success,
        raw_items=raw_items,
        unique_items=unique_items,
        selected_items=selected_items,
        duplicate_count=duplicate_count,
        candidate_event_compression_ratio=candidate_event_compression_ratio,
        event_count=event_count,
        avg_items_per_event=avg_items_per_event,
        source_error_count=source_error_count,
        rag_hit=rag_hit,
        critic_passed=critic_passed,
    )

    # 最后统一组装 EvaluationResult。这样上层不需要知道指标来自 SQLite、trace 还是文件系统。
    return EvaluationResult(
        run_id=run_id,
        score=score,
        run_success=run_success,
        trace_status=trace_status,
        report_path=report_path,
        raw_items=raw_items,
        unique_items=unique_items,
        selected_items=selected_items,
        duplicate_count=duplicate_count,
        candidate_event_count=candidate_event_count,
        candidate_event_compression_ratio=round(candidate_event_compression_ratio, 2),
        event_count=event_count,
        avg_items_per_event=avg_items_per_event,
        source_error_count=source_error_count,
        rag_hit=rag_hit,
        critic_passed=critic_passed,
        critic_has_unsupported_fact=critic_has_unsupported_fact,
        revision_triggered=revision_triggered,
        revision_accepted=revision_accepted,
        feedback_count=feedback_count,
        trace_duration_ms=trace_duration_ms,
        # 以下 LLM 成本和 token 指标来自 trace 顶层 metrics；缺失时用 0 或空字符串兜底。
        llm_call_count=int(trace_metrics.get("llm_call_count", 0) or 0),
        llm_prompt_tokens=int(trace_metrics.get("llm_prompt_tokens", 0) or 0),
        llm_completion_tokens=int(trace_metrics.get("llm_completion_tokens", 0) or 0),
        llm_total_tokens=int(trace_metrics.get("llm_total_tokens", 0) or 0),
        llm_estimated_cost_usd=float(trace_metrics.get("llm_estimated_cost_usd", 0.0) or 0.0),
        llm_actual_cost_available=metric_bool(trace_metrics.get("llm_actual_cost_available", False)),
        llm_actual_cost=float(trace_metrics.get("llm_actual_cost", 0.0) or 0.0),
        llm_actual_cost_currency=str(trace_metrics.get("llm_actual_cost_currency", "") or ""),
        llm_balance_delta=float(trace_metrics.get("llm_balance_delta", 0.0) or 0.0),
        llm_cost_mode=str(trace_metrics.get("llm_cost_mode", "") or ""),
        llm_balance_error=str(trace_metrics.get("llm_balance_error", "") or ""),
        slowest_span=slowest_span,
        slowest_span_duration_ms=slowest_span_duration_ms,
        findings=findings,
    )


def fetch_run(database_path: Path, run_id: str) -> sqlite3.Row:
    """读取一条 runs 记录；不存在时抛出清晰错误。"""

    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()

    # 没有 run 记录说明调用方传入的 run_id 不合法，继续评估只会产生误导性结果。
    if row is None:
        raise RuntimeError(f"Run not found: {run_id}")
    return row


def count_rows(database_path: Path, table: str, run_id: str) -> int:
    """统计某次运行在已知表中的记录数。"""

    # table 不能直接作为 SQL 参数绑定，所以必须白名单校验，避免 SQL 注入。
    if table not in {"events", "source_errors"}:
        raise ValueError(f"Unsupported table: {table}")

    with connect(database_path) as connection:
        row = connection.execute(
            f"SELECT COUNT(*) AS count FROM {table} WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    return int(row["count"])


def count_feedback_for_run(database_path: Path, run_id: str) -> int:
    """统计某次运行的事件收到过多少条用户反馈。"""

    # event_feedback 本身没有 run_id，所以需要通过 events 表把 feedback 关联回具体运行。
    with connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM event_feedback feedback
            JOIN events event ON event.id = feedback.event_id
            WHERE event.run_id = ?
            """,
            (run_id,),
        ).fetchone()
    return int(row["count"])


def read_trace_payload(trace_dir: Path, run_id: str) -> dict:
    """如果 trace 文件存在，就读取 trace JSON。"""

    # trace 文件名约定为 trace_<run_id>.json，和 observability.py 中的写入逻辑保持一致。
    trace_path = trace_dir / f"trace_{run_id}.json"
    if not trace_path.exists():
        return {}

    # trace 是本地 JSON 文件，评估阶段只读取它，不会再次执行任何 Agent 步骤。
    return json.loads(trace_path.read_text(encoding="utf-8"))


def trace_spans(trace_payload: dict) -> list[dict]:
    """从 trace payload 中取出 span 列表，并过滤非 dict 项。"""

    # 过滤类型可以避免 trace 文件被手动修改或版本变更后，一个坏条目拖垮整个评估。
    spans = trace_payload.get("spans", []) if trace_payload else []
    return [span for span in spans if isinstance(span, dict)]


def trace_has_span(trace_payload: dict, span_name: str) -> bool:
    """判断某个命名 span 是否存在。"""

    return any(span.get("name") == span_name for span in trace_spans(trace_payload))


def trace_span_metric(
    trace_payload: dict,
    span_name: str,
    metric_name: str,
    default: int | float | str | bool,
) -> int | float | str | bool:
    """读取某个 span 中的一项 metric。"""

    # 同名 span 理论上不应该大量重复；这里读取第一个匹配项，符合当前 trace 写入约定。
    for span in trace_spans(trace_payload):
        if span.get("name") != span_name:
            continue
        metrics = span.get("metrics", {})
        if isinstance(metrics, dict):
            return metrics.get(metric_name, default)
    return default


def trace_optional_bool_metric(trace_payload: dict, span_name: str, metric_name: str) -> bool | None:
    """读取可选布尔 metric；缺失时返回 None。"""

    # None 表示“没有记录这个指标”，False 表示“明确记录为否”，两者在报告里含义不同。
    value = trace_span_metric(trace_payload, span_name, metric_name, None)
    if value is None:
        return None
    return bool(value)


def slowest_trace_span(trace_payload: dict) -> tuple[str, float]:
    """返回耗时最长的 span 名称和耗时。"""

    spans = trace_spans(trace_payload)
    if not spans:
        return "", 0.0

    # duration_ms 缺失时按 0 处理，保证 max() 不会因为脏数据报错。
    slowest = max(spans, key=lambda span: float(span.get("duration_ms", 0.0) or 0.0))
    return str(slowest.get("name", "")), float(slowest.get("duration_ms", 0.0) or 0.0)


def is_critic_passed(critic_result: str) -> bool:
    """判断 critic 文本是否表示通过。"""

    # 约定：只要包含 FAIL 就认为未通过；空 critic 也不算通过。
    normalized = critic_result.strip().upper()
    return bool(normalized) and "FAIL" not in normalized


def has_unsupported_fact_issue(critic_result: str) -> bool:
    """检测 critic 是否提到无来源支撑、编造或幻觉风险。"""

    # 这不是严格事实性评测，只是一个可解释的“幻觉风险代理指标”。
    normalized = critic_result.lower()
    patterns = [
        "无来源支撑",
        "没有来源支撑",
        "无法从参考来源得到支撑",
        "无法从来源得到支撑",
        "未经验证",
        "编造",
        "幻觉",
        "unsupported",
        "not supported by",
        "fabricated",
        "hallucination",
    ]
    return any(pattern in normalized for pattern in patterns)


def read_source_health_summary(source_health_path: Path) -> SourceHealthSummary:
    """读取来源健康 JSON，并计算聚合可靠性指标。"""

    # 没有健康文件时返回全 0，避免评估命令失败。
    if not source_health_path.exists():
        return SourceHealthSummary(
            source_count=0,
            successful_sources=0,
            failing_sources=0,
            total_success_count=0,
            total_failure_count=0,
            source_success_rate=0.0,
            failing_source_names=[],
        )

    payload = json.loads(source_health_path.read_text(encoding="utf-8"))

    # source_health.json 按来源名索引，这里只保留值为 dict 的条目。
    entries = [value for value in payload.values() if isinstance(value, dict)]
    total_success = sum(int(entry.get("success_count", 0) or 0) for entry in entries)
    total_failure = sum(int(entry.get("failure_count", 0) or 0) for entry in entries)
    attempts = total_success + total_failure
    failing_names = [
        str(entry.get("source_name", "unknown"))
        for entry in entries
        if str(entry.get("last_status", "")) != "success"
    ]

    return SourceHealthSummary(
        source_count=len(entries),
        successful_sources=len(entries) - len(failing_names),
        failing_sources=len(failing_names),
        total_success_count=total_success,
        total_failure_count=total_failure,
        source_success_rate=percentage(total_success, attempts),
        failing_source_names=failing_names,
    )


def build_evaluation_summary(
    results: list[EvaluationResult],
    source_health: SourceHealthSummary,
) -> EvaluationSummary:
    """根据多次运行结果计算项目级 KPI。"""

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 没有运行记录也要返回完整结构，方便 Markdown 渲染。
    if not results:
        return EvaluationSummary(
            generated_at=generated_at,
            evaluated_runs=0,
            average_score=0.0,
            run_success_rate=0.0,
            critic_pass_rate=0.0,
            hallucination_proxy_rate=0.0,
            source_success_rate=source_health.source_success_rate,
            rag_hit_rate=0.0,
            average_event_compression_ratio=0.0,
            average_items_per_event=0.0,
            average_duration_ms=0.0,
            p95_duration_ms=0.0,
            total_llm_calls=0,
            total_llm_tokens=0,
            actual_llm_cost_available_runs=0,
            actual_llm_cost_total=0.0,
            actual_llm_cost_currency="",
            estimated_llm_cost_usd=0.0,
            average_llm_cost_per_run_usd=0.0,
            revision_accept_rate=0.0,
        )

    # 修订接受率只在触发过修订的运行中计算。
    revision_runs = [result for result in results if result.revision_triggered]
    accepted_revisions = [
        result
        for result in revision_runs
        if result.revision_accepted is True
    ]
    actual_cost_results = [
        result
        for result in results
        if result.llm_actual_cost_available
    ]

    # 如果所有实际成本都是同一币种，就展示该币种；混合币种则标记 mixed。
    actual_cost_currencies = sorted(
        {
            result.llm_actual_cost_currency
            for result in actual_cost_results
            if result.llm_actual_cost_currency
        }
    )
    actual_cost_currency = (
        actual_cost_currencies[0]
        if len(actual_cost_currencies) == 1
        else "mixed"
        if actual_cost_currencies
        else ""
    )

    return EvaluationSummary(
        generated_at=generated_at,
        evaluated_runs=len(results),
        # 下面这些聚合指标会出现在 Markdown 顶部 KPI 表中，便于快速判断项目近期状态。
        average_score=round(average([result.score for result in results]), 1),
        run_success_rate=percentage(count_true(result.run_success for result in results), len(results)),
        critic_pass_rate=percentage(count_true(result.critic_passed for result in results), len(results)),
        hallucination_proxy_rate=percentage(
            count_true(result.critic_has_unsupported_fact for result in results),
            len(results),
        ),
        source_success_rate=source_health.source_success_rate,
        rag_hit_rate=percentage(count_true(result.rag_hit for result in results), len(results)),
        average_event_compression_ratio=round(
            average([result.candidate_event_compression_ratio for result in results]),
            2,
        ),
        average_items_per_event=round(average([result.avg_items_per_event for result in results]), 2),
        average_duration_ms=round(average([result.trace_duration_ms for result in results]), 2),
        p95_duration_ms=round(percentile([result.trace_duration_ms for result in results], 95), 2),
        total_llm_calls=sum(result.llm_call_count for result in results),
        total_llm_tokens=sum(result.llm_total_tokens for result in results),
        actual_llm_cost_available_runs=len(actual_cost_results),
        actual_llm_cost_total=round(sum(result.llm_actual_cost for result in actual_cost_results), 6),
        actual_llm_cost_currency=actual_cost_currency,
        estimated_llm_cost_usd=round(sum(result.llm_estimated_cost_usd for result in results), 6),
        average_llm_cost_per_run_usd=round(
            average([result.llm_estimated_cost_usd for result in results]),
            6,
        ),
        revision_accept_rate=percentage(len(accepted_revisions), len(revision_runs)),
    )


def count_true(values) -> int:
    """统计可迭代对象中为真的值数量。"""

    # values 可能是生成器，所以这里边遍历边计数，而不是先转成 list。
    return sum(1 for value in values if value)


def average(values: list[int | float]) -> float:
    """计算数值列表平均值；空列表返回 0。"""

    # 空列表返回 0.0，避免没有运行记录时出现除零错误。
    return sum(values) / len(values) if values else 0.0


def percentile(values: list[int | float], percentile_value: int) -> float:
    """用 nearest-rank 方法计算百分位数。"""

    if not values:
        return 0.0

    # nearest-rank 的位置从 1 开始，这里转换成 Python 的 0-based 下标。
    sorted_values = sorted(float(value) for value in values)
    index = max(0, min(len(sorted_values) - 1, math.ceil(percentile_value / 100 * len(sorted_values)) - 1))
    return sorted_values[index]


def percentage(numerator: int, denominator: int) -> float:
    """计算百分比，并保留一位小数。"""

    # denominator 为 0 时返回 0，保证“没有样本”的评估报告也能正常生成。
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 1)


def metric_bool(value: object) -> bool:
    """从 JSON metric 中安全读取布尔值。"""

    # trace 里可能是真正的 bool，也可能是字符串形式的 true/yes/1。
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def score_run(
    *,
    run_success: bool,
    raw_items: int,
    unique_items: int,
    selected_items: int,
    duplicate_count: int,
    candidate_event_compression_ratio: float,
    event_count: int,
    avg_items_per_event: float,
    source_error_count: int,
    rag_hit: bool,
    critic_passed: bool,
) -> tuple[int, list[str]]:
    """把一组指标转换成 0-100 的简单健康分。"""

    # 评分从 100 开始扣分，findings 记录每次扣分的解释。
    score = 100
    findings: list[str] = []

    # 1. 先检查主流程是否完整完成；流程失败会严重影响报告可信度。
    if not run_success:
        score -= 25
        findings.append("Run did not complete cleanly or no report path was recorded.")

    # 2. 检查采集规模。没有原始数据时，后续所有分析都没有基础。
    if raw_items <= 0:
        score -= 35
        findings.append("Collection produced no raw items.")
    elif raw_items < 10:
        score -= 10
        findings.append("Collection volume is low; the report may miss important events.")

    if unique_items <= 0:
        score -= 25
        findings.append("No unique items survived deduplication.")

    # 3. 检查筛选阶段是否过严或过松；两种情况都会影响日报质量。
    if selected_items <= 0:
        score -= 25
        findings.append("No items were selected for model analysis.")
    elif raw_items and selected_items / raw_items > 0.9:
        score -= 6
        findings.append("Selection is broad; the scorer may not be filtering enough noise.")

    if duplicate_count == 0 and raw_items >= 20:
        score -= 4
        findings.append("No duplicates were detected in a large batch; dedup rules may be too weak.")

    # 4. 检查事件聚类是否有效：最终事件太多，说明新闻没有被充分合并。
    if event_count <= 0:
        score -= 20
        findings.append("No final events were produced.")
    elif selected_items and event_count >= selected_items * 0.9:
        score -= 10
        findings.append("Event compression is weak; many news items may still be one-item events.")

    if candidate_event_compression_ratio and candidate_event_compression_ratio < 1.3:
        score -= 6
        findings.append("Candidate event compression ratio is below the target threshold of 1.30.")

    if avg_items_per_event >= 2:
        # 这条是正向发现，不扣分，用来提示事件聚类表现不错。
        findings.append("Event clustering is compressing related news into multi-item events.")

    # 5. 检查工程稳定性：来源失败、RAG 未命中、critic FAIL 都是需要关注的信号。
    if source_error_count >= 3:
        score -= 8
        findings.append("Several sources failed during collection; source reliability needs attention.")

    if not rag_hit:
        score -= 6
        findings.append("No RAG hit was recorded; long-term memory did not help this run.")

    if not critic_passed:
        score -= 12
        findings.append("The critic marked the report as FAIL or found hard quality issues.")

    if not findings:
        findings.append("No major quality risks detected by the offline evaluator.")

    return max(0, min(100, score)), findings


def build_evaluation_markdown(
    results: list[EvaluationResult],
    summary: EvaluationSummary,
    source_health: SourceHealthSummary,
) -> str:
    """把评估结果渲染成人类可读的 Markdown 报告。"""

    # 没有结果时仍生成报告，告诉用户需要先运行一次日报。
    if not results:
        return f"""# Agent Evaluation Report

Generated at: {summary.generated_at}

No runs were found in the database. Run `python catch_ai.py --run-once` first.
"""

    # lines 使用列表逐行累加，最后 join，比超长 f-string 更容易维护。
    # 第一段是报告头部和项目级 KPI 概览，适合快速看近期 Agent 是否稳定。
    lines = [
        "# Agent Evaluation Report",
        "",
        f"Generated at: {summary.generated_at}",
        f"Evaluated runs: {summary.evaluated_runs}",
        f"Average score: {summary.average_score}/100",
        "",
        "## KPI Summary",
        "",
        "| KPI | Value |",
        "| --- | ---: |",
        f"| Run success rate | {summary.run_success_rate:.1f}% |",
        f"| Critic pass rate | {summary.critic_pass_rate:.1f}% |",
        f"| Hallucination proxy rate | {summary.hallucination_proxy_rate:.1f}% |",
        f"| Source success rate | {summary.source_success_rate:.1f}% |",
        f"| RAG hit rate | {summary.rag_hit_rate:.1f}% |",
        f"| Avg candidate event compression | {summary.average_event_compression_ratio:.2f} |",
        f"| Avg items per final event | {summary.average_items_per_event:.2f} |",
        f"| Avg duration | {summary.average_duration_ms:.0f} ms |",
        f"| P95 duration | {summary.p95_duration_ms:.0f} ms |",
        f"| Total LLM calls | {summary.total_llm_calls} |",
        f"| Total LLM tokens | {summary.total_llm_tokens} |",
        f"| Actual LLM cost | {format_actual_cost(summary.actual_llm_cost_total, summary.actual_llm_cost_currency)} |",
        f"| Actual cost available runs | {summary.actual_llm_cost_available_runs}/{summary.evaluated_runs} |",
        f"| Estimated LLM cost | ${summary.estimated_llm_cost_usd:.6f} |",
        f"| Avg LLM cost/run | ${summary.average_llm_cost_per_run_usd:.6f} |",
        f"| Revision accept rate | {summary.revision_accept_rate:.1f}% |",
        "",
        "## Source Health",
        "",
        f"- Sources tracked: {source_health.source_count}",
        f"- Currently successful sources: {source_health.successful_sources}",
        f"- Currently failing sources: {source_health.failing_sources}",
        f"- Lifetime source attempts: {source_health.total_success_count} success / {source_health.total_failure_count} failure",
        f"- Failing sources: {', '.join(source_health.failing_source_names) if source_health.failing_source_names else 'none'}",
        "",
        "## Run Summary",
        "",
        "| Run ID | Success | Score | Raw | Unique | Selected | Candidate Events | Compression | Final Events | Avg Items/Event | Source Errors | RAG | Critic | Unsupported Fact | LLM Calls | LLM Tokens | Actual Cost | Est. Cost | Trace ms | Slowest Span |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    # 每个 run 输出一行表格，方便横向比较“哪次运行变差了、差在哪里”。
    for result in results:
        lines.append(
            "| "
            f"{result.run_id} | {yes_no(result.run_success)} | {result.score} | "
            f"{result.raw_items} | {result.unique_items} | {result.selected_items} | "
            f"{result.candidate_event_count} | {result.candidate_event_compression_ratio:.2f} | "
            f"{result.event_count} | {result.avg_items_per_event} | "
            f"{result.source_error_count} | {yes_no(result.rag_hit)} | "
            f"{'PASS' if result.critic_passed else 'FAIL'} | "
            f"{yes_no(result.critic_has_unsupported_fact)} | "
            f"{result.llm_call_count} | {result.llm_total_tokens} | "
            f"{format_run_actual_cost(result)} | "
            f"${result.llm_estimated_cost_usd:.6f} | "
            f"{result.trace_duration_ms:.0f} | {format_slowest_span(result)} |"
        )

    # findings 展开每次运行的扣分原因；这里是排查问题时最应该先看的区域。
    lines.extend(["", "## Findings", ""])
    for result in results:
        lines.append(f"### {result.run_id} - {result.score}/100")
        for finding in result.findings:
            lines.append(f"- {finding}")
        lines.append("")

    # 最后一段解释这些指标应该如何使用，避免把离线代理指标误解成严格学术评测。
    lines.extend(
        [
            "## How To Use This",
            "",
            "- Low collection scores usually mean source configuration or network reliability needs work.",
            "- Weak event compression means the clustering or LLM event-merge prompt should be improved.",
            "- Hallucination proxy rate counts critic findings about unsupported or fabricated facts; it is not a full factuality benchmark.",
            "- Actual LLM cost comes from DeepSeek balance delta and is most reliable when the same API key is not used by another job during the run.",
            "- Estimated LLM cost is a fallback populated when token usage is present in trace and per-1M-token prices are configured.",
            "- Missing RAG hits means the long-term memory is not yet contributing useful context.",
            "- Critic failures should be reviewed before trusting the final report.",
        ]
    )

    return "\n".join(lines)


def yes_no(value: bool) -> str:
    """把布尔值格式化为 Markdown 表格中的 yes/no。"""

    # Markdown 表格中用简短英文，能保持列宽紧凑。
    return "yes" if value else "no"


def format_actual_cost(amount: float, currency: str) -> str:
    """格式化供应商余额差额成本。"""

    # 没有币种时说明实际成本不可用，用 n/a 比 0 更不容易误导。
    if not currency:
        return "n/a"
    return f"{currency} {amount:.6f}"


def format_run_actual_cost(result: EvaluationResult) -> str:
    """格式化单次运行的实际成本字段。"""

    # actual_cost_available 为 False 时，不展示数值，避免把默认 0 当成真实免费。
    if not result.llm_actual_cost_available:
        return "n/a"
    return format_actual_cost(result.llm_actual_cost, result.llm_actual_cost_currency)


def format_slowest_span(result: EvaluationResult) -> str:
    """格式化最慢 span，供 Markdown 表格展示。"""

    # 没有 trace 或 span 时返回空字符串，让表格保持简洁。
    if not result.slowest_span:
        return ""
    return f"{result.slowest_span} ({result.slowest_span_duration_ms:.0f} ms)"
