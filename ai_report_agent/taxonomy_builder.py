"""自动发现和维护事件词典。

主词典仍保持可解释的小核心；本模块负责从 RSS 标题和摘要中发现高置信候选，
自动写入 generated 词典。低置信或有歧义的候选会写入 review 文件，并在终端
提示人工修正。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_report_agent.sources import NewsItem
from ai_report_agent.taxonomy import (
    DEFAULT_TAXONOMY_DIR,
    clear_event_taxonomy_cache,
    get_event_taxonomy,
    normalize_alias,
    read_json,
)


PRODUCT_PREFIX_CANONICAL = {
    "gpt": "GPT",
    "claude": "Claude",
    "gemini": "Gemini",
    "grok": "Grok",
    "llama": "Llama",
    "mistral": "Mistral",
    "qwen": "Qwen",
    "ernie": "ERNIE",
    "glm": "GLM",
    "hunyuan": "Hunyuan",
    "deepseek": "DeepSeek",
    "baichuan": "Baichuan",
    "minicpm": "MiniCPM",
    "yi": "Yi",
    "step": "Step",
    "doubao": "Doubao",
    "kimi": "Kimi",
    "spark": "Spark",
    "pangu": "Pangu",
}

ACTION_ALIAS_HINTS = {
    "launch": [
        "开启内测",
        "启动内测",
        "开放内测",
        "开放公测",
        "灰度开放",
        "开放体验",
        "首曝",
        "首度亮相",
    ],
    "upgrade": ["焕新", "更新至", "升级至", "能力增强", "能力提升"],
    "open_source": ["开放权重", "开放模型权重", "公开权重"],
    "pricing": ["降价", "涨价", "免费开放", "付费版", "订阅制"],
    "partnership": ["携手", "牵手", "结盟", "战略牵手"],
    "integration": ["打入", "接入到", "集成到", "嵌入到", "落地到"],
    "funding": ["完成融资", "获得融资", "获投", "加注"],
    "acquisition": ["完成收购", "并入"],
    "regulation": ["获批", "通过备案", "完成备案", "纳入监管"],
    "safety_security": ["修复漏洞", "封堵", "拦截攻击", "安全评估"],
    "application_case": ["试点落地", "规模化落地", "商用落地"],
    "infrastructure": ["量产", "投产", "扩建算力", "训练集群"],
}

UNCLEAR_ACTION_TERMS = [
    "布局",
    "押注",
    "探索",
    "试水",
    "回应",
    "否认",
    "计划",
    "考虑",
    "加速",
    "转向",
]

GENERIC_CANDIDATES = {
    "人工智能",
    "企业智能",
    "智能体",
    "大模型",
    "中国公司",
    "科技公司",
    "云服务",
    "研究院",
    "实验室",
}


@dataclass
class TaxonomyCandidate:
    """一个词典候选项。"""

    kind: str
    canonical: str
    alias: str
    confidence: float
    status: str
    reason: str
    count: int = 0
    sources: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TaxonomyUpdateResult:
    """一次自动词典更新的摘要。"""

    auto_entity_aliases: int
    auto_product_aliases: int
    auto_action_aliases: int
    review_candidates: int
    generated_paths: list[str]
    review_path: str
    report_path: str


def update_event_taxonomy_from_items(
    items: list[NewsItem],
    taxonomy_dir: Path = DEFAULT_TAXONOMY_DIR,
    show_progress: bool = True,
    max_review_items: int = 10,
) -> TaxonomyUpdateResult:
    """从新闻标题/摘要自动发现词典候选并更新 generated 词典。"""

    taxonomy = get_event_taxonomy(taxonomy_dir)
    buckets = collect_candidate_buckets(items, taxonomy)
    auto_candidates, review_candidates = split_candidates(buckets)

    generated_paths = write_generated_taxonomy(auto_candidates, taxonomy_dir)
    review_path = write_review_candidates(review_candidates, taxonomy_dir)
    report_path = write_review_report(auto_candidates, review_candidates, taxonomy_dir)

    clear_event_taxonomy_cache()

    result = TaxonomyUpdateResult(
        auto_entity_aliases=count_candidates(auto_candidates, "entity"),
        auto_product_aliases=count_candidates(auto_candidates, "product"),
        auto_action_aliases=count_candidates(auto_candidates, "action"),
        review_candidates=len(review_candidates),
        generated_paths=[str(path) for path in generated_paths],
        review_path=str(review_path),
        report_path=str(report_path),
    )

    if show_progress:
        print_taxonomy_update_summary(result, review_candidates[:max_review_items])

    return result


def collect_candidate_buckets(items: list[NewsItem], taxonomy) -> list[TaxonomyCandidate]:
    """收集候选并把重复命中合并为桶。"""

    buckets: dict[tuple[str, str, str], TaxonomyCandidate] = {}

    for item in items:
        text = f"{item.title} {item.summary}"
        example = f"{item.source}: {item.title}"
        for canonical, alias, confidence, reason in discover_product_candidates(text, taxonomy):
            add_candidate(buckets, "product", canonical, alias, confidence, reason, item.source, example)
        for canonical, alias, confidence, reason in discover_entity_candidates(text, taxonomy):
            add_candidate(buckets, "entity", canonical, alias, confidence, reason, item.source, example)
        for canonical, alias, confidence, reason in discover_action_candidates(text, taxonomy):
            add_candidate(buckets, "action", canonical, alias, confidence, reason, item.source, example)
        for alias in discover_unclear_action_terms(text, taxonomy):
            add_candidate(
                buckets,
                "action_review",
                "",
                alias,
                0.45,
                "动作含义依赖上下文，需要人工决定是否映射到已有动作类别",
                item.source,
                example,
            )

    return sorted(
        buckets.values(),
        key=lambda candidate: (candidate.status != "auto", -candidate.confidence, -candidate.count, candidate.alias),
    )


def add_candidate(
    buckets: dict[tuple[str, str, str], TaxonomyCandidate],
    kind: str,
    canonical: str,
    alias: str,
    confidence: float,
    reason: str,
    source: str,
    example: str,
) -> None:
    """把一次命中加入候选桶。"""

    cleaned_alias = clean_candidate(alias)
    cleaned_canonical = clean_candidate(canonical or alias)
    if not cleaned_alias or is_generic_candidate(cleaned_alias):
        return

    key = (kind, cleaned_canonical, cleaned_alias)
    bucket = buckets.get(key)
    if bucket is None:
        bucket = TaxonomyCandidate(
            kind=kind,
            canonical=cleaned_canonical,
            alias=cleaned_alias,
            confidence=confidence,
            status="review",
            reason=reason,
        )
        buckets[key] = bucket

    bucket.count += 1
    bucket.confidence = max(bucket.confidence, confidence)
    if source not in bucket.sources:
        bucket.sources.append(source)
    if example not in bucket.examples and len(bucket.examples) < 3:
        bucket.examples.append(example)


def discover_product_candidates(text: str, taxonomy) -> list[tuple[str, str, float, str]]:
    """发现产品/模型候选。"""

    candidates: list[tuple[str, str, float, str]] = []
    existing_aliases = taxonomy.product_aliases
    product_values = set(existing_aliases.values())

    model_pattern = re.compile(
        r"\b(?:GPT|Claude|Gemini|Grok|Llama|Mistral|Qwen|ERNIE|GLM|Hunyuan|DeepSeek|Baichuan|MiniCPM|Yi|Step|Doubao|Kimi|Spark|Pangu)[-\s]?[A-Za-z0-9.]+(?:[-.][A-Za-z0-9]+)*\b"
    )
    for match in model_pattern.findall(text):
        alias = clean_candidate(match)
        if known_alias(alias, existing_aliases):
            continue
        canonical = infer_product_canonical(alias, product_values)
        candidates.append((canonical, alias, 0.92, "明确模型/产品编号，自动加入产品别名"))

    chinese_pattern = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]{2,16}(?:大模型|模型|Agent|智能体|助手)")
    for match in chinese_pattern.findall(text):
        alias = clean_candidate(match)
        if known_alias(alias, existing_aliases):
            continue
        candidates.append((alias, alias, 0.62, "中文产品短语，需要重复出现后自动沉淀"))

    return candidates


def discover_entity_candidates(text: str, taxonomy) -> list[tuple[str, str, float, str]]:
    """发现公司/机构候选。"""

    candidates: list[tuple[str, str, float, str]] = []
    existing_aliases = taxonomy.entity_aliases

    chinese_pattern = re.compile(r"[\u4e00-\u9fff]{2,12}(?:科技|智能|集团|实验室|研究院|云|公司)")
    for match in chinese_pattern.findall(text):
        alias = clean_candidate(match)
        if known_alias(alias, existing_aliases):
            continue
        candidates.append((alias, alias, 0.72, "中文组织后缀命中，需要重复出现后自动沉淀"))

    english_pattern = re.compile(
        r"\b(?:[A-Z][A-Za-z0-9&.-]+)(?:\s+[A-Z][A-Za-z0-9&.-]+){0,2}\s+(?:AI|Labs|Lab|Research|Cloud|Technologies|Systems)\b"
    )
    for match in english_pattern.findall(text):
        alias = clean_candidate(match)
        if known_alias(alias, existing_aliases):
            continue
        candidates.append((alias, alias, 0.74, "英文组织形态命中，需要重复出现后自动沉淀"))

    return candidates


def discover_action_candidates(text: str, taxonomy) -> list[tuple[str, str, float, str]]:
    """发现可以自动映射到既有动作类别的别名。"""

    candidates: list[tuple[str, str, float, str]] = []
    for action_id, aliases in ACTION_ALIAS_HINTS.items():
        for alias in aliases:
            if alias in text and not known_alias(alias, taxonomy.action_aliases):
                candidates.append((action_id, alias, 0.9, "动作别名命中内置高置信规则"))
    return candidates


def discover_unclear_action_terms(text: str, taxonomy) -> list[str]:
    """发现需要人工确认的含糊动作词。"""

    if not taxonomy.match_entities(text) and not taxonomy.match_products(text):
        return []
    return [
        term
        for term in UNCLEAR_ACTION_TERMS
        if term in text and not known_alias(term, taxonomy.action_aliases)
    ]


def split_candidates(
    candidates: list[TaxonomyCandidate],
) -> tuple[list[TaxonomyCandidate], list[TaxonomyCandidate]]:
    """把候选分为自动写入和人工复核。"""

    auto: list[TaxonomyCandidate] = []
    review: list[TaxonomyCandidate] = []

    for candidate in candidates:
        if should_auto_accept(candidate):
            candidate.status = "auto"
            auto.append(candidate)
        else:
            candidate.status = "review"
            review.append(candidate)

    return auto, sorted(review, key=lambda item: (-item.count, -item.confidence, item.alias))


def should_auto_accept(candidate: TaxonomyCandidate) -> bool:
    """判断候选是否可以自动进入 generated 词典。"""

    if candidate.kind == "action":
        return candidate.confidence >= 0.88
    if candidate.kind == "product":
        return candidate.confidence >= 0.88 or candidate.count >= 2
    if candidate.kind == "entity":
        return candidate.count >= 2 and candidate.confidence >= 0.7
    return False


def write_generated_taxonomy(candidates: list[TaxonomyCandidate], taxonomy_dir: Path) -> list[Path]:
    """把自动候选写入 generated 词典。"""

    generated_dir = taxonomy_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    entity_path = generated_dir / "entities.generated.json"
    product_path = generated_dir / "products.generated.json"
    action_path = generated_dir / "action_aliases.generated.json"

    entity_payload = merge_generated_aliases(read_json(entity_path), candidates, "entity", "entities")
    product_payload = merge_generated_aliases(read_json(product_path), candidates, "product", "products")
    action_payload = merge_generated_actions(read_json(action_path), candidates)

    write_json(entity_path, entity_payload)
    write_json(product_path, product_payload)
    write_json(action_path, action_payload)

    return [entity_path, product_path, action_path]


def merge_generated_aliases(
    payload: dict[str, Any],
    candidates: list[TaxonomyCandidate],
    kind: str,
    root_key: str,
) -> dict[str, Any]:
    """合并实体/产品 generated 词典。"""

    values = payload.get(root_key)
    if not isinstance(values, dict):
        values = {}
    merged: dict[str, list[str]] = {
        str(canonical): read_string_list(raw_aliases)
        for canonical, raw_aliases in values.items()
    }

    for candidate in candidates:
        if candidate.kind != kind:
            continue
        aliases = merged.setdefault(candidate.canonical, [])
        if candidate.alias not in aliases and candidate.alias != candidate.canonical:
            aliases.append(candidate.alias)
        elif candidate.alias == candidate.canonical and not aliases:
            aliases.append(candidate.alias)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        root_key: {canonical: sorted(set(aliases)) for canonical, aliases in sorted(merged.items())},
    }


def merge_generated_actions(payload: dict[str, Any], candidates: list[TaxonomyCandidate]) -> dict[str, Any]:
    """合并动作 generated 词典。"""

    raw_actions = payload.get("actions")
    if not isinstance(raw_actions, dict):
        raw_actions = {}
    actions: dict[str, dict[str, list[str]]] = {}
    for action_id, raw_spec in raw_actions.items():
        aliases: list[str] = []
        if isinstance(raw_spec, dict):
            aliases = read_string_list(raw_spec.get("aliases"))
        elif isinstance(raw_spec, list):
            aliases = read_string_list(raw_spec)
        actions[str(action_id)] = {"aliases": aliases}

    for candidate in candidates:
        if candidate.kind != "action":
            continue
        aliases = actions.setdefault(candidate.canonical, {"aliases": []})["aliases"]
        if candidate.alias not in aliases:
            aliases.append(candidate.alias)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "actions": {
            action_id: {"aliases": sorted(set(spec["aliases"]))}
            for action_id, spec in sorted(actions.items())
        },
    }


def write_review_candidates(candidates: list[TaxonomyCandidate], taxonomy_dir: Path) -> Path:
    """保存需要人工复核的候选 JSON。"""

    review_dir = taxonomy_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    review_path = review_dir / "taxonomy_candidates.json"
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "manual_hint": "确认后可把别名写入 data/event_taxonomy/overrides/aliases.override.json；误命中可写入 blocked_aliases。",
        "candidates": [asdict(candidate) for candidate in candidates],
    }
    write_json(review_path, payload)
    return review_path


def write_review_report(
    auto_candidates: list[TaxonomyCandidate],
    review_candidates: list[TaxonomyCandidate],
    taxonomy_dir: Path,
) -> Path:
    """保存 Markdown 版词典更新报告。"""

    review_dir = taxonomy_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    report_path = review_dir / "taxonomy_report.md"
    lines = [
        "# Taxonomy Auto Update Report",
        "",
        f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Auto Accepted",
        "",
        *format_candidate_lines(auto_candidates[:30]),
        "",
        "## Needs Manual Review",
        "",
        *format_candidate_lines(review_candidates[:50]),
        "",
        "## How To Review",
        "",
        "- Add confirmed aliases to `data/event_taxonomy/overrides/aliases.override.json`.",
        "- Add false positives to `blocked_aliases` in the same file.",
        "- Keep action categories small; prefer adding aliases to existing actions.",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def format_candidate_lines(candidates: list[TaxonomyCandidate]) -> list[str]:
    """把候选格式化为 Markdown 列表。"""

    if not candidates:
        return ["- None"]
    return [
        (
            f"- `{candidate.kind}` {candidate.alias} -> {candidate.canonical} "
            f"(count={candidate.count}, confidence={candidate.confidence:.2f}) "
            f"{candidate.reason}"
        )
        for candidate in candidates
    ]


def print_taxonomy_update_summary(
    result: TaxonomyUpdateResult,
    review_candidates: list[TaxonomyCandidate],
) -> None:
    """在终端打印自动词典更新摘要和人工修正提示。"""

    print(
        "Taxonomy auto-update: "
        f"{result.auto_entity_aliases} entity aliases, "
        f"{result.auto_product_aliases} product aliases, "
        f"{result.auto_action_aliases} action aliases generated."
    )
    if not result.review_candidates:
        return

    print(
        "Taxonomy review needed: "
        f"{result.review_candidates} candidates. Review file: {result.review_path}"
    )
    for candidate in review_candidates:
        example = candidate.examples[0] if candidate.examples else ""
        print(
            f"  - {candidate.kind}: {candidate.alias} -> {candidate.canonical or '未定'} "
            f"(count={candidate.count}, confidence={candidate.confidence:.2f}) {example}"
        )


def count_candidates(candidates: list[TaxonomyCandidate], kind: str) -> int:
    """统计某类候选数量。"""

    return sum(1 for candidate in candidates if candidate.kind == kind)


def infer_product_canonical(alias: str, known_products: set[str]) -> str:
    """根据模型名前缀推断产品家族。"""

    lowered = normalize_alias(alias).replace(" ", "-")
    for prefix, canonical in PRODUCT_PREFIX_CANONICAL.items():
        if lowered.startswith(prefix) and canonical in known_products:
            return canonical
    return alias


def known_alias(alias: str, alias_map: dict[str, str]) -> bool:
    """判断候选别名是否已经存在。"""

    return normalize_alias(alias) in alias_map


def clean_candidate(value: str) -> str:
    """清理候选词显示形式。"""

    return re.sub(r"\s+", " ", (value or "").strip(" \t\r\n，。、“”‘’：:;；()（）[]【】")).strip()


def is_generic_candidate(value: str) -> bool:
    """过滤明显泛化的候选词。"""

    normalized = normalize_alias(value)
    compact = re.sub(r"[\s._-]+", "", normalized)
    return compact in {normalize_alias(item).replace(" ", "") for item in GENERIC_CANDIDATES}


def read_string_list(value: object) -> list[str]:
    """读取字符串列表。"""

    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """写入 JSON 文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
