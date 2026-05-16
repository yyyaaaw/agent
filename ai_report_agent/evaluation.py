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
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ai_report_agent.config import Settings
from ai_report_agent.database import connect, initialize_database


@dataclass(frozen=True)
class EvaluationResult:
    """Structured evaluation result for one run."""

    run_id: str
    score: int
    raw_items: int
    unique_items: int
    selected_items: int
    duplicate_count: int
    event_count: int
    avg_items_per_event: float
    source_error_count: int
    rag_hit: bool
    critic_passed: bool
    feedback_count: int
    trace_duration_ms: float
    findings: list[str]


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

    output_dir = settings.raw_data_dir.parent / "eval"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    markdown_path = output_dir / f"eval_report_{timestamp}.md"
    json_path = output_dir / f"eval_report_{timestamp}.json"

    markdown_path.write_text(
        build_evaluation_markdown(results),
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps([result.__dict__ for result in results], ensure_ascii=False, indent=2),
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

    avg_items_per_event = round(selected_items / event_count, 2) if event_count else 0.0
    rag_hit = any("RAG" in str(decision) for decision in decisions)
    critic_passed = "FAIL" not in critic_result.upper()
    trace_duration_ms = read_trace_duration(settings.raw_data_dir.parent / "traces", run_id)

    score, findings = score_run(
        raw_items=raw_items,
        unique_items=unique_items,
        selected_items=selected_items,
        duplicate_count=duplicate_count,
        event_count=event_count,
        avg_items_per_event=avg_items_per_event,
        source_error_count=source_error_count,
        rag_hit=rag_hit,
        critic_passed=critic_passed,
    )

    return EvaluationResult(
        run_id=run_id,
        score=score,
        raw_items=raw_items,
        unique_items=unique_items,
        selected_items=selected_items,
        duplicate_count=duplicate_count,
        event_count=event_count,
        avg_items_per_event=avg_items_per_event,
        source_error_count=source_error_count,
        rag_hit=rag_hit,
        critic_passed=critic_passed,
        feedback_count=feedback_count,
        trace_duration_ms=trace_duration_ms,
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


def read_trace_duration(trace_dir: Path, run_id: str) -> float:
    """Read total trace duration if a trace file exists."""

    trace_path = trace_dir / f"trace_{run_id}.json"
    if not trace_path.exists():
        return 0.0

    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    return float(payload.get("duration_ms", 0.0))


def score_run(
    *,
    raw_items: int,
    unique_items: int,
    selected_items: int,
    duplicate_count: int,
    event_count: int,
    avg_items_per_event: float,
    source_error_count: int,
    rag_hit: bool,
    critic_passed: bool,
) -> tuple[int, list[str]]:
    """Convert metrics into a simple 0-100 health score."""

    score = 100
    findings: list[str] = []

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


def build_evaluation_markdown(results: list[EvaluationResult]) -> str:
    """Render evaluation results as a human-readable Markdown report."""

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not results:
        return f"""# Agent Evaluation Report

Generated at: {now}

No runs were found in the database. Run `python catch_ai.py --run-once` first.
"""

    average_score = round(sum(result.score for result in results) / len(results), 1)

    lines = [
        "# Agent Evaluation Report",
        "",
        f"Generated at: {now}",
        f"Evaluated runs: {len(results)}",
        f"Average score: {average_score}/100",
        "",
        "## Run Summary",
        "",
        "| Run ID | Score | Raw | Unique | Selected | Events | Avg Items/Event | Source Errors | RAG | Critic | Trace ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |",
    ]

    for result in results:
        lines.append(
            "| "
            f"{result.run_id} | {result.score} | {result.raw_items} | {result.unique_items} | "
            f"{result.selected_items} | {result.event_count} | {result.avg_items_per_event} | "
            f"{result.source_error_count} | {yes_no(result.rag_hit)} | "
            f"{'PASS' if result.critic_passed else 'FAIL'} | {result.trace_duration_ms:.0f} |"
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
            "- Missing RAG hits means the long-term memory is not yet contributing useful context.",
            "- Critic failures should be reviewed before trusting the final report.",
        ]
    )

    return "\n".join(lines)


def yes_no(value: bool) -> str:
    """Format booleans for Markdown tables."""

    return "yes" if value else "no"
