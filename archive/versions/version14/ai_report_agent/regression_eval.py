"""Deterministic regression evaluation for core agent behavior."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ai_report_agent.config import Settings, ROOT_DIR
from ai_report_agent.critic import local_critic_issues, should_revise, validate_revision_report
from ai_report_agent.deduplicator import deduplicate_items
from ai_report_agent.profile import DEFAULT_PROFILE, UserProfile
from ai_report_agent.scorer import score_items
from ai_report_agent.sources import NewsItem


DEFAULT_CASES_PATH = ROOT_DIR / "evals" / "regression_cases.json"


@dataclass(frozen=True)
class RegressionCaseResult:
    """One deterministic regression case result."""

    case_id: str
    case_type: str
    description: str
    passed: bool
    expected: dict[str, Any]
    actual: dict[str, Any]
    details: str


@dataclass(frozen=True)
class RegressionSummary:
    """Portfolio summary for regression cases."""

    generated_at: str
    cases_path: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float


def run_regression_evaluation(
    settings: Settings,
    cases_path: Path = DEFAULT_CASES_PATH,
) -> Path:
    """Run fixed regression cases and save Markdown/JSON reports."""

    payload = load_cases(cases_path)
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        raise RuntimeError(f"Invalid regression cases file: {cases_path}")

    results = [evaluate_case(case) for case in cases if isinstance(case, dict)]
    summary = build_summary(results, cases_path)

    output_dir = settings.raw_data_dir.parent / "eval"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    markdown_path = output_dir / f"regression_report_{timestamp}.md"
    json_path = output_dir / f"regression_report_{timestamp}.json"

    markdown_path.write_text(
        build_markdown(summary, results),
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps(
            {
                "summary": asdict(summary),
                "cases": [asdict(result) for result in results],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return markdown_path


def load_cases(cases_path: Path) -> dict[str, Any]:
    """Load regression case JSON."""

    if not cases_path.exists():
        raise RuntimeError(f"Regression cases file not found: {cases_path}")
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Regression cases root must be an object: {cases_path}")
    return payload


def evaluate_case(case: dict[str, Any]) -> RegressionCaseResult:
    """Dispatch one regression case."""

    case_id = str(case.get("id", "unknown"))
    case_type = str(case.get("type", "unknown"))
    description = str(case.get("description", ""))
    expected = case.get("expect", {})
    if not isinstance(expected, dict):
        expected = {}

    try:
        actual = evaluate_case_by_type(case_type, case)
        passed, details = compare_expected(case_type, expected, actual)
    except Exception as exc:
        actual = {"error": str(exc)}
        passed = False
        details = f"Case raised {type(exc).__name__}: {exc}"

    return RegressionCaseResult(
        case_id=case_id,
        case_type=case_type,
        description=description,
        passed=passed,
        expected=expected,
        actual=actual,
        details=details,
    )


def evaluate_case_by_type(case_type: str, case: dict[str, Any]) -> dict[str, Any]:
    """Run the concrete evaluator for a supported case type."""

    if case_type == "deduplication":
        return evaluate_deduplication_case(case)
    if case_type == "scoring_order":
        return evaluate_scoring_case(case)
    if case_type == "local_critic":
        return evaluate_local_critic_case(case)
    if case_type == "revision_validation":
        return evaluate_revision_validation_case(case)
    if case_type == "should_revise":
        return evaluate_should_revise_case(case)
    raise ValueError(f"Unsupported regression case type: {case_type}")


def evaluate_deduplication_case(case: dict[str, Any]) -> dict[str, Any]:
    """Evaluate deterministic deduplication behavior."""

    items = read_case_items(case)
    result = deduplicate_items([item for _, item in items])
    return {
        "unique_count": len(result.unique_items),
        "duplicate_count": result.duplicate_count,
        "unique_titles": [item.title for item in result.unique_items],
    }


def evaluate_scoring_case(case: dict[str, Any]) -> dict[str, Any]:
    """Evaluate deterministic scoring order behavior."""

    items = read_case_items(case)
    profile = read_case_profile(case.get("profile"))
    scored = score_items([item for _, item in items], profile)
    item_id_by_key = {item_key(item): item_id for item_id, item in items}
    ordered_ids = [item_id_by_key[item_key(entry.item)] for entry in scored]
    scores = {
        item_id_by_key[item_key(entry.item)]: entry.score
        for entry in scored
    }
    return {
        "ordered_ids": ordered_ids,
        "top_id": ordered_ids[0] if ordered_ids else "",
        "scores": scores,
    }


def evaluate_local_critic_case(case: dict[str, Any]) -> dict[str, Any]:
    """Evaluate local critic hard-rule checks."""

    today = parse_case_date(str(case.get("today", date.today().isoformat())))
    report = str(case.get("report", ""))
    issues = local_critic_issues(report, today)
    return {
        "issue_count": len(issues),
        "issues": issues,
    }


def evaluate_revision_validation_case(case: dict[str, Any]) -> dict[str, Any]:
    """Evaluate revision completeness gate."""

    original_report = build_report_text(case.get("original_report"))
    revised_report = str(case.get("revised_report", ""))
    accepted, reason = validate_revision_report(original_report, revised_report)
    return {
        "accepted": accepted,
        "reason": reason,
        "original_chars": len(original_report),
        "revised_chars": len(revised_report),
    }


def evaluate_should_revise_case(case: dict[str, Any]) -> dict[str, Any]:
    """Evaluate critic decision parsing."""

    critique = str(case.get("critique", ""))
    return {"should_revise": should_revise(critique)}


def compare_expected(
    case_type: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> tuple[bool, str]:
    """Compare expected values with actual case output."""

    checks: list[tuple[bool, str]] = []

    if case_type == "deduplication":
        checks.append(equal_check("unique_count", expected, actual))
        checks.append(equal_check("duplicate_count", expected, actual))
    elif case_type == "scoring_order":
        checks.append(equal_check("top_id", expected, actual))
        top_id = str(expected.get("top_id", ""))
        scores = actual.get("scores", {})
        if not isinstance(scores, dict):
            scores = {}
        for loser_id in expected.get("above_ids", []):
            winner_score = int(scores.get(top_id, 0) or 0)
            loser_score = int(scores.get(str(loser_id), 0) or 0)
            checks.append(
                (
                    winner_score > loser_score,
                    f"{top_id} score {winner_score} > {loser_id} score {loser_score}",
                )
            )
    elif case_type == "local_critic":
        min_issue_count = int(expected.get("min_issue_count", 0) or 0)
        issue_count = int(actual.get("issue_count", 0) or 0)
        checks.append((issue_count >= min_issue_count, f"issue_count {issue_count} >= {min_issue_count}"))
    elif case_type == "revision_validation":
        checks.append(equal_check("accepted", expected, actual))
    elif case_type == "should_revise":
        checks.append(equal_check("should_revise", expected, actual))
    else:
        checks.append((False, f"Unsupported case type: {case_type}"))

    failed = [message for passed, message in checks if not passed]
    if failed:
        return False, "; ".join(failed)
    return True, "; ".join(message for _, message in checks)


def equal_check(
    key: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> tuple[bool, str]:
    """Compare one key in expected and actual dictionaries."""

    expected_value = expected.get(key)
    actual_value = actual.get(key)
    return actual_value == expected_value, f"{key}: expected {expected_value!r}, got {actual_value!r}"


def read_case_items(case: dict[str, Any]) -> list[tuple[str, NewsItem]]:
    """Build NewsItem objects from case JSON."""

    raw_items = case.get("items", [])
    if not isinstance(raw_items, list):
        raise ValueError("Case items must be a list")

    items: list[tuple[str, NewsItem]] = []
    for index, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            raise ValueError("Each case item must be an object")
        item_id = str(raw_item.get("id", f"item_{index}"))
        items.append((item_id, read_news_item(raw_item)))
    return items


def read_news_item(raw_item: dict[str, Any]) -> NewsItem:
    """Build one NewsItem from JSON."""

    return NewsItem(
        source=str(raw_item.get("source", "")),
        category=str(raw_item.get("category", "")),
        title=str(raw_item.get("title", "")),
        link=str(raw_item.get("link", "")),
        published=str(raw_item.get("published", "")),
        summary=str(raw_item.get("summary", "")),
    )


def read_case_profile(raw_profile: object) -> UserProfile:
    """Build UserProfile from case JSON, falling back to defaults."""

    if not isinstance(raw_profile, dict):
        return DEFAULT_PROFILE
    return UserProfile(
        interests=read_string_list(raw_profile.get("interests"), DEFAULT_PROFILE.interests),
        avoid=read_string_list(raw_profile.get("avoid"), DEFAULT_PROFILE.avoid),
        preferred_categories=read_string_list(
            raw_profile.get("preferred_categories"),
            DEFAULT_PROFILE.preferred_categories,
        ),
        report_style=str(raw_profile.get("report_style", DEFAULT_PROFILE.report_style)),
        top_questions=read_string_list(raw_profile.get("top_questions"), DEFAULT_PROFILE.top_questions),
    )


def read_string_list(value: object, default: list[str]) -> list[str]:
    """Read a JSON value as a string list."""

    if not isinstance(value, list):
        return default
    return [str(item) for item in value]


def item_key(item: NewsItem) -> tuple[str, str, str, str, str, str]:
    """Return a stable key for mapping scored items back to fixture IDs."""

    return (
        item.source,
        item.category,
        item.title,
        item.link,
        item.published,
        item.summary,
    )


def parse_case_date(value: str) -> date:
    """Parse YYYY-MM-DD test fixture date."""

    return datetime.strptime(value, "%Y-%m-%d").date()


def build_report_text(spec: object) -> str:
    """Build report text from either a string or a compact repeated-section spec."""

    if isinstance(spec, str):
        return spec
    if not isinstance(spec, dict):
        return ""
    header = str(spec.get("header", ""))
    repeat_section = str(spec.get("repeat_section", ""))
    repeat_count = int(spec.get("repeat_count", 1) or 1)
    footer = str(spec.get("footer", ""))
    return header + repeat_section * repeat_count + footer


def build_summary(results: list[RegressionCaseResult], cases_path: Path) -> RegressionSummary:
    """Build regression summary."""

    passed_cases = sum(1 for result in results if result.passed)
    total_cases = len(results)
    failed_cases = total_cases - passed_cases
    pass_rate = round(passed_cases / total_cases * 100, 1) if total_cases else 0.0
    return RegressionSummary(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        cases_path=str(cases_path),
        total_cases=total_cases,
        passed_cases=passed_cases,
        failed_cases=failed_cases,
        pass_rate=pass_rate,
    )


def build_markdown(
    summary: RegressionSummary,
    results: list[RegressionCaseResult],
) -> str:
    """Render regression results as Markdown."""

    lines = [
        "# Agent Regression Eval Report",
        "",
        f"Generated at: {summary.generated_at}",
        f"Cases file: `{summary.cases_path}`",
        "",
        "## Summary",
        "",
        "| KPI | Value |",
        "| --- | ---: |",
        f"| Total cases | {summary.total_cases} |",
        f"| Passed cases | {summary.passed_cases} |",
        f"| Failed cases | {summary.failed_cases} |",
        f"| Pass rate | {summary.pass_rate:.1f}% |",
        "",
        "## Case Results",
        "",
        "| Case | Type | Result | Details |",
        "| --- | --- | --- | --- |",
    ]

    for result in results:
        lines.append(
            f"| `{result.case_id}` | {result.case_type} | "
            f"{'PASS' if result.passed else 'FAIL'} | {escape_table_text(result.details)} |"
        )

    failed_results = [result for result in results if not result.passed]
    if failed_results:
        lines.extend(["", "## Failed Cases", ""])
        for result in failed_results:
            lines.extend(
                [
                    f"### {result.case_id}",
                    "",
                    f"- Type: `{result.case_type}`",
                    f"- Expected: `{json.dumps(result.expected, ensure_ascii=False)}`",
                    f"- Actual: `{json.dumps(result.actual, ensure_ascii=False)}`",
                    f"- Details: {result.details}",
                    "",
                ]
            )

    lines.extend(
        [
            "",
            "## How To Use This",
            "",
            "- Run this before and after changing scoring, deduplication, critic, revision, or related prompts.",
            "- These cases do not replace real daily-report evaluation; they catch regressions on stable inputs.",
            "- Add a new case when a production run reveals a bug that should never come back.",
        ]
    )
    return "\n".join(lines)


def escape_table_text(value: str) -> str:
    """Escape Markdown table separators."""

    return value.replace("|", "\\|").replace("\n", " ")
