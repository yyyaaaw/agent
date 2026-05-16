"""交互式用户反馈模块。

Version 7 开始，agent 不再只依赖手写 feedback.json。
你可以运行：

python catch_ai.py --feedback

然后对最近一次运行的事件点赞、点踩、添加备注。
这些反馈会先写入 SQLite，再自动汇总回 feedback.json。
下次运行日报时，agent 直接读取更新后的 feedback.json 参与评分。
"""

from __future__ import annotations

# json 用来读取 events 表里的 sources_json/categories_json。
import json

# dataclass 用来定义反馈事件结构。
from dataclasses import dataclass

# Path 用来表示数据库路径。
from pathlib import Path

# connect / utc_now_text 复用数据库模块的连接和时间函数。
from ai_report_agent.database import connect, initialize_database, utc_now_text

# FeedbackRules 是评分模块可直接使用的反馈规则结构。
# load_feedback / save_feedback 用来读取和自动更新 feedback.json。
from ai_report_agent.feedback import FeedbackRules, load_feedback, save_feedback


@dataclass(frozen=True)
class FeedbackEvent:
    """可供用户反馈的事件。"""

    # events 表主键。
    event_id: int

    # 运行 ID。
    run_id: str

    # 事件标题。
    title: str

    # 事件摘要。
    summary: str

    # 来源列表。
    sources: list[str]

    # 类别列表。
    categories: list[str]

    # 事件最高分。
    max_score: int

    # 事件包含的新闻条数。
    item_count: int


def parse_number_list(value: str) -> set[int]:
    """把用户输入的 1,2,3 转成数字集合。"""
    # 去掉首尾空白。
    value = value.strip()

    # 空输入表示没有选择。
    if not value:
        return set()

    # 按逗号拆分，并转换为整数。
    numbers: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if part.isdigit():
            numbers.add(int(part))

    # 返回数字集合。
    return numbers


def latest_run_id_with_events(database_path: Path) -> str | None:
    """查找最近一次包含事件的运行 ID。"""
    # 查询最新有事件的 run_id。
    with connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT run_id
            FROM events
            GROUP BY run_id
            ORDER BY MAX(created_at) DESC
            LIMIT 1
            """
        ).fetchone()

    # 没有事件时返回 None。
    if row is None:
        return None

    # 返回 run_id。
    return str(row["run_id"])


def load_events_for_feedback(database_path: Path, run_id: str | None = None) -> list[FeedbackEvent]:
    """读取某次运行的事件，供用户反馈。"""
    # 如果没有指定 run_id，就找最近一次有事件的运行。
    if run_id is None:
        run_id = latest_run_id_with_events(database_path)

    # 没有任何可反馈运行时返回空列表。
    if run_id is None:
        return []

    # 查询该次运行的事件。
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, run_id, title, summary, sources_json, categories_json,
                   max_score, item_count
            FROM events
            WHERE run_id = ?
            ORDER BY max_score DESC, average_score DESC, id
            """,
            (run_id,),
        ).fetchall()

    # 转成 FeedbackEvent 对象。
    return [
        FeedbackEvent(
            event_id=int(row["id"]),
            run_id=str(row["run_id"]),
            title=str(row["title"]),
            summary=str(row["summary"]),
            sources=[str(item) for item in json.loads(row["sources_json"] or "[]")],
            categories=[str(item) for item in json.loads(row["categories_json"] or "[]")],
            max_score=int(row["max_score"]),
            item_count=int(row["item_count"]),
        )
        for row in rows
    ]


def save_event_feedback(
    database_path: Path,
    event_id: int,
    feedback_type: str,
    note: str = "",
) -> None:
    """保存一条事件反馈。"""
    # 写入时间。
    now = utc_now_text()

    # 保存反馈。
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO event_feedback (event_id, feedback_type, note, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (event_id, feedback_type, note, now),
        )


def run_feedback_session(database_path: Path, feedback_path: Path) -> None:
    """运行一次命令行交互反馈。"""
    # 确保数据库表存在。
    initialize_database(database_path)

    # 读取最近一次运行的事件。
    events = load_events_for_feedback(database_path)

    # 没有事件时提示用户先运行日报。
    if not events:
        print("没有找到可反馈的事件。请先运行：python catch_ai.py --run-once")
        return

    # 展示事件列表。
    print("最近一次日报的事件列表：")
    for index, event in enumerate(events, start=1):
        sources = ", ".join(event.sources)
        categories = ", ".join(event.categories)
        print(f"{index}. {event.title}")
        print(f"   来源：{sources or '未知'}")
        print(f"   类别：{categories or '未知'}")
        print(f"   新闻数：{event.item_count}，最高分：{event.max_score}")

    # 读取用户点赞/点踩输入。
    liked_numbers = parse_number_list(input("喜欢哪些事件？输入编号，如 1,3；没有就直接回车："))
    disliked_numbers = parse_number_list(input("不喜欢哪些事件？输入编号，如 2；没有就直接回车："))

    # 读取整体备注。
    note = input("备注或偏好说明，可直接回车跳过：").strip()

    # 保存点赞。
    for number in liked_numbers:
        if 1 <= number <= len(events):
            save_event_feedback(database_path, events[number - 1].event_id, "like", note)

    # 保存点踩。
    for number in disliked_numbers:
        if 1 <= number <= len(events):
            save_event_feedback(database_path, events[number - 1].event_id, "dislike", note)

    # 如果只写了备注但没有选择事件，就把备注挂到第一条事件上，避免丢失。
    if note and not liked_numbers and not disliked_numbers:
        save_event_feedback(database_path, events[0].event_id, "note", note)

    # 从数据库反馈重新生成动态规则。
    dynamic_feedback = build_feedback_rules_from_history(database_path)

    # 读取现有 feedback.json，保留用户原本手写或历史同步过的偏好。
    file_feedback = load_feedback(feedback_path)

    # 合并旧规则和新规则，避免重复，并保持原有顺序优先。
    updated_feedback = merge_feedback_rules(file_feedback, dynamic_feedback)

    # 把合并后的结果写回 feedback.json，让用户能直接查看 agent 学到的偏好。
    save_feedback(feedback_path, updated_feedback)

    # 打印完成提示。
    print(f"反馈已保存，并已自动更新：{feedback_path}")


def build_feedback_rules_from_history(database_path: Path) -> FeedbackRules:
    """从历史事件反馈中构造动态反馈规则。"""
    # 确保表存在。
    initialize_database(database_path)

    # 查询事件反馈及其对应事件。
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT f.feedback_type, e.title, e.sources_json, e.categories_json
            FROM event_feedback f
            JOIN events e ON e.id = f.event_id
            ORDER BY f.created_at DESC
            LIMIT 200
            """
        ).fetchall()

    # 没有反馈时返回空规则。
    if not rows:
        return FeedbackRules([], [], [], [], [], [])

    # 计数器用普通 dict，避免额外依赖。
    liked_keywords: dict[str, int] = {}
    disliked_keywords: dict[str, int] = {}
    liked_sources: dict[str, int] = {}
    disliked_sources: dict[str, int] = {}
    liked_categories: dict[str, int] = {}
    disliked_categories: dict[str, int] = {}

    # 根据反馈类型累计关键词、来源、类别。
    for row in rows:
        feedback_type = str(row["feedback_type"])
        title_tokens = extract_feedback_keywords(str(row["title"]))
        sources = [str(item) for item in json.loads(row["sources_json"] or "[]")]
        categories = [str(item) for item in json.loads(row["categories_json"] or "[]")]

        if feedback_type == "like":
            add_counts(liked_keywords, title_tokens)
            add_counts(liked_sources, sources)
            add_counts(liked_categories, categories)
        elif feedback_type == "dislike":
            add_counts(disliked_keywords, title_tokens)
            add_counts(disliked_sources, sources)
            add_counts(disliked_categories, categories)

    # 只保留出现次数较高的内容，避免一次误点影响太大。
    return FeedbackRules(
        liked_keywords=top_keys(liked_keywords, 12),
        disliked_keywords=top_keys(disliked_keywords, 12),
        liked_sources=top_keys(liked_sources, 8),
        disliked_sources=top_keys(disliked_sources, 8),
        liked_categories=top_keys(liked_categories, 8),
        disliked_categories=top_keys(disliked_categories, 8),
    )


def extract_feedback_keywords(title: str) -> list[str]:
    """从事件标题中提取可用于反馈规则的关键词。"""
    # 为避免重复实现复杂分词，这里采用简单规则：按空格和常见分隔符切分。
    normalized = title.replace("｜", " ").replace("/", " ").replace("-", " ")
    tokens = [
        token.strip(" ，。,:：()（）[]【】").lower()
        for token in normalized.split()
    ]

    # 保留较长 token，中文短语一般不会被空格拆开，所以可以保留。
    return [token for token in tokens if len(token) >= 3]


def add_counts(counter: dict[str, int], values: list[str]) -> None:
    """给计数字典累加。"""
    for value in values:
        if value:
            counter[value] = counter.get(value, 0) + 1


def top_keys(counter: dict[str, int], limit: int) -> list[str]:
    """取计数字典中出现最多的 key。"""
    return [
        key
        for key, _ in sorted(counter.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def merge_feedback_rules(base: FeedbackRules, dynamic: FeedbackRules) -> FeedbackRules:
    """合并 feedback.json 规则和历史反馈生成的动态规则。"""
    return FeedbackRules(
        liked_keywords=merge_lists(base.liked_keywords, dynamic.liked_keywords),
        disliked_keywords=merge_lists(base.disliked_keywords, dynamic.disliked_keywords),
        liked_sources=merge_lists(base.liked_sources, dynamic.liked_sources),
        disliked_sources=merge_lists(base.disliked_sources, dynamic.disliked_sources),
        liked_categories=merge_lists(base.liked_categories, dynamic.liked_categories),
        disliked_categories=merge_lists(base.disliked_categories, dynamic.disliked_categories),
    )


def merge_lists(left: list[str], right: list[str]) -> list[str]:
    """合并两个字符串列表并保持顺序去重。"""
    return list(dict.fromkeys([*left, *right]))
