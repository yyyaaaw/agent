"""用户反馈模块。

Version 4 开始，agent 不只读取静态 profile，也可以读取反馈配置。

feedback.json 用来表达“我后来发现自己喜欢/不喜欢什么”：
- liked_keywords：命中这些词会加分。
- disliked_keywords：命中这些词会扣分。
- liked_sources：喜欢的来源会加分。
- disliked_sources：不喜欢的来源会扣分。
- liked_categories：喜欢的类别会加分。
- disliked_categories：不喜欢的类别会扣分。

这是一种轻量反馈闭环，不需要先做界面，也能让打分逐步贴近用户口味。
"""

from __future__ import annotations

# json 用来读取和写入 feedback.json。
import json

# dataclass 用来定义反馈数据结构。
from dataclasses import dataclass

# Path 用来表示反馈文件路径。
from pathlib import Path


@dataclass(frozen=True)
class FeedbackRules:
    """用户反馈规则。"""

    # 喜欢的关键词，命中后加分。
    liked_keywords: list[str]

    # 不喜欢的关键词，命中后扣分。
    disliked_keywords: list[str]

    # 喜欢的资讯来源。
    liked_sources: list[str]

    # 不喜欢的资讯来源。
    disliked_sources: list[str]

    # 喜欢的来源类别。
    liked_categories: list[str]

    # 不喜欢的来源类别。
    disliked_categories: list[str]


# 默认反馈为空，表示不额外影响打分。
DEFAULT_FEEDBACK = FeedbackRules(
    liked_keywords=[],
    disliked_keywords=[],
    liked_sources=[],
    disliked_sources=[],
    liked_categories=[],
    disliked_categories=[],
)


def load_feedback(feedback_path: Path) -> FeedbackRules:
    """从 feedback.json 读取用户反馈规则。"""
    # 如果反馈文件不存在，就使用空反馈。
    if not feedback_path.exists():
        return DEFAULT_FEEDBACK

    # 读取 JSON 配置。
    data = json.loads(feedback_path.read_text(encoding="utf-8"))

    # 把每个字段都转换成字符串列表，避免配置里出现非字符串导致后续拼接报错。
    return FeedbackRules(
        liked_keywords=[str(item) for item in data.get("liked_keywords", [])],
        disliked_keywords=[str(item) for item in data.get("disliked_keywords", [])],
        liked_sources=[str(item) for item in data.get("liked_sources", [])],
        disliked_sources=[str(item) for item in data.get("disliked_sources", [])],
        liked_categories=[str(item) for item in data.get("liked_categories", [])],
        disliked_categories=[str(item) for item in data.get("disliked_categories", [])],
    )


def save_feedback(feedback_path: Path, feedback: FeedbackRules) -> None:
    """把反馈规则写回 feedback.json。"""
    # 确保 feedback.json 所在目录存在。
    feedback_path.parent.mkdir(parents=True, exist_ok=True)

    # 转成普通 dict，保持字段顺序，方便用户直接阅读。
    payload = {
        "liked_keywords": feedback.liked_keywords,
        "disliked_keywords": feedback.disliked_keywords,
        "liked_sources": feedback.liked_sources,
        "disliked_sources": feedback.disliked_sources,
        "liked_categories": feedback.liked_categories,
        "disliked_categories": feedback.disliked_categories,
    }

    # ensure_ascii=False 保留中文；indent=2 让文件更适合人工查看。
    feedback_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
