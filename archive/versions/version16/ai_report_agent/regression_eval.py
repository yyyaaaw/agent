"""核心 Agent 行为的确定性回归评估。

离线评估 evaluation.py 关注“真实运行是否健康”；
本模块关注“固定输入下，核心规则有没有被改坏”。

这些回归用例不会调用真实 LLM，也不会访问真实网络。
它们主要覆盖：
- 去重规则
- 评分排序
- critic 本地硬规则
- 修订完整性校验
- 事件词典抽取与事件合并判断
- 自动词典构建
"""

from __future__ import annotations

# json 用来读取回归用例和写出评估报告。
import json

# shutil 用于把默认词典 fixture 复制到临时目录。
import shutil

# tempfile 用于创建临时词典目录，避免测试写入真实业务词典。
import tempfile

# asdict 把 dataclass 转成可 JSON 序列化的 dict；dataclass 定义结果结构。
from dataclasses import asdict, dataclass

# date/datetime 用于本地 critic 日期校验和报告时间戳。
from datetime import date, datetime

# Path 用来处理用例文件、输出报告和临时词典路径。
from pathlib import Path

# Any 表示 JSON 中可能出现的任意类型。
from typing import Any

# Settings 提供 data/eval 输出目录；ROOT_DIR 用于定位默认 regression_cases.json。
from ai_report_agent.config import Settings, ROOT_DIR

# critic 相关函数用于检查报告硬规则、修订计划解析和修订完整性。
from ai_report_agent.critic import (
    ReportSection,
    local_critic_issues,
    parse_revision_plan_response,
    should_revise,
    split_report_sections,
    validate_revision_report,
    validate_section_revision,
)

# 去重模块是回归评估重点之一。
from ai_report_agent.deduplicator import deduplicate_items

# 事件模块提供词典抽取后的特征结构和两两合并判断。
from ai_report_agent.events import (
    EventFeatures,
    extract_actions,
    extract_entities,
    extract_keywords,
    extract_products,
    should_merge_pair,
)

# 默认用户偏好和 UserProfile 用于构造评分用例。
from ai_report_agent.profile import DEFAULT_PROFILE, UserProfile

# score_items 用于验证固定新闻输入下的排序是否符合预期。
from ai_report_agent.scorer import score_items

# NewsItem 是回归用例中新闻条目的标准结构。
from ai_report_agent.sources import NewsItem

# 词典读写工具用于构造临时词典目录和检查自动生成结果。
from ai_report_agent.taxonomy import DEFAULT_TAXONOMY_DIR, read_json

# update_event_taxonomy_from_items 用于测试自动发现词典候选。
from ai_report_agent.taxonomy_builder import update_event_taxonomy_from_items


# 默认回归用例文件。用户也可以传入其他 cases_path。
DEFAULT_CASES_PATH = ROOT_DIR / "evals" / "regression_cases.json"


@dataclass(frozen=True)
class RegressionCaseResult:
    """单个确定性回归用例的结果。"""

    case_id: str
    case_type: str
    description: str
    passed: bool
    expected: dict[str, Any]
    actual: dict[str, Any]
    details: str


@dataclass(frozen=True)
class RegressionSummary:
    """整批回归用例的汇总结果。"""

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
    """运行固定回归用例，并保存 Markdown/JSON 报告。"""

    # 读取 evals/regression_cases.json。
    payload = load_cases(cases_path)
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        raise RuntimeError(f"Invalid regression cases file: {cases_path}")

    # 逐个执行 case；非 dict 的异常配置会被跳过。
    results = [evaluate_case(case) for case in cases if isinstance(case, dict)]
    summary = build_summary(results, cases_path)

    # 输出到 data/eval，与普通离线评估报告放在一起。
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
    """读取回归用例 JSON 文件。"""

    if not cases_path.exists():
        raise RuntimeError(f"Regression cases file not found: {cases_path}")
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Regression cases root must be an object: {cases_path}")
    return payload


def evaluate_case(case: dict[str, Any]) -> RegressionCaseResult:
    """调度并执行单个回归用例。"""

    # 每个 case 都需要 id/type/description/expect；缺失时给兜底值。
    case_id = str(case.get("id", "unknown"))
    case_type = str(case.get("type", "unknown"))
    description = str(case.get("description", ""))
    expected = case.get("expect", {})
    if not isinstance(expected, dict):
        expected = {}

    try:
        # 先根据 type 运行具体评估逻辑，再把 actual 和 expect 比较。
        actual = evaluate_case_by_type(case_type, case)
        passed, details = compare_expected(case_type, expected, actual)
    except Exception as exc:
        # 回归评估不让单个 case 的异常中断整批评估，而是记录为失败。
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
    """根据 case_type 调用具体评估函数。"""

    # 这里显式分支比动态反射更可读，也更适合面试讲解。
    if case_type == "deduplication":
        return evaluate_deduplication_case(case)
    if case_type == "scoring_order":
        return evaluate_scoring_case(case)
    if case_type == "local_critic":
        return evaluate_local_critic_case(case)
    if case_type == "revision_validation":
        return evaluate_revision_validation_case(case)
    if case_type == "section_revision_validation":
        return evaluate_section_revision_validation_case(case)
    if case_type == "revision_plan":
        return evaluate_revision_plan_case(case)
    if case_type == "should_revise":
        return evaluate_should_revise_case(case)
    if case_type == "event_taxonomy_pair":
        return evaluate_event_taxonomy_pair_case(case)
    if case_type == "taxonomy_builder":
        return evaluate_taxonomy_builder_case(case)
    raise ValueError(f"Unsupported regression case type: {case_type}")


def evaluate_deduplication_case(case: dict[str, Any]) -> dict[str, Any]:
    """评估确定性去重行为。"""

    # read_case_items 会把 JSON fixture 转成 NewsItem。
    items = read_case_items(case)
    result = deduplicate_items([item for _, item in items])
    return {
        "unique_count": len(result.unique_items),
        "duplicate_count": result.duplicate_count,
        "unique_titles": [item.title for item in result.unique_items],
    }


def evaluate_scoring_case(case: dict[str, Any]) -> dict[str, Any]:
    """评估固定输入下的评分排序。"""

    items = read_case_items(case)
    profile = read_case_profile(case.get("profile"))
    scored = score_items([item for _, item in items], profile)

    # item_id_by_key 用来把 ScoredNewsItem 映射回 fixture 中的人类可读 id。
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
    """评估 critic 的本地硬规则检查。"""

    today = parse_case_date(str(case.get("today", date.today().isoformat())))
    report = str(case.get("report", ""))
    issues = local_critic_issues(report, today)
    return {
        "issue_count": len(issues),
        "issues": issues,
    }


def evaluate_revision_validation_case(case: dict[str, Any]) -> dict[str, Any]:
    """评估整篇报告修订完整性闸门。"""

    original_report = build_report_text(case.get("original_report"))
    revised_report = str(case.get("revised_report", ""))
    accepted, reason = validate_revision_report(original_report, revised_report)
    return {
        "accepted": accepted,
        "reason": reason,
        "original_chars": len(original_report),
        "revised_chars": len(revised_report),
    }


def evaluate_section_revision_validation_case(case: dict[str, Any]) -> dict[str, Any]:
    """评估单区块修订完整性闸门。"""

    section_title = str(case.get("section_title", "今日摘要"))
    original_section = ReportSection(
        title=section_title,
        content=str(case.get("original_section", "")),
        index=1,
    )
    revised_section = str(case.get("revised_section", ""))
    accepted, reason = validate_section_revision(original_section, revised_section)
    return {
        "accepted": accepted,
        "reason": reason,
        "revised_chars": len(revised_section),
    }


def evaluate_revision_plan_case(case: dict[str, Any]) -> dict[str, Any]:
    """评估结构化修订计划解析。"""

    report = build_report_text(case.get("report"))
    plan_response = str(case.get("plan_response", ""))
    plan = parse_revision_plan_response(plan_response, report)
    return {
        "plan_valid": plan.valid,
        "plan_reason": plan.rejected_reason,
        "section_titles": sorted(plan.section_instructions.keys()),
        "section_count": len(plan.section_instructions),
        "global_instruction_count": len(plan.global_instructions),
        "report_sections": [section.title for section in split_report_sections(report)],
    }


def evaluate_should_revise_case(case: dict[str, Any]) -> dict[str, Any]:
    """评估 critic PASS/FAIL 文本解析。"""

    critique = str(case.get("critique", ""))
    return {"should_revise": should_revise(critique)}


def evaluate_event_taxonomy_pair_case(case: dict[str, Any]) -> dict[str, Any]:
    """不调用 embedding API，评估词典抽取和两两事件合并判断。"""

    raw_items = case.get("items", [])
    if not isinstance(raw_items, list):
        raise ValueError("Case items must be a list")

    features_by_id: dict[str, EventFeatures] = {}
    item_actual: dict[str, dict[str, list[str]]] = {}
    for index, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            raise ValueError("Each event taxonomy item must be an object")
        item_id = str(raw_item.get("id", f"item_{index}"))
        text = str(raw_item.get("text", ""))

        # 用例中直接提供向量，避免测试依赖本地 BGE 模型或网络。
        embedding = read_float_list(raw_item.get("embedding"), [1.0, 0.0, 0.0])
        products = extract_products(text)
        entities = extract_entities(text) | products
        features = EventFeatures(
            text=text,
            embedding=embedding,
            entities=entities,
            products=products,
            actions=extract_actions(text),
            keywords=extract_keywords(text),
        )
        features_by_id[item_id] = features
        item_actual[item_id] = {
            "entities": sorted(features.entities),
            "products": sorted(features.products),
            "actions": sorted(features.actions),
            "keywords": sorted(features.keywords),
        }

    pair_actual: dict[str, dict[str, Any]] = {}
    raw_pairs = case.get("pairs", [])
    if not isinstance(raw_pairs, list):
        raise ValueError("Case pairs must be a list")
    for raw_pair in raw_pairs:
        if not isinstance(raw_pair, dict):
            raise ValueError("Each event taxonomy pair must be an object")
        left_id = str(raw_pair.get("left", ""))
        right_id = str(raw_pair.get("right", ""))
        if left_id not in features_by_id or right_id not in features_by_id:
            raise ValueError(f"Unknown pair ids: {left_id}, {right_id}")

        # should_merge_pair 是事件粗聚类的核心规则，这里直接验证它的布尔结果和原因。
        should_merge, reason = should_merge_pair(
            features_by_id[left_id],
            features_by_id[right_id],
            hybrid_threshold=float(raw_pair.get("hybrid_threshold", 0.58) or 0.58),
        )
        pair_actual[f"{left_id}|{right_id}"] = {
            "should_merge": should_merge,
            "reason": reason,
        }

    return {
        "items": item_actual,
        "pairs": pair_actual,
    }


def evaluate_taxonomy_builder_case(case: dict[str, Any]) -> dict[str, Any]:
    """在临时词典目录中评估自动词典生成。"""

    items = [item for _, item in read_case_items(case)]

    # 必须使用临时目录，避免回归测试污染真实 data/event_taxonomy。
    with tempfile.TemporaryDirectory() as tmp_dir:
        taxonomy_dir = Path(tmp_dir) / "event_taxonomy"
        prepare_temp_taxonomy_dir(taxonomy_dir)
        result = update_event_taxonomy_from_items(
            items,
            taxonomy_dir=taxonomy_dir,
            show_progress=False,
        )
        products = read_json(taxonomy_dir / "generated" / "products.generated.json")
        actions = read_json(taxonomy_dir / "generated" / "action_aliases.generated.json")
        review = read_json(taxonomy_dir / "review" / "taxonomy_candidates.json")

    return {
        "auto_entity_aliases": result.auto_entity_aliases,
        "auto_product_aliases": result.auto_product_aliases,
        "auto_action_aliases": result.auto_action_aliases,
        "review_candidates": result.review_candidates,
        "generated_products": products.get("products", {}),
        "generated_actions": actions.get("actions", {}),
        "review_aliases": [
            str(candidate.get("alias", ""))
            for candidate in review.get("candidates", [])
            if isinstance(candidate, dict)
        ],
    }


def compare_expected(
    case_type: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> tuple[bool, str]:
    """比较 expect 和 actual，返回是否通过以及解释文本。"""

    # checks 里每一项都是 (是否通过, 说明)。
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

        # above_ids 表示 top_id 的分数应高于这些 id。
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
    elif case_type == "section_revision_validation":
        checks.append(equal_check("accepted", expected, actual))
    elif case_type == "revision_plan":
        checks.append(equal_check("plan_valid", expected, actual))
        expected_sections = set(read_string_list(expected.get("section_titles"), []))
        actual_sections = set(read_string_list(actual.get("section_titles"), []))
        checks.append(
            (
                expected_sections <= actual_sections,
                f"section_titles contains {sorted(expected_sections)}",
            )
        )
    elif case_type == "should_revise":
        checks.append(equal_check("should_revise", expected, actual))
    elif case_type == "event_taxonomy_pair":
        checks.extend(event_taxonomy_checks(expected, actual))
    elif case_type == "taxonomy_builder":
        checks.extend(taxonomy_builder_checks(expected, actual))
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
    """比较 expected/actual 字典中的单个字段。"""

    expected_value = expected.get(key)
    actual_value = actual.get(key)
    return actual_value == expected_value, f"{key}: expected {expected_value!r}, got {actual_value!r}"


def read_case_items(case: dict[str, Any]) -> list[tuple[str, NewsItem]]:
    """从 case JSON 构造带 fixture id 的 NewsItem 列表。"""

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
    """从 JSON 对象构造一条 NewsItem。"""

    return NewsItem(
        source=str(raw_item.get("source", "")),
        category=str(raw_item.get("category", "")),
        title=str(raw_item.get("title", "")),
        link=str(raw_item.get("link", "")),
        published=str(raw_item.get("published", "")),
        summary=str(raw_item.get("summary", "")),
        region=str(raw_item.get("region", "global")),
        language=str(raw_item.get("language", "en")),
        source_type=str(raw_item.get("source_type", "company")),
        priority=int(raw_item.get("priority", 3) or 3),
        tags=read_string_list(raw_item.get("tags"), []),
    )


def read_case_profile(raw_profile: object) -> UserProfile:
    """从 case JSON 构造 UserProfile，缺失时使用默认偏好。"""

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
    """把 JSON 值安全读取为字符串列表。"""

    if not isinstance(value, list):
        return default
    return [str(item) for item in value]


def read_float_list(value: object, default: list[float]) -> list[float]:
    """把 JSON 值安全读取为浮点数列表。"""

    if not isinstance(value, list):
        return default
    floats: list[float] = []
    for item in value:
        try:
            floats.append(float(item))
        except (TypeError, ValueError):
            return default
    return floats or default


def event_taxonomy_checks(
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> list[tuple[bool, str]]:
    """比较事件词典抽取和合并判断结果。"""

    checks: list[tuple[bool, str]] = []
    actual_items = actual.get("items", {})
    if not isinstance(actual_items, dict):
        actual_items = {}
    for item_id, raw_expected_fields in read_mapping(expected.get("items")).items():
        actual_fields = actual_items.get(item_id, {})
        if not isinstance(actual_fields, dict):
            actual_fields = {}
        for field, expected_values in read_mapping(raw_expected_fields).items():
            actual_values = set(read_string_list(actual_fields.get(field), []))
            for expected_value in read_string_list(expected_values, []):
                checks.append(
                    (
                        expected_value in actual_values,
                        f"{item_id}.{field} contains {expected_value!r}",
                    )
                )

    actual_pairs = actual.get("pairs", {})
    if not isinstance(actual_pairs, dict):
        actual_pairs = {}
    for pair_key, expected_value in read_mapping(expected.get("pairs")).items():
        actual_pair = actual_pairs.get(pair_key, {})
        actual_merge = actual_pair.get("should_merge") if isinstance(actual_pair, dict) else None
        checks.append(
            (
                actual_merge == expected_value,
                f"{pair_key}.should_merge: expected {expected_value!r}, got {actual_merge!r}",
            )
        )
    return checks


def taxonomy_builder_checks(
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> list[tuple[bool, str]]:
    """比较自动词典生成结果和人工复核提示。"""

    checks: list[tuple[bool, str]] = []
    for key in ["auto_product_aliases", "auto_action_aliases"]:
        minimum = int(expected.get(f"min_{key}", 0) or 0)
        actual_value = int(actual.get(key, 0) or 0)
        checks.append((actual_value >= minimum, f"{key} {actual_value} >= {minimum}"))

    generated_products = actual.get("generated_products", {})
    if not isinstance(generated_products, dict):
        generated_products = {}
    for spec in read_mapping(expected.get("generated_products")).values():
        if not isinstance(spec, dict):
            continue
        canonical = str(spec.get("canonical", ""))
        alias = str(spec.get("alias", ""))
        aliases = set(read_string_list(generated_products.get(canonical), []))
        checks.append((alias in aliases, f"generated product {canonical} contains {alias}"))

    generated_actions = actual.get("generated_actions", {})
    if not isinstance(generated_actions, dict):
        generated_actions = {}
    for spec in read_mapping(expected.get("generated_actions")).values():
        if not isinstance(spec, dict):
            continue
        action_id = str(spec.get("action", ""))
        alias = str(spec.get("alias", ""))
        raw_action = generated_actions.get(action_id, {})
        aliases = []
        if isinstance(raw_action, dict):
            aliases = read_string_list(raw_action.get("aliases"), [])
        checks.append((alias in set(aliases), f"generated action {action_id} contains {alias}"))

    review_aliases = set(read_string_list(actual.get("review_aliases"), []))
    for alias in read_string_list(expected.get("review_aliases"), []):
        checks.append((alias in review_aliases, f"review aliases contain {alias}"))
    return checks


def read_mapping(value: object) -> dict[str, Any]:
    """把 JSON 值安全读取为字典。"""

    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def prepare_temp_taxonomy_dir(taxonomy_dir: Path) -> None:
    """为回归测试准备干净的临时词典目录。"""

    # 复制基础词典，保证测试环境和真实词典结构一致。
    taxonomy_dir.mkdir(parents=True, exist_ok=True)
    for filename in [
        "entities.json",
        "products.json",
        "action_aliases.json",
        "stopwords.json",
        "patterns.json",
    ]:
        shutil.copyfile(DEFAULT_TAXONOMY_DIR / filename, taxonomy_dir / filename)

    (taxonomy_dir / "generated").mkdir(parents=True, exist_ok=True)
    (taxonomy_dir / "overrides").mkdir(parents=True, exist_ok=True)

    # generated/overrides 写入空结构，让自动词典生成逻辑可以正常读写。
    (taxonomy_dir / "generated" / "entities.generated.json").write_text(
        json.dumps({"generated_at": "", "entities": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (taxonomy_dir / "generated" / "products.generated.json").write_text(
        json.dumps({"generated_at": "", "products": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (taxonomy_dir / "generated" / "action_aliases.generated.json").write_text(
        json.dumps({"generated_at": "", "actions": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (taxonomy_dir / "overrides" / "aliases.override.json").write_text(
        json.dumps(
            {"entities": {}, "products": {}, "actions": {}, "blocked_aliases": []},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def item_key(item: NewsItem) -> tuple[str, str, str, str, str, str]:
    """返回稳定 key，用于把评分结果映射回 fixture id。"""

    return (
        item.source,
        item.category,
        item.title,
        item.link,
        item.published,
        item.summary,
    )


def parse_case_date(value: str) -> date:
    """解析 YYYY-MM-DD 格式的测试日期。"""

    return datetime.strptime(value, "%Y-%m-%d").date()


def build_report_text(spec: object) -> str:
    """根据字符串或紧凑重复区块配置构造报告文本。"""

    # 简单字符串直接作为报告正文使用。
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
    """构建回归评估汇总。"""

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
    """把回归评估结果渲染成 Markdown。"""

    # 先输出总体结果，再输出每个 case 的明细。
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
        # 失败用例单独展开 expected/actual，方便定位回归原因。
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
    """转义 Markdown 表格中的竖线和换行。"""

    return value.replace("|", "\\|").replace("\n", " ")
