"""事件级聚类模块。

Version 13 专门修复“一个新闻几乎就是一个事件”的问题。

旧版的粗聚类只依赖一个条件：新闻 embedding 和已有事件 embedding 的余弦相似度
是否超过 0.78。这个策略太保守，尤其在科技新闻场景里会失败：

1. 官方公告、媒体报道、价格分析、风险评论可能都在讲同一个产品，但文本角度不同。
2. 标题很短时，embedding 很容易被“企业案例”“趋势评论”等泛化表达拉开。
3. 贪心聚类只把当前新闻塞进已有簇，一旦早期没有匹配成功，后续很难重新连接。
4. LLM 二次合并拿到的候选已经太碎，模型只能看到一堆单条事件，合并空间很小。

新版改成“高召回、可解释”的混合聚类：

- embedding 相似度仍然保留，但不再是唯一依据。
- 从标题和摘要里抽取实体，例如公司名、产品名、模型名。
- 抽取动作类型，例如发布、开源、融资、定价、安全、监管、研究。
- 计算标题关键词重叠，捕捉同一事件的共同事实词。
- 用并查集做成对合并，让 A-B、B-C 这种链式相关能形成同一个候选事件。

注意：这里的目标是生成“候选事件”，后续仍会交给 LLM 做二次整合和命名。
因此 Version 13 的粗聚类比旧版更重视召回，但仍保留防误合并规则，避免把
同一家公司完全不同的新闻硬并成一个事件。
"""

from __future__ import annotations

# math 用于处理向量和分数时的基础数值计算。
import math

# re 用于抽取英文实体、模型名、关键词。
import re

# dataclass 用于定义事件对象和聚类特征对象。
from dataclasses import dataclass

# cosine_similarity / embed_text 用于计算新闻和事件的语义向量。
from ai_report_agent.embeddings import cosine_similarity, embed_text

# ScoredNewsItem 是带评分和评分理由的新闻对象。
from ai_report_agent.scorer import ScoredNewsItem

# NewsItem 是 RSS 采集阶段产出的标准新闻结构。
from ai_report_agent.sources import NewsItem

# 事件词典负责把公司、产品和动作别名归一化为稳定 ID。
from ai_report_agent.taxonomy import get_event_taxonomy


# 常见 AI 公司、实验室、产品和模型实体。
# 这不是为了做完美 NER，而是给事件聚类提供“同一主体”的强信号。
# 例如 OpenAI 官方发布和 The Decoder 的价格报道，如果都提到 GPT-5.5，
# 即使 embedding 角度不同，也应该进入同一个候选事件。
KNOWN_ENTITY_PATTERNS = {
    "openai": "OpenAI",
    "chatgpt": "ChatGPT",
    "gpt-5.5": "GPT-5.5",
    "gpt-5": "GPT-5",
    "gpt-4o": "GPT-4o",
    "codex": "Codex",
    "anthropic": "Anthropic",
    "claude": "Claude",
    "claude mythos": "Claude Mythos",
    "google deepmind": "Google DeepMind",
    "deepmind": "Google DeepMind",
    "gemini": "Gemini",
    "microsoft": "Microsoft",
    "copilot": "Copilot",
    "nvidia": "NVIDIA",
    "rubin": "NVIDIA Rubin",
    "nemotron": "Nemotron",
    "meta": "Meta",
    "llama": "Llama",
    "mistral": "Mistral",
    "perplexity": "Perplexity",
    "xai": "xAI",
    "grok": "Grok",
    "bytedance": "ByteDance",
    "tiktok": "TikTok",
    "apple": "Apple",
    "amazon": "Amazon",
    "aws": "AWS",
    "salesforce": "Salesforce",
    "adobe": "Adobe",
    "palantir": "Palantir",
    "palo alto networks": "Palo Alto Networks",
    "metr": "METR",
}


# 动作类型词典。每个键是标准化后的动作类别，值是可能出现在标题/摘要中的关键词。
# 聚类时，“同一实体 + 同一动作类型”是比纯 embedding 更可靠的事件信号。
ACTION_KEYWORDS = {
    "发布": [
        "launch", "launches", "launched", "release", "releases", "released",
        "announce", "announces", "announced", "introduce", "introduces",
        "roll out", "rolls out", "unveil", "unveils", "发布", "推出", "上线",
        "公布", "宣布",
    ],
    "开源": ["open source", "open-source", "opensource", "开源"],
    "定价": ["price", "pricing", "cost", "costs", "expensive", "cheaper", "定价", "价格", "成本"],
    "安全": [
        "safe", "safety", "security", "cyber", "hack", "attack", "risk",
        "blackmail", "安全", "攻击", "风险", "网络安全",
    ],
    "融资交易": [
        "funding", "raises", "raise", "investment", "invest", "deal",
        "acquisition", "acquire", "equity", "融资", "投资", "收购", "交易",
    ],
    "合作": ["partner", "partners", "partnership", "collaborate", "合作", "联盟"],
    "监管伦理": [
        "regulation", "regulator", "policy", "ethics", "ethical", "religious",
        "copyright", "lawsuit", "监管", "政策", "伦理", "诉讼", "版权",
    ],
    "研究评测": [
        "research", "researchers", "benchmark", "evaluation", "measure",
        "paper", "study", "研究", "论文", "评测", "基准",
    ],
    "应用案例": [
        "enterprise", "customer", "customers", "case", "workflow", "productivity",
        "service", "agent", "agents", "应用", "案例", "企业", "客服", "工作流",
    ],
}

LEGACY_ACTION_IDS = {
    "发布": "launch",
    "开源": "open_source",
    "定价": "pricing",
    "安全": "safety_security",
    "融资交易": "funding",
    "合作": "partnership",
    "监管伦理": "regulation",
    "研究评测": "research_evaluation",
    "应用案例": "application_case",
}


# 这些动作类别本身比较宽泛。
# 例如“应用案例”可以覆盖客服、农业、办公、创意生产等很多完全不同的新闻。
# 因此它们不能单独和“同一公司”一起作为强合并依据。
WEAK_ACTIONS = {"应用案例", "发布"}


# 高频公司名容易变成“聚类黑洞”。
# 例如 NVIDIA 每天可能同时有芯片、研究、投资、机器人、自动驾驶等多条新闻。
# 如果只因为它们都提到 NVIDIA 就合并，会把不同事件吸成一个巨大事件。
HUB_ENTITIES = {
    "OpenAI",
    "Microsoft",
    "NVIDIA",
    "Google DeepMind",
    "Anthropic",
    "Meta",
    "Amazon",
    "AWS",
    "Apple",
    "ByteDance",
}


# 一些高频但区分度很弱的词。标题关键词重叠时会过滤它们，
# 否则所有 AI 新闻都会因为 ai/model/agent 这类词看起来“相似”。
STOP_WORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with",
    "from", "by", "as", "at", "is", "are", "be", "its", "their", "this",
    "that", "how", "what", "why", "can", "now", "new", "ai", "model",
    "models", "agent", "agents", "tool", "tools", "future", "using", "uses",
    "blog", "first", "most", "help", "build", "building", "systems", "capable",
    "complex", "launched", "released", "published", "about", "use", "open",
    "shows", "show", "source", "sources",
}


@dataclass
class NewsEvent:
    """聚类后的事件对象。"""

    # 事件 ID，只在本次运行内使用。
    event_id: str

    # 事件标题。LLM 二次合并后可能会重新生成标题。
    title: str

    # 事件摘要材料，用于报告 prompt 和数据库保存。
    summary: str

    # 事件包含的评分新闻。
    scored_items: list[ScoredNewsItem]

    # 事件向量，用于事件级 RAG。
    embedding: list[float]

    # 事件平均分。
    average_score: float

    # 事件最高分。
    max_score: int

    # 事件来源列表。
    sources: list[str]

    # 事件类别列表。
    categories: list[str]

    # 代表链接，通常使用最高分新闻的链接。
    representative_link: str


@dataclass(frozen=True)
class EventFeatures:
    """一条新闻用于事件聚类的可解释特征。"""

    # 新闻原始文本，包含标题、摘要、分类、来源。
    text: str

    # 语义向量。
    embedding: list[float]

    # 抽取到的公司、产品、模型等实体。
    entities: set[str]

    # 抽取到的产品和模型实体。单独保留是因为它们比公司名更能限定事件边界。
    products: set[str]

    # 抽取到的动作类型，例如发布、定价、安全。
    actions: set[str]

    # 标题和摘要中的区分性关键词。
    keywords: set[str]


class UnionFind:
    """并查集，用于把两两相似的新闻合并成连通事件簇。

    旧版是贪心聚类：每条新闻只和已有簇比较一次。新版先做成对判断，
    再用并查集合并，这样 A 和 B 相似、B 和 C 相似时，A/B/C 会自然形成一组。
    """

    def __init__(self, size: int) -> None:
        # parent[i] 表示 i 的父节点；初始化时每个节点都是自己的父节点。
        self.parent = list(range(size))

        # rank 用来减少树高度，让 find 更快。
        self.rank = [0] * size

    def find(self, value: int) -> int:
        """查找 value 所在集合的代表节点。"""
        if self.parent[value] != value:
            # 路径压缩：查找时顺手把节点直接挂到根节点下，后续查询会更快。
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        """把 left 和 right 所在集合合并。"""
        left_root = self.find(left)
        right_root = self.find(right)

        if left_root == right_root:
            return

        # 按 rank 合并：优先把较矮的树挂到较高的树下面，避免树退化成链表。
        if self.rank[left_root] < self.rank[right_root]:
            self.parent[left_root] = right_root
        elif self.rank[left_root] > self.rank[right_root]:
            self.parent[right_root] = left_root
        else:
            self.parent[right_root] = left_root
            self.rank[left_root] += 1


def item_event_text(item: NewsItem) -> str:
    """把一条新闻整理成用于事件聚类的文本。"""
    return f"{item.title} {item.summary} {item.category} {item.source}"


def normalize_text(text: str) -> str:
    """把文本转成适合规则匹配的小写形式。"""
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def taxonomy_stop_words() -> set[str]:
    """返回代码内置和外置词典合并后的停用词。"""

    # 外置词典方便后续补充领域词，不需要每次都改这份聚类代码。
    return STOP_WORDS | get_event_taxonomy().stop_words


def taxonomy_weak_actions() -> set[str]:
    """返回标准化后的弱动作集合。"""

    # 旧版中文动作名会先映射成新词典使用的动作 ID，再和外置配置合并。
    legacy_weak_actions = {LEGACY_ACTION_IDS.get(action, action) for action in WEAK_ACTIONS}
    return legacy_weak_actions | get_event_taxonomy().weak_actions


def taxonomy_hub_entities() -> set[str]:
    """返回容易产生误合并的高频主体集合。"""

    return HUB_ENTITIES | get_event_taxonomy().hub_entities


def format_action_names(actions: set[str] | list[str]) -> list[str]:
    """把动作 ID 转成用于解释原因的可读名称。"""

    taxonomy = get_event_taxonomy()
    return [taxonomy.action_label(action) for action in sorted(actions)]


def extract_entities(text: str) -> set[str]:
    """从文本中抽取实体。

    这里采用“已知实体词典 + 通用模型名/公司名规则”的轻量方案。
    它比纯 embedding 更适合工程场景，因为事件合并最需要知道“同一个主体是谁”。
    """
    normalized = normalize_text(text)
    taxonomy = get_event_taxonomy()
    entities: set[str] = set(taxonomy.match_entities(text))

    # 先用已知词典抽取稳定实体。
    for pattern, canonical_name in KNOWN_ENTITY_PATTERNS.items():
        if pattern in normalized:
            entities.add(canonical_name)

    # 抽取 GPT-5.5、GPT-4.1、Claude-3.7 这类模型名。
    for match in re.findall(r"\b(?:gpt|claude|llama|gemini|grok|mistral)[-\s]?\d[\w.-]*\b", normalized):
        entities.add(match.upper().replace(" ", "-"))

    # 抽取全大写缩写，例如 METR、API、GPU。过滤过短或太泛的缩写。
    for match in re.findall(r"\b[A-Z][A-Z0-9-]{2,}\b", text):
        if match.lower() not in {"api", "gpu", "llm", "ai"}:
            entities.add(match)

    # 抽取标题里常见的英文专名短语。这里只保留 2-4 个词的连续大写开头短语，
    # 用来捕捉 Parloa、Wispr Flow、Palo Alto Networks 这类词典外主体。
    proper_phrases = re.findall(
        r"\b(?:[A-Z][A-Za-z0-9&.-]+)(?:\s+[A-Z][A-Za-z0-9&.-]+){0,3}\b",
        text,
    )
    for phrase in proper_phrases:
        cleaned = phrase.strip(" .,:;()[]{}")
        words = cleaned.split()
        if not words:
            continue
        if cleaned.lower() in taxonomy_stop_words():
            continue
        if words[0].lower() in {"the", "how", "what", "why", "as", "from"}:
            continue
        # 单词实体只接收看起来像品牌或产品的词，避免把普通句首单词当实体。
        if len(words) == 1 and cleaned not in KNOWN_ENTITY_PATTERNS.values():
            continue
        entities.add(cleaned)

    return entities


def extract_products(text: str) -> set[str]:
    """从文本中抽取产品、模型和框架名称。"""

    normalized = normalize_text(text)
    products = set(get_event_taxonomy().match_products(text))

    # 抽取 GPT-5.5、Claude-3.7、Qwen3 这类可能尚未进入词典的新模型名。
    model_patterns = [
        r"\b(?:gpt|claude|llama|gemini|grok|mistral)[-\s]?\d[\w.-]*\b",
        r"\b(?:qwen|ernie|glm|hunyuan|deepseek|baichuan|minicpm)[-\s]?\d[\w.-]*\b",
    ]
    for pattern in model_patterns:
        for match in re.findall(pattern, normalized):
            products.add(match.upper().replace(" ", "-"))

    return products


def extract_actions(text: str) -> set[str]:
    """从文本中抽取新闻动作类型。"""
    normalized = normalize_text(text)

    # 优先使用 taxonomy 中可维护的动作规则，再用本文件的历史关键词作为补充。
    actions: set[str] = set(get_event_taxonomy().match_actions(text))

    for action_name, keywords in ACTION_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            # 返回统一的动作 ID，避免“发布”和 launch 这类别名在后续比较中对不上。
            actions.add(LEGACY_ACTION_IDS.get(action_name, action_name))

    return actions


def extract_keywords(text: str) -> set[str]:
    """抽取用于标题/摘要重叠计算的关键词。"""
    normalized = normalize_text(text)
    words = re.findall(r"[a-z0-9][a-z0-9.-]{2,}", normalized)

    keywords = {
        word.strip(".-")
        for word in words
        if word.strip(".-")
        and word.strip(".-") not in taxonomy_stop_words()
        and len(word.strip(".-")) >= 3
    }

    # 保留部分中文连续片段。当前 RSS 多数是英文标题，这里只是兼容中文来源。
    for match in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        if len(match) <= 12 and match not in taxonomy_stop_words():
            keywords.add(match)

    return keywords


def build_features(entry: ScoredNewsItem) -> EventFeatures:
    """为单条评分新闻构造聚类特征。"""
    # 实体、动作和关键词只从标题与摘要抽取。
    # 不能把来源名放进去，否则 “Microsoft AI Blog” 会被误识别为共同实体，
    # 导致同一来源的不同新闻被错误合并。
    signal_text = f"{entry.item.title} {entry.item.summary}"

    # embedding 只使用标题和摘要，不加入来源名或分类。
    # 原因是来源名和分类会让同一站点/同一栏目下的不同新闻看起来过于相似。
    embedding_text = f"{entry.item.title} {entry.item.summary}"
    entities = extract_entities(signal_text)
    products = extract_products(signal_text)

    return EventFeatures(
        text=signal_text,
        embedding=embed_text(embedding_text),
        entities=entities | products,
        products=products,
        actions=extract_actions(signal_text),
        keywords=extract_keywords(signal_text),
    )


def jaccard(left: set[str], right: set[str]) -> float:
    """计算两个集合的 Jaccard 相似度。"""
    # 任一集合为空时没有可解释的重叠，直接记为 0。
    if not left or not right:
        return 0.0
    union_size = len(left | right)
    if union_size == 0:
        return 0.0
    return len(left & right) / union_size


def pair_cluster_score(left: EventFeatures, right: EventFeatures) -> tuple[float, str]:
    """计算两条新闻是否应进入同一候选事件。

    返回值包含：
    - score：混合相似度分数。
    - reason：可写入调试信息的合并原因。

    分数设计思路：
    - embedding 负责语义近邻。
    - entity_overlap 负责“是不是同一主体”。
    - action_overlap 负责“是不是同一类进展”。
    - keyword_overlap 负责捕捉标题中的共同事实词。
    """
    # 先分别计算各类特征的相似度，再按经验权重合成一个总分。
    embedding_similarity = cosine_similarity(left.embedding, right.embedding)
    entity_overlap = jaccard(left.entities, right.entities)
    product_overlap = jaccard(left.products, right.products)
    action_overlap = get_event_taxonomy().action_similarity(left.actions, right.actions)
    keyword_overlap = jaccard(left.keywords, right.keywords)

    # 产品/模型比公司名更能限定事件边界，所以权重高于普通动作和关键词。
    score = (
        0.46 * embedding_similarity
        + 0.20 * entity_overlap
        + 0.18 * product_overlap
        + 0.10 * action_overlap
        + 0.06 * keyword_overlap
    )

    shared_entities = sorted(left.entities & right.entities)
    shared_products = sorted(left.products & right.products)
    shared_actions = sorted(left.actions & right.actions)
    shared_keywords = sorted(left.keywords & right.keywords)
    similar_action_pairs = get_event_taxonomy().similar_action_pairs(left.actions, right.actions)

    # reason 会进入调试信息，方便解释“为什么两条新闻被并到一起”。
    reason_parts = [
        f"混合分={score:.2f}",
        f"语义={embedding_similarity:.2f}",
    ]
    if shared_entities:
        reason_parts.append(f"共同实体={', '.join(shared_entities[:4])}")
    if shared_products:
        reason_parts.append(f"共同产品={', '.join(shared_products[:4])}")
    if shared_actions:
        reason_parts.append(f"共同动作={', '.join(format_action_names(shared_actions[:3]))}")
    elif similar_action_pairs:
        pair_labels = [
            f"{get_event_taxonomy().action_label(left_action)}~{get_event_taxonomy().action_label(right_action)}"
            for left_action, right_action, _score in similar_action_pairs[:3]
        ]
        reason_parts.append(f"相近动作={', '.join(pair_labels)}")
    if shared_keywords:
        reason_parts.append(f"共同关键词={', '.join(shared_keywords[:5])}")

    return score, "；".join(reason_parts)


def should_merge_pair(
    left: EventFeatures,
    right: EventFeatures,
    hybrid_threshold: float,
) -> tuple[bool, str]:
    """判断两条新闻是否应该在粗聚类阶段合并。

    这个函数是 Version 13 的核心。它故意使用多条规则，而不是单一阈值：

    - 高语义相似可以直接合并。
    - 同一产品/模型实体 + 中等语义相似，可以合并。
    - 同一公司 + 同一动作类型 + 中等语义相似，可以合并。
    - 没有任何实体、动作或关键词交集时，即使分数勉强够，也不合并。

    这样能提高召回，同时降低把“同一领域但不同事实”的新闻误合并的概率。
    """
    score, reason = pair_cluster_score(left, right)
    embedding_similarity = cosine_similarity(left.embedding, right.embedding)
    shared_entities = left.entities & right.entities
    shared_products = left.products & right.products
    shared_actions = left.actions & right.actions
    shared_keywords = left.keywords & right.keywords
    taxonomy = get_event_taxonomy()
    action_similarity = taxonomy.action_similarity(left.actions, right.actions)
    weak_actions = taxonomy_weak_actions()
    product_markers = taxonomy.product_markers or {"gpt", "claude", "gemini", "codex", "rubin", "llama", "grok"}

    # 有些产品名也会被抽进 entities，这里统一识别出“像产品/模型”的共同实体。
    # 例如 GPT-5、Claude-3.7 比 OpenAI、Anthropic 更适合作为强合并证据。
    product_like_entities = {
        entity
        for entity in shared_entities | shared_products
        if entity in shared_products
        or any(marker in entity.lower() for marker in product_markers)
    }

    # 如果共同实体只有高频公司名，必须要求额外证据。
    # 这条规则要放在“高语义相似”之前，因为同一来源同一栏目下的公司新闻可能语义也偏高。
    hub_only_overlap = bool(shared_entities) and not product_like_entities and all(
        entity in taxonomy_hub_entities() or any(entity.startswith(f"{hub} ") for hub in taxonomy_hub_entities())
        for entity in shared_entities
    )
    strong_shared_actions = shared_actions - weak_actions
    has_similar_strong_action = (
        action_similarity >= 0.72
        and not left.actions <= weak_actions
        and not right.actions <= weak_actions
    )
    # 高频主体只在证据足够强时合并，否则宁可留给后续 LLM 二次判断。
    if hub_only_overlap:
        if (strong_shared_actions or has_similar_strong_action) and embedding_similarity >= 0.55 and len(shared_keywords) >= 2:
            return True, f"高频主体但有强动作和事实关键词；{reason}"
        if embedding_similarity >= 0.84 and len(shared_keywords) >= 3:
            return True, f"高频主体但语义和事实词都高度一致；{reason}"
        return False, f"仅共享高频主体，证据不足；{reason}"

    # 语义极高时通常可以认为是同一事件或重复报道。
    if embedding_similarity >= 0.76:
        return True, f"高语义相似；{reason}"

    # 同一产品/模型实体是强信号。这里不要求动作完全一致，因为官方发布、
    # 媒体价格分析、安全解读可能动作标签不同，但仍围绕同一核心产品进展。
    if product_like_entities and (
        embedding_similarity >= 0.50
        or shared_actions
        or action_similarity >= 0.65
        or len(shared_keywords) >= 1
    ):
        return True, f"共同产品/模型实体；{reason}"

    # 同一实体 + 同一强动作，适合合并“同一公司开源/融资/安全事件”的多源报道。
    # “应用案例”和“发布”过于宽泛，不能只靠它们合并，否则容易把同一公司的不同新闻合并。
    if shared_entities and strong_shared_actions and embedding_similarity >= 0.38:
        return True, f"共同实体和动作；{reason}"

    # 动作词不同但语义相近时，例如“合作”和“接入/集成”，只要主体和事实词也对得上，
    # 就允许进入同一候选事件，避免因为用词不同把同一进展拆碎。
    if shared_entities and has_similar_strong_action and embedding_similarity >= 0.45 and len(shared_keywords) >= 1:
        return True, f"共同实体和相近动作；{reason}"

    # 如果只有弱动作重叠，需要额外满足更高语义相似度或更多事实关键词重叠。
    if shared_entities and shared_actions and embedding_similarity >= 0.58 and len(shared_keywords) >= 2:
        return True, f"共同实体、弱动作和事实关键词；{reason}"

    # 只有“同一公司 + 弱动作 + 极少关键词”时，不允许走混合分兜底。
    # 这是为了避免 Microsoft、NVIDIA、OpenAI 这类高频主体把不同主题的多篇新闻吸成一团。
    if (
        shared_entities
        and (shared_actions or action_similarity >= 0.65)
        and not strong_shared_actions
        and not has_similar_strong_action
        and len(shared_keywords) < 2
        and embedding_similarity < 0.72
    ):
        return False, f"仅共享主体和弱动作，证据不足；{reason}"

    # 标题关键词高度重叠时，即使没有抽到实体，也可能是同一事件的复述。
    if len(shared_keywords) >= 5 and embedding_similarity >= 0.52:
        return True, f"标题事实词高度重叠；{reason}"

    # 混合分超过阈值时仍要求至少有一种可解释重叠，避免纯泛化语义误合并。
    if score >= hybrid_threshold and (shared_entities or shared_actions or action_similarity >= 0.65 or len(shared_keywords) >= 2):
        return True, f"混合特征达到阈值；{reason}"

    return False, reason


def event_summary_text(items: list[ScoredNewsItem]) -> str:
    """生成事件摘要材料。"""
    parts: list[str] = []

    # 摘要材料只取前 5 条高分新闻，避免 prompt 和数据库字段过长。
    for entry in items[:5]:
        parts.append(f"{entry.item.title}：{entry.item.summary[:180]}")
    return "\n".join(parts)


def unique_preserve_order(values: list[str]) -> list[str]:
    """去重但保留原始顺序。"""
    return list(dict.fromkeys(value for value in values if value))


def build_event(
    event_index: int,
    items: list[ScoredNewsItem],
    title: str | None = None,
    summary: str | None = None,
) -> NewsEvent:
    """根据一组评分新闻构造事件对象。"""
    # 分数最高的新闻作为默认标题和代表链接，保证事件列表优先展示最重要来源。
    sorted_items = sorted(items, key=lambda entry: entry.score, reverse=True)
    representative = sorted_items[0]

    # 事件向量使用簇内所有新闻文本，便于后续按事件级别做 RAG 检索。
    event_text = " ".join(item_event_text(entry.item) for entry in sorted_items)
    embedding = embed_text(event_text)

    # 来源和类别保留首次出现顺序，展示时更贴近原始新闻排序。
    scores = [entry.score for entry in sorted_items]
    sources = unique_preserve_order([entry.item.source for entry in sorted_items])
    categories = unique_preserve_order([entry.item.category for entry in sorted_items])

    return NewsEvent(
        event_id=f"event_{event_index}",
        title=title or representative.item.title,
        summary=summary or event_summary_text(sorted_items),
        scored_items=sorted_items,
        embedding=embedding,
        average_score=sum(scores) / len(scores),
        max_score=max(scores),
        sources=sources,
        categories=categories,
        representative_link=representative.item.link,
    )


def build_clusters_from_pairs(
    scored_items: list[ScoredNewsItem],
    features: list[EventFeatures],
    hybrid_threshold: float,
) -> list[list[ScoredNewsItem]]:
    """根据成对相似关系构造事件簇。"""
    union_find = UnionFind(len(scored_items))

    # 两两比较。日报入选新闻通常几十条，O(n^2) 在这里可接受，且结果更稳定。
    for left_index in range(len(scored_items)):
        for right_index in range(left_index + 1, len(scored_items)):
            should_merge, _reason = should_merge_pair(
                features[left_index],
                features[right_index],
                hybrid_threshold=hybrid_threshold,
            )
            if should_merge:
                union_find.union(left_index, right_index)

    grouped: dict[int, list[ScoredNewsItem]] = {}
    for index, entry in enumerate(scored_items):
        # 同一个根节点代表同一个连通簇，也就是一个候选事件。
        root = union_find.find(index)
        grouped.setdefault(root, []).append(entry)

    return list(grouped.values())


def cluster_scored_items(
    scored_items: list[ScoredNewsItem],
    similarity_threshold: float = 0.58,
) -> list[NewsEvent]:
    """把评分新闻聚成候选事件。

    参数名 `similarity_threshold` 为了兼容旧调用保留，但含义已经从“纯 embedding
    阈值”变成“混合特征阈值”。默认值从旧版 0.78 调低到 0.58，是因为新版阈值
    已经混入实体、动作和关键词，不再和纯余弦相似度同量纲。
    """
    if not scored_items:
        return []

    # 高分新闻优先进入候选事件，但成对聚类不会依赖处理顺序。
    sorted_items = sorted(scored_items, key=lambda entry: entry.score, reverse=True)

    # 为每条新闻生成 embedding 与可解释特征。
    features = [build_features(entry) for entry in sorted_items]

    # 使用并查集把所有满足合并条件的新闻连成事件簇。
    clusters = build_clusters_from_pairs(
        sorted_items,
        features,
        hybrid_threshold=similarity_threshold,
    )

    # 簇内按分数排序，簇间按最高分和平均分排序。
    events = [
        build_event(index + 1, cluster)
        for index, cluster in enumerate(clusters)
    ]

    return sorted(events, key=lambda event: (event.max_score, event.average_score), reverse=True)


def rebuild_events_from_groups(
    groups: list[tuple[list[str], str, str]],
    source_events: list[NewsEvent],
) -> list[NewsEvent]:
    """按 LLM 返回的事件分组重建最终事件。

    groups 的每一项是：
    - 候选 event_id 列表
    - LLM 生成的新事件标题
    - LLM 生成的新事件摘要
    """
    # 先建索引，方便用 LLM 返回的 event_id 找回原始候选事件。
    event_by_id = {event.event_id: event for event in source_events}

    # used_event_ids 防止 LLM 把同一个候选事件放进多个分组时重复计入。
    used_event_ids: set[str] = set()
    rebuilt_events: list[NewsEvent] = []

    for event_ids, title, summary in groups:
        merged_items: list[ScoredNewsItem] = []

        # 忽略 LLM 返回的未知 ID，避免因为格式小错误中断整次日报生成。
        normalized_ids = [event_id for event_id in event_ids if event_id in event_by_id]

        for event_id in normalized_ids:
            if event_id in used_event_ids:
                continue
            used_event_ids.add(event_id)
            merged_items.extend(event_by_id[event_id].scored_items)

        if not merged_items:
            continue

        rebuilt_events.append(
            build_event(
                len(rebuilt_events) + 1,
                merged_items,
                title=title.strip() or None,
                summary=summary.strip() or None,
            )
        )

    # LLM 如果漏掉某个候选事件，保守保留，避免丢新闻。
    for event in source_events:
        if event.event_id in used_event_ids:
            continue
        rebuilt_events.append(
            build_event(
                len(rebuilt_events) + 1,
                event.scored_items,
                title=event.title,
                summary=event.summary,
            )
        )

    return sorted(rebuilt_events, key=lambda event: (event.max_score, event.average_score), reverse=True)


def format_events_for_state(events: list[NewsEvent], max_events: int = 30) -> list[str]:
    """把事件聚类结果整理成可写入 run_state decisions 的文本。"""
    lines: list[str] = []

    for index, event in enumerate(events[:max_events], start=1):
        # 每个事件只展示前几条标题，保证状态日志可读且不会膨胀太快。
        item_titles = "；".join(entry.item.title for entry in event.scored_items[:6])
        lines.append(
            f"事件 {index}｜{event.title}｜新闻数 {len(event.scored_items)}｜"
            f"来源 {', '.join(event.sources) or '未知'}｜相关新闻：{item_titles}"
        )

    return lines


def format_events_for_prompt(events: list[NewsEvent], max_events: int = 12) -> str:
    """把事件列表格式化为 DeepSeek prompt 文本。"""
    if not events:
        return "暂无事件。"

    blocks: list[str] = []
    for index, event in enumerate(events[:max_events], start=1):
        # 给 LLM 的每个候选事件保留少量代表新闻，帮助它判断是否需要二次合并或改名。
        item_lines = [
            f"- [{entry.item.source}｜{entry.item.category}] {entry.item.title} ({entry.score} 分)"
            for entry in event.scored_items[:6]
        ]

        blocks.append(
            "\n".join(
                [
                    f"## 事件 {index}: {event.title}",
                    f"来源：{', '.join(event.sources)}",
                    f"类别：{', '.join(event.categories)}",
                    f"新闻数：{len(event.scored_items)}",
                    f"最高分：{event.max_score}，平均分：{event.average_score:.1f}",
                    f"代表链接：{event.representative_link or '无'}",
                    "相关新闻：",
                    *item_lines,
                    "事件摘要材料：",
                    event.summary or "无",
                ]
            )
        )

    return "\n\n".join(blocks)


def event_compression_ratio(selected_item_count: int, event_count: int) -> float:
    """计算事件压缩率，供测试或后续评估使用。

    压缩率 = 入选新闻数 / 最终候选事件数。
    如果压缩率接近 1，说明仍然是一条新闻一个事件。
    """
    if event_count <= 0:
        return 0.0
    return selected_item_count / event_count
