"""外置事件词典加载与归一化。

事件聚合需要持续补充公司、产品和动作别名。如果这些规则都写在
``events.py`` 里，后续扩展国内来源和综合新闻站点时会越来越难维护。
本模块把词典放到 ``data/event_taxonomy``，并提供轻量匹配能力。
"""

from __future__ import annotations

# json 用来读取 data/event_taxonomy 下的词典文件。
import json

# re 用于别名归一化、中文字符判断和边界匹配。
import re

# dataclass 用于定义词典在内存中的结构。
from dataclasses import dataclass

# lru_cache 缓存词典，避免每次抽取实体都重复读 JSON。
from functools import lru_cache

# Path 用于定位项目根目录和词典目录。
from pathlib import Path

# Any 用于描述 JSON 文件中不固定的值类型。
from typing import Any


# 项目根目录。
ROOT_DIR = Path(__file__).resolve().parents[1]

# 默认事件词典目录。基础词典、generated、overrides 都在这里。
DEFAULT_TAXONOMY_DIR = ROOT_DIR / "data" / "event_taxonomy"


@dataclass(frozen=True)
class EventTaxonomy:
    """事件聚合词典的内存表示。"""

    entity_aliases: dict[str, str]
    product_aliases: dict[str, str]
    action_aliases: dict[str, str]
    action_labels: dict[str, str]
    action_similarity_matrix: dict[str, dict[str, float]]
    weak_actions: set[str]
    hub_entities: set[str]
    stop_words: set[str]
    product_markers: set[str]

    def match_entities(self, text: str) -> set[str]:
        """返回文本里命中的标准公司/组织实体。"""

        return match_aliases(text, self.entity_aliases)

    def match_products(self, text: str) -> set[str]:
        """返回文本里命中的标准产品/模型实体。"""

        return match_aliases(text, self.product_aliases)

    def match_actions(self, text: str) -> set[str]:
        """返回文本里命中的标准动作类型。"""

        return match_aliases(text, self.action_aliases)

    def action_label(self, action_id: str) -> str:
        """返回动作类型的可读标签。"""

        return self.action_labels.get(action_id, action_id)

    def action_similarity(self, left_actions: set[str], right_actions: set[str]) -> float:
        """计算两组动作的最大相似度。"""

        if not left_actions or not right_actions:
            return 0.0

        best_score = 0.0
        for left in left_actions:
            for right in right_actions:
                if left == right:
                    best_score = max(best_score, 1.0)
                    continue
                best_score = max(best_score, self._action_pair_similarity(left, right))
        return best_score

    def similar_action_pairs(
        self,
        left_actions: set[str],
        right_actions: set[str],
        threshold: float = 0.65,
    ) -> list[tuple[str, str, float]]:
        """返回达到相似度阈值的动作对。"""

        pairs: list[tuple[str, str, float]] = []
        for left in left_actions:
            for right in right_actions:
                score = 1.0 if left == right else self._action_pair_similarity(left, right)
                if score >= threshold:
                    pairs.append((left, right, score))
        return sorted(pairs, key=lambda item: item[2], reverse=True)

    def _action_pair_similarity(self, left: str, right: str) -> float:
        """从对称矩阵里读取动作相似度。"""

        if left in self.action_similarity_matrix:
            value = self.action_similarity_matrix[left].get(right)
            if value is not None:
                return value
        if right in self.action_similarity_matrix:
            value = self.action_similarity_matrix[right].get(left)
            if value is not None:
                return value
        return 0.0


def normalize_alias(value: str) -> str:
    """把别名标准化成用于匹配的形式。"""

    return re.sub(r"\s+", " ", value.strip().lower())


def match_aliases(text: str, aliases: dict[str, str]) -> set[str]:
    """用别名表匹配文本，返回标准名称集合。"""

    # 文本先统一小写和空白，保证 alias 匹配更稳定。
    normalized = normalize_alias(text or "")
    if not normalized:
        return set()

    matches: set[str] = set()

    # 长别名优先匹配，避免短别名先命中导致解释不清。
    for alias, canonical in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if alias and alias_in_text(alias, normalized):
            matches.add(canonical)
    return matches


def alias_in_text(alias: str, normalized_text: str) -> bool:
    """判断一个别名是否出现在已标准化文本中。"""

    # 中文没有英文单词边界概念，直接 substring 匹配。
    if contains_cjk(alias):
        return alias in normalized_text

    # 英文别名用负向边界，避免 "ai" 命中 "paid" 这类误匹配。
    pattern = re.escape(alias).replace(r"\ ", r"\s+")
    return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", normalized_text) is not None


def contains_cjk(value: str) -> bool:
    """判断字符串是否包含中文字符。"""

    return re.search(r"[\u4e00-\u9fff]", value) is not None


@lru_cache(maxsize=1)
def get_event_taxonomy(taxonomy_dir: Path = DEFAULT_TAXONOMY_DIR) -> EventTaxonomy:
    """加载并缓存事件词典。"""

    # 基础词典：人工维护的主要规则。
    entity_payload = read_json(taxonomy_dir / "entities.json")
    product_payload = read_json(taxonomy_dir / "products.json")
    action_payload = read_json(taxonomy_dir / "action_aliases.json")
    stopword_payload = read_json(taxonomy_dir / "stopwords.json")
    pattern_payload = read_json(taxonomy_dir / "patterns.json")

    # generated 词典：taxonomy_builder 自动发现的高置信别名。
    generated_entity_payload = read_json(taxonomy_dir / "generated" / "entities.generated.json")
    generated_product_payload = read_json(taxonomy_dir / "generated" / "products.generated.json")
    generated_action_payload = read_json(taxonomy_dir / "generated" / "action_aliases.generated.json")

    # overrides：人工确认的新增别名、修正和 blocked_aliases。
    override_payload = read_json(taxonomy_dir / "overrides" / "aliases.override.json")

    # 动作需要保留 label、aliases 和 similarity，所以先合并完整 spec。
    action_specs = merge_action_specs(
        read_mapping(action_payload.get("actions")),
        read_mapping(generated_action_payload.get("actions")),
        read_mapping(override_payload.get("actions")),
    )
    action_aliases = read_action_aliases(action_specs)

    # label 用于把 action_id 展示成人类可读中文。
    action_labels = {
        action_id: str(spec.get("label", action_id))
        for action_id, spec in action_specs.items()
        if isinstance(spec, dict)
    }

    # blocked_aliases 用于人工屏蔽误命中，优先级最高。
    blocked_aliases = {normalize_alias(value) for value in read_string_set(override_payload.get("blocked_aliases"))}

    # entity/product 别名按基础 -> generated -> override 顺序合并，后者可以覆盖前者。
    entity_aliases = merge_alias_maps(
        read_named_aliases(entity_payload.get("entities")),
        read_named_aliases(generated_entity_payload.get("entities")),
        read_named_aliases(override_payload.get("entities")),
    )
    product_aliases = merge_alias_maps(
        read_named_aliases(product_payload.get("products")),
        read_named_aliases(generated_product_payload.get("products")),
        read_named_aliases(override_payload.get("products")),
    )

    # 把人工屏蔽的 alias 从所有别名表中删除。
    action_aliases = {
        alias: canonical
        for alias, canonical in action_aliases.items()
        if alias not in blocked_aliases
    }
    entity_aliases = {
        alias: canonical
        for alias, canonical in entity_aliases.items()
        if alias not in blocked_aliases
    }
    product_aliases = {
        alias: canonical
        for alias, canonical in product_aliases.items()
        if alias not in blocked_aliases
    }

    # 构造不可变 EventTaxonomy 对象，供 events.py 和 taxonomy_builder.py 使用。
    return EventTaxonomy(
        entity_aliases=entity_aliases,
        product_aliases=product_aliases,
        action_aliases=action_aliases,
        action_labels=action_labels,
        action_similarity_matrix=read_similarity_matrix(action_payload.get("similarity")),
        weak_actions=read_string_set(action_payload.get("weak_actions")),
        hub_entities=read_string_set(pattern_payload.get("hub_entities")),
        stop_words={normalize_alias(value) for value in read_string_set(stopword_payload.get("stop_words"))},
        product_markers={normalize_alias(value) for value in read_string_set(pattern_payload.get("product_markers"))},
    )


def clear_event_taxonomy_cache() -> None:
    """清空词典缓存，让本次自动生成的新词典立即生效。"""

    get_event_taxonomy.cache_clear()


def read_json(path: Path) -> dict[str, Any]:
    """读取 JSON 文件；不存在时返回空对象，避免词典缺失导致主流程失败。"""

    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return payload


def read_mapping(value: object) -> dict[str, Any]:
    """安全读取 JSON 对象。"""

    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def read_named_aliases(value: object) -> dict[str, str]:
    """读取 ``标准名 -> 别名列表`` 结构。"""

    aliases: dict[str, str] = {}
    for canonical, raw_aliases in read_mapping(value).items():
        for alias in [canonical, *read_string_list(raw_aliases)]:
            normalized = normalize_alias(alias)
            if is_usable_alias(normalized):
                aliases[normalized] = canonical
    return aliases


def merge_alias_maps(*alias_maps: dict[str, str]) -> dict[str, str]:
    """按顺序合并别名表，后面的文件可以覆盖前面的映射。"""

    merged: dict[str, str] = {}
    for alias_map in alias_maps:
        merged.update(alias_map)
    return merged


def merge_action_specs(*spec_maps: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """合并动作定义，保留基础标签并追加 generated/override 别名。"""

    merged: dict[str, dict[str, Any]] = {}
    for spec_map in spec_maps:
        for action_id, raw_spec in spec_map.items():
            # 每个 action 至少有 label 和 aliases 两个字段。
            current = merged.setdefault(action_id, {"label": action_id, "aliases": []})
            if isinstance(raw_spec, list):
                # 兼容旧格式：{"launch": ["发布", "推出"]}。
                current["aliases"] = unique_strings([*read_string_list(current.get("aliases")), *read_string_list(raw_spec)])
                continue
            if not isinstance(raw_spec, dict):
                continue
            label = raw_spec.get("label")
            if label:
                current["label"] = str(label)
            # 新格式：{"launch": {"label": "发布", "aliases": [...]}}。
            current["aliases"] = unique_strings(
                [
                    *read_string_list(current.get("aliases")),
                    *read_string_list(raw_spec.get("aliases")),
                ]
            )
    return merged


def read_action_aliases(action_specs: dict[str, Any]) -> dict[str, str]:
    """读取动作别名，返回 ``别名 -> 标准动作 id``。"""

    aliases: dict[str, str] = {}
    for action_id, spec in action_specs.items():
        if not isinstance(spec, dict):
            continue
        raw_aliases = spec.get("aliases")
        for alias in [action_id, *read_string_list(raw_aliases)]:
            normalized = normalize_alias(alias)
            if is_usable_alias(normalized):
                aliases[normalized] = action_id
    return aliases


def read_similarity_matrix(value: object) -> dict[str, dict[str, float]]:
    """读取动作相似度矩阵。"""

    matrix: dict[str, dict[str, float]] = {}
    for left, raw_targets in read_mapping(value).items():
        targets: dict[str, float] = {}
        for right, raw_score in read_mapping(raw_targets).items():
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                continue
            # 相似度强制限制在 0-1，避免配置错误放大聚类权重。
            targets[right] = max(0.0, min(score, 1.0))
        matrix[left] = targets
    return matrix


def read_string_list(value: object) -> list[str]:
    """读取字符串列表。"""

    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def read_string_set(value: object) -> set[str]:
    """读取字符串集合。"""

    return set(read_string_list(value))


def unique_strings(values: list[str]) -> list[str]:
    """字符串去重并保留顺序。"""

    return list(dict.fromkeys(value for value in values if str(value).strip()))


def is_usable_alias(value: str) -> bool:
    """过滤过短或过泛的别名，降低误命中。"""

    compact = re.sub(r"[\s._-]+", "", value)
    if len(compact) < 2:
        return False
    return compact not in {"ai", "llm", "api", "gpu"}
