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

import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from ai_report_agent.config import Settings
from ai_report_agent.database import connect, initialize_database


@dataclass(frozen=True)
class EvaluationResult:
    """Structured evaluation result for one run."""

    run_id: str
    score: int
    run_success: bool
    trace_status: str
    report_path: str
    raw_items: int
    unique_items: int
    selected_items: int
    duplicate_count: int
    candidate_event_count: int
    candidate_event_compression_ratio: float
    event_count: int
    avg_items_per_event: float
    source_error_count: int
    rag_hit: bool
    critic_passed: bool
    critic_has_unsupported_fact: bool
    revision_triggered: bool
    revision_accepted: bool | None
    feedback_count: int
    trace_duration_ms: float
    slowest_span: str
    slowest_span_duration_ms: float
    findings: list[str]


@dataclass(frozen=True)
class SourceHealthSummary:
    """Aggregated source reliability metrics."""

    source_count: int
    successful_sources: int
    failing_sources: int
    total_success_count: int
    total_failure_count: int
    source_success_rate: float
    failing_source_names: list[str]


@dataclass(frozen=True)
class EvaluationSummary:
    """Portfolio-level KPIs across evaluated runs."""

    generated_at: str
    evaluated_runs: int
    average_score: float
    run_success_rate: float
    critic_pass_rate: float
    hallucination_proxy_rate: float
    source_success_rate: float
    rag_hit_rate: float
    average_event_compression_ratio: float
    average_items_per_event: float
    average_duration_ms: float
    p95_duration_ms: float
    revision_accept_rate: float


def run_evaluation(settings: Settings, limit: int = 5) -> Path:
    """Evaluate recent agent runs and save a Markdown report.

    This is the entry point used by `python catch_ai.py --eval`.
    """

    initialize_database(settings.database_path)
    run_ids = latest_run_ids(settings.database_path, limit)

    results = [
        evaluate_single_run(settings, run_id)
        for run_id in run_ids
    ]
    source_health = read_source_health_summary(settings.raw_data_dir.parent / "source_health.json")
    summary = build_evaluation_summary(results, source_health)

    output_dir = settings.raw_data_dir.parent / "eval"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    markdown_path = output_dir / f"eval_report_{timestamp}.md"
    json_path = output_dir / f"eval_report_{timestamp}.json"

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
    """Read recent run IDs from SQLite, newest first."""

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
    return [str(row["run_id"]) for row in rows]


def evaluate_single_run(settings: Settings, run_id: str) -> EvaluationResult:
    """Compute explainable health metrics for one run."""

    run = fetch_run(settings.database_path, run_id)
    event_count = count_rows(settings.database_path, "events", run_id)
    source_error_count = count_rows(settings.database_path, "source_errors", run_id)
    feedback_count = count_feedback_for_run(settings.database_path, run_id)

    raw_items = int(run["raw_item_count"])
    unique_items = int(run["unique_item_count"])
    selected_items = int(run["selected_item_count"])
    duplicate_count = int(run["duplicate_count"])
    decisions = json.loads(run["decisions_json"] or "[]")
    critic_result = str(run["critic_result"] or "")
    report_path = str(run["report_path"] or "")

    trace_payload = read_trace_payload(settings.raw_data_dir.parent / "traces", run_id)
    trace_status = str(trace_payload.get("status", "missing")) if trace_payload else "missing"
    trace_duration_ms = float(trace_payload.get("duration_ms", 0.0)) if trace_payload else 0.0
    candidate_event_count = int(trace_span_metric(trace_payload, "cluster_scored_items", "candidate_events", 0))
    candidate_event_compression_ratio = float(
        trace_span_metric(trace_payload, "cluster_scored_items", "candidate_event_compression_ratio", 0.0)
    )
    if not candidate_event_compression_ratio and selected_items and candidate_event_count:
        candidate_event_compression_ratio = round(selected_items / candidate_event_count, 2)

    avg_items_per_event = round(selected_items / event_count, 2) if event_count else 0.0
    rag_hit = any("RAG" in str(decision) for decision in decisions)
    critic_passed = is_critic_passed(critic_result)
    critic_has_unsupported_fact = has_unsupported_fact_issue(critic_result)
    revision_triggered = trace_has_span(trace_payload, "revise_report")
    revision_accepted = trace_optional_bool_metric(trace_payload, "revise_report", "revision_accepted")
    slowest_span, slowest_span_duration_ms = slowest_trace_span(trace_payload)
    run_success = trace_status == "ok" and bool(report_path)

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
        slowest_span=slowest_span,
        slowest_span_duration_ms=slowest_span_duration_ms,
        findings=findings,
    )


def fetch_run(database_path: Path, run_id: str) -> sqlite3.Row:
    """Fetch one run row.  Raise a clear error if it is missing."""

    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()

    if row is None:
        raise RuntimeError(f"Run not found: {run_id}")
    return row


def count_rows(database_path: Path, table: str, run_id: str) -> int:
    """Count rows for a run in a known table."""

    if table not in {"events", "source_errors"}:
        raise ValueError(f"Unsupported table: {table}")

    with connect(database_path) as connection:
        row = connection.execute(
            f"SELECT COUNT(*) AS count FROM {table} WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    return int(row["count"])


def count_feedback_for_run(database_path: Path, run_id: str) -> int:
    """Count event-level feedback attached to events from this run."""

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
    """Read trace JSON if a trace file exists."""

    trace_path = trace_dir / f"trace_{run_id}.json"
    if not trace_path.exists():
        return {}

    return json.loads(trace_path.read_text(encoding="utf-8"))


def trace_spans(trace_payload: dict) -> list[dict]:
    """Return trace spans from a trace payload."""

    spans = trace_payload.get("spans", []) if trace_payload else []
    return [span for span in spans if isinstance(span, dict)]


def trace_has_span(trace_payload: dict, span_name: str) -> bool:
    """Return whether a named span exists."""

    return any(span.get("name") == span_name for span in trace_spans(trace_payload))


def trace_span_metric(
    trace_payload: dict,
    span_name: str,
    metric_name: str,
    default: int | float | str | bool,
) -> int | float | str | bool:
    """Read one metric from a named span."""

    for span in trace_spans(trace_payload):
        if span.get("name") != span_name:
            continue
        metrics = span.get("metrics", {})
        if isinstance(metrics, dict):
            return metrics.get(metric_name, default)
    return default


def trace_optional_bool_metric(trace_payload: dict, span_name: str, metric_name: str) -> bool | None:
    """Read an optional boolean span metric."""

    value = trace_span_metric(trace_payload, span_name, metric_name, None)
    if value is None:
        return None
    return bool(value)


def slowest_trace_span(trace_payload: dict) -> tuple[str, float]:
    """Return the slowest span name and duration."""

    spans = trace_spans(trace_payload)
    if not spans:
        return "", 0.0

    slowest = max(spans, key=lambda span: float(span.get("duration_ms", 0.0) or 0.0))
    return str(slowest.get("name", "")), float(slowest.get("duration_ms", 0.0) or 0.0)


def is_critic_passed(critic_result: str) -> bool:
    """Return whether critic text indicates a pass."""

    normalized = critic_result.strip().upper()
    return bool(normalized) and "FAIL" not in normalized


def has_unsupported_fact_issue(critic_result: str) -> bool:
    """Detect critic findings that are a useful proxy for hallucination risk."""

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
    """Read source health JSON and compute aggregate reliability metrics."""

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
    """Compute portfolio-level KPIs from run results."""

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
            revision_accept_rate=0.0,
        )

    revision_runs = [result for result in results if result.revision_triggered]
    accepted_revisions = [
        result
        for result in revision_runs
        if result.revision_accepted is True
    ]

    return EvaluationSummary(
        generated_at=generated_at,
        evaluated_runs=len(results),
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
        revision_accept_rate=percentage(len(accepted_revisions), len(revision_runs)),
    )


def count_true(values) -> int:
    """Count truthy values from an iterable."""

    return sum(1 for value in values if value)


def average(values: list[int | float]) -> float:
    """Return the average of numeric values."""

    return sum(values) / len(values) if values else 0.0


def percentile(values: list[int | float], percentile_value: int) -> float:
    """Return nearest-rank percentile for a numeric list."""

    if not values:
        return 0.0

    sorted_values = sorted(float(value) for value in values)
    index = max(0, min(len(sorted_values) - 1, math.ceil(percentile_value / 100 * len(sorted_values)) - 1))
    return sorted_values[index]


def percentage(numerator: int, denominator: int) -> float:
    """Return percentage rounded to one decimal place."""

    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 1)


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
    """Convert metrics into a simple 0-100 health score."""

    score = 100
    findings: list[str] = []

    if not run_success:
        score -= 25
        findings.append("Run did not complete cleanly or no report path was recorded.")

    if raw_items <= 0:
        score -= 35
        findings.append("Collection produced no raw items.")
    elif raw_items < 10:
        score -= 10
        findings.append("Collection volume is low; the report may miss important events.")

    if unique_items <= 0:
        score -= 25
        findings.append("No unique items survived deduplication.")

    if selected_items <= 0:
        score -= 25
        findings.append("No items were selected for model analysis.")
    elif raw_items and selected_items / raw_items > 0.9:
        score -= 6
        findings.append("Selection is broad; the scorer may not be filtering enough noise.")

    if duplicate_count == 0 and raw_items >= 20:
        score -= 4
        findings.append("No duplicates were detected in a large batch; dedup rules may be too weak.")

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
        findings.append("Event clustering is compressing related news into multi-item events.")

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
    """Render evaluation results as a human-readable Markdown report."""

    if not results:
        return f"""# Agent Evaluation Report

Generated at: {summary.generated_at}

No runs were found in the database. Run `python catch_ai.py --run-once` first.
"""

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
        "| Run ID | Success | Score | Raw | Unique | Selected | Candidate Events | Compression | Final Events | Avg Items/Event | Source Errors | RAG | Critic | Unsupported Fact | Trace ms | Slowest Span |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | ---: | --- |",
    ]

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
            f"{result.trace_duration_ms:.0f} | {format_slowest_span(result)} |"
        )

    lines.extend(["", "## Findings", ""])
    for result in results:
        lines.append(f"### {result.run_id} - {result.score}/100")
        for finding in result.findings:
            lines.append(f"- {finding}")
        lines.append("")

    lines.extend(
        [
            "## How To Use This",
            "",
            "- Low collection scores usually mean source configuration or network reliability needs work.",
            "- Weak event compression means the clustering or LLM event-merge prompt should be improved.",
            "- Hallucination proxy rate counts critic findings about unsupported or fabricated facts; it is not a full factuality benchmark.",
            "- Missing RAG hits means the long-term memory is not yet contributing useful context.",
            "- Critic failures should be reviewed before trusting the final report.",
        ]
    )

    return "\n".join(lines)


def yes_no(value: bool) -> str:
    """Format booleans for Markdown tables."""

    return "yes" if value else "no"


def format_slowest_span(result: EvaluationResult) -> str:
    """Format slowest span for Markdown tables."""

    if not result.slowest_span:
        return ""
    return f"{result.slowest_span} ({result.slowest_span_duration_ms:.0f} ms)"
