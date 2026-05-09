"""SQLite 数据库模块。

Version 5 在 Version 4 的 SQLite 长期记忆基础上，改用本地 BGE-M3 生成真实语义 embedding。

Version 2 会把状态保存成 JSON 文件，这适合人工查看，
但不方便长期查询、统计和做 RAG 检索。

这个模块使用 Python 标准库 sqlite3，把以下信息写入本地数据库：
1. 每次运行的状态。
2. 每次采集到的新闻。
3. 每条新闻的去重、评分、入选结果。
4. 最终生成的报告和自查结果。
5. 采集失败的来源错误。

SQLite 是一个单文件数据库，不需要额外安装服务，很适合本地 agent。
"""

from __future__ import annotations

# json 用来把 list/dict 这类结构化数据存进 SQLite 的 TEXT 字段。
import json

# sqlite3 是 Python 标准库自带的 SQLite 客户端。
import sqlite3

# datetime 用来生成统一的写入时间。
from datetime import datetime

# Path 用来处理数据库文件路径。
from pathlib import Path

# DeduplicationResult 提供去重结果类型。
from ai_report_agent.deduplicator import DeduplicationResult, item_keys

# embed_text / embed_texts / cosine_similarity 用于 BGE-M3 向量检索版 RAG。
from ai_report_agent.embeddings import cosine_similarity, embed_text, embed_texts

# FeedbackRules 是用户反馈规则类型。
from ai_report_agent.feedback import FeedbackRules

# ScoredNewsItem 提供评分结果类型。
from ai_report_agent.scorer import ScoredNewsItem

# NewsItem 是采集阶段产出的标准资讯结构。
from ai_report_agent.sources import NewsItem

# AgentRunState 是本次运行状态结构。
from ai_report_agent.state import AgentRunState


def utc_now_text() -> str:
    """返回当前时间字符串，用于数据库 created_at/updated_at 字段。"""
    # 这里使用本地时间，便于和报告生成时间保持一致。
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(database_path: Path) -> sqlite3.Connection:
    """创建 SQLite 连接，并启用按字段名访问结果。"""
    # sqlite3.connect 会在文件不存在时自动创建数据库文件。
    connection = sqlite3.connect(database_path)

    # row_factory 让查询结果可以像字典一样按列名读取。
    connection.row_factory = sqlite3.Row

    # foreign_keys 默认关闭，这里显式开启外键约束。
    connection.execute("PRAGMA foreign_keys = ON")

    # 返回数据库连接对象。
    return connection


def initialize_database(database_path: Path) -> None:
    """初始化数据库表结构。"""
    # 确保数据库所在目录存在。
    database_path.parent.mkdir(parents=True, exist_ok=True)

    # 使用 with 可以确保连接正常关闭。
    with connect(database_path) as connection:
        # runs 表记录每次 agent 运行的总体状态。
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                raw_item_count INTEGER NOT NULL DEFAULT 0,
                unique_item_count INTEGER NOT NULL DEFAULT 0,
                selected_item_count INTEGER NOT NULL DEFAULT 0,
                duplicate_count INTEGER NOT NULL DEFAULT 0,
                decisions_json TEXT NOT NULL DEFAULT '[]',
                errors_json TEXT NOT NULL DEFAULT '[]',
                report_path TEXT NOT NULL DEFAULT '',
                raw_data_path TEXT NOT NULL DEFAULT '',
                critic_result TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        # news_items 表记录每次运行采集到的新闻及其处理结果。
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS news_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                source TEXT NOT NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL,
                published TEXT NOT NULL,
                summary TEXT NOT NULL,
                normalized_link TEXT NOT NULL,
                normalized_title TEXT NOT NULL,
                embedding_json TEXT NOT NULL DEFAULT '[]',
                is_unique INTEGER NOT NULL DEFAULT 0,
                is_selected INTEGER NOT NULL DEFAULT 0,
                score INTEGER,
                reasons_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
            )
            """
        )

        # 如果用户从 v3 数据库升级到 v4，旧表可能还没有 embedding_json 字段。
        # SQLite 不支持 CREATE TABLE IF NOT EXISTS 自动补列，所以这里做一次兼容迁移。
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(news_items)").fetchall()
        }
        if "embedding_json" not in existing_columns:
            connection.execute("ALTER TABLE news_items ADD COLUMN embedding_json TEXT NOT NULL DEFAULT '[]'")

        # reports 表保存最终 Markdown 报告正文和路径。
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL UNIQUE,
                report_date TEXT NOT NULL,
                path TEXT NOT NULL,
                markdown TEXT NOT NULL,
                critic_result TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
            )
            """
        )

        # user_feedback 表保存反馈配置快照，方便之后分析哪次运行用了什么反馈规则。
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                liked_keywords_json TEXT NOT NULL DEFAULT '[]',
                disliked_keywords_json TEXT NOT NULL DEFAULT '[]',
                liked_sources_json TEXT NOT NULL DEFAULT '[]',
                disliked_sources_json TEXT NOT NULL DEFAULT '[]',
                liked_categories_json TEXT NOT NULL DEFAULT '[]',
                disliked_categories_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
            )
            """
        )

        # source_errors 表保存每个采集失败来源的错误详情，便于统计来源质量。
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS source_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                error TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
            )
            """
        )

        # 常用查询索引：按链接、标题、运行编号和日期检索。
        connection.execute("CREATE INDEX IF NOT EXISTS idx_news_items_link ON news_items(normalized_link)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_news_items_title ON news_items(normalized_title)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_news_items_run ON news_items(run_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_reports_date ON reports(report_date)")


def upsert_run_state(database_path: Path, state: AgentRunState) -> None:
    """把当前运行状态写入 runs 表。

    这个函数可以在流程中多次调用。
    如果 run_id 已存在，就更新最新状态；如果不存在，就插入新记录。
    """
    # 把 decisions/errors 列表转成 JSON 字符串。
    decisions_json = json.dumps(state.decisions, ensure_ascii=False)
    errors_json = json.dumps(state.errors, ensure_ascii=False)

    # 当前写入时间。
    now = utc_now_text()

    # 执行插入或更新。
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO runs (
                run_id, started_at, raw_item_count, unique_item_count,
                selected_item_count, duplicate_count, decisions_json,
                errors_json, report_path, raw_data_path, critic_result,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                raw_item_count = excluded.raw_item_count,
                unique_item_count = excluded.unique_item_count,
                selected_item_count = excluded.selected_item_count,
                duplicate_count = excluded.duplicate_count,
                decisions_json = excluded.decisions_json,
                errors_json = excluded.errors_json,
                report_path = excluded.report_path,
                raw_data_path = excluded.raw_data_path,
                critic_result = excluded.critic_result,
                updated_at = excluded.updated_at
            """,
            (
                state.run_id,
                state.started_at,
                state.raw_item_count,
                state.unique_item_count,
                state.selected_item_count,
                state.duplicate_count,
                decisions_json,
                errors_json,
                state.report_path,
                state.raw_data_path,
                state.critic_result,
                now,
                now,
            ),
        )


def save_source_errors(database_path: Path, run_id: str, errors: list[str]) -> None:
    """保存采集失败来源的错误信息。"""
    # 没有错误时无需写入。
    if not errors:
        return

    # 当前写入时间。
    now = utc_now_text()

    # 写入每条错误。
    with connect(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO source_errors (run_id, source_name, error, created_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    # 错误字符串格式通常是 "来源名: 错误详情"，这里拆出来源名。
                    error.split(":", 1)[0].strip(),
                    error,
                    now,
                )
                for error in errors
            ],
        )


def save_feedback_rules(database_path: Path, run_id: str, feedback: FeedbackRules) -> None:
    """保存本次运行使用的用户反馈规则快照。"""
    # 当前写入时间。
    now = utc_now_text()

    # 写入反馈配置，方便之后复盘评分变化。
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO user_feedback (
                run_id,
                liked_keywords_json,
                disliked_keywords_json,
                liked_sources_json,
                disliked_sources_json,
                liked_categories_json,
                disliked_categories_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                json.dumps(feedback.liked_keywords, ensure_ascii=False),
                json.dumps(feedback.disliked_keywords, ensure_ascii=False),
                json.dumps(feedback.liked_sources, ensure_ascii=False),
                json.dumps(feedback.disliked_sources, ensure_ascii=False),
                json.dumps(feedback.liked_categories, ensure_ascii=False),
                json.dumps(feedback.disliked_categories, ensure_ascii=False),
                now,
            ),
        )


def save_raw_news_items(database_path: Path, run_id: str, items: list[NewsItem]) -> None:
    """保存原始采集新闻。"""
    # 当前写入时间。
    now = utc_now_text()

    # 先把所有新闻拼成 embedding 输入文本。
    embedding_texts = [
        f"{item.title} {item.summary} {item.category} {item.source}"
        for item in items
    ]

    # 批量生成 embedding；BGE 批量处理比逐条处理更快。
    embeddings = embed_texts(embedding_texts)

    # 把 NewsItem 转成数据库行。
    rows = []
    for item, embedding in zip(items, embeddings):
        # item_keys 会生成链接键和标题键，后续去重和历史检索都会用到。
        normalized_link, normalized_title = item_keys(item)

        # embedding 用 JSON 存入 SQLite。
        embedding_json = json.dumps(embedding)

        # 保存一行新闻。
        rows.append(
            (
                run_id,
                item.source,
                item.category,
                item.title,
                item.link,
                item.published,
                item.summary,
                normalized_link,
                normalized_title,
                embedding_json,
                now,
            )
        )

    # 批量写入数据库。
    with connect(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO news_items (
                run_id, source, category, title, link, published, summary,
                normalized_link, normalized_title, embedding_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def mark_unique_news_items(
    database_path: Path,
    run_id: str,
    dedup_result: DeduplicationResult,
) -> None:
    """把去重结果写回 news_items 表。"""
    # 建立本次运行中被保留资讯的链接键集合和标题键集合。
    unique_keys = {item_keys(item) for item in dedup_result.unique_items}

    # 读取本次运行所有新闻，并逐条判断是否属于 unique_keys。
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, normalized_link, normalized_title
            FROM news_items
            WHERE run_id = ?
            ORDER BY id
            """,
            (run_id,),
        ).fetchall()

        # seen_keys 用来确保同一组重复内容只有第一条被标记为唯一。
        seen_keys: set[tuple[str, str]] = set()

        # 准备批量更新参数。
        updates = []
        for row in rows:
            # 当前数据库行的去重键。
            key = (row["normalized_link"], row["normalized_title"])

            # 只有在去重结果中、且之前没标记过的第一条，才算唯一。
            is_unique = 1 if key in unique_keys and key not in seen_keys else 0

            # 如果当前行被标记为唯一，就记录这个键。
            if is_unique:
                seen_keys.add(key)

            # 追加更新参数。
            updates.append((is_unique, row["id"]))

        # 批量更新每一行的 is_unique 字段。
        connection.executemany(
            "UPDATE news_items SET is_unique = ? WHERE id = ?",
            updates,
        )


def save_scored_news_items(
    database_path: Path,
    run_id: str,
    scored_items: list[ScoredNewsItem],
    selected_items: list[ScoredNewsItem],
) -> None:
    """保存评分结果和是否入选 DeepSeek 分析。"""
    # selected_keys 用来快速判断某条评分资讯是否入选。
    selected_keys = {item_keys(entry.item) for entry in selected_items}

    # 逐条更新分数、原因和入选状态。
    updates = []
    for entry in scored_items:
        # 生成当前资讯的链接键和标题键。
        normalized_link, normalized_title = item_keys(entry.item)

        # 判断当前资讯是否在入选集合里。
        is_selected = 1 if (normalized_link, normalized_title) in selected_keys else 0

        # reasons 转成 JSON 字符串保存。
        reasons_json = json.dumps(entry.reasons, ensure_ascii=False)

        # 追加一条更新参数。
        updates.append(
            (
                entry.score,
                reasons_json,
                is_selected,
                run_id,
                normalized_link,
                normalized_title,
            )
        )

    # 批量更新数据库。
    with connect(database_path) as connection:
        connection.executemany(
            """
            UPDATE news_items
            SET score = ?, reasons_json = ?, is_selected = ?
            WHERE run_id = ? AND normalized_link = ? AND normalized_title = ? AND is_unique = 1
            """,
            updates,
        )


def save_report_record(
    database_path: Path,
    run_id: str,
    report_path: Path,
    markdown: str,
    critic_result: str,
) -> None:
    """保存最终报告正文和自查结果。"""
    # report_date 使用文件生成当天日期，便于按天查询。
    report_date = datetime.now().strftime("%Y-%m-%d")

    # 当前写入时间。
    now = utc_now_text()

    # 写入 reports 表；同一个 run_id 只保留一份最终报告。
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO reports (run_id, report_date, path, markdown, critic_result, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                path = excluded.path,
                markdown = excluded.markdown,
                critic_result = excluded.critic_result
            """,
            (run_id, report_date, str(report_path), markdown, critic_result, now),
        )

'''
RAG 是 Retrieval-Augmented Generation，中文通常叫“检索增强生成”。
Retrieval：先检索资料
Augmented：把资料补充给模型
Generation：再让模型生成答案

在 agent-v5 中，主要由 retrieve_related_history(...) 实现 RAG 检索：
在调用 DeepSeek 之前，先用本地 BGE-M3 把本次入选资讯转换成真实语义 embedding，
再从数据库里查找 embedding 相似的历史记录，作为 RAG 上下文输入。

这就是 RAG 的核心价值：让 LLM 不只看当前输入，而是先检索历史资料，再带着资料生成回答。这样可以让模型的输出更有连续性和深度，尤其适合需要趋势分析的日报场景。
解决的核心问题是：
LLM 本身不知道你的私有数据库、历史日报、本地文件。所以你要先帮它把相关资料找出来，再放进 prompt。

现在的知识库就是 SQLite，检索器就是 retrieve_related_history()，生成器就是 DeepSeek。
'''

def retrieve_related_history(
    database_path: Path,
    current_run_id: str,
    selected_items: list[NewsItem],
    limit: int = 8,
) -> str:
    """从历史数据库中检索与本次入选资讯语义相似的旧记录。

    返回文本会写入 DeepSeek 的最终汇总 prompt。
    如果数据库里还没有历史记录，则返回空字符串。
    """
    # 没有入选资讯时无法检索，直接返回空字符串。
    if not selected_items:
        return ""

    # 把本次入选资讯合并成查询文本，并生成查询向量。
    query_text = " ".join(
        f"{item.title} {item.summary} {item.category} {item.source}"
        for item in selected_items
    )
    query_embedding = embed_text(query_text)

    # 查询历史入选或高分资讯，排除本次运行。
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT title, source, category, published, score, embedding_json
            FROM news_items
            WHERE run_id != ?
              AND (is_selected = 1 OR score >= 5)
            ORDER BY created_at DESC
            """,
            (current_run_id,),
        ).fetchall()

    # 没有历史命中时返回空字符串。
    if not rows:
        return ""

    # 计算每条历史资讯和本次查询向量的余弦相似度。
    scored_rows = []
    for row in rows:
        # 读取历史资讯向量。
        embedding = json.loads(row["embedding_json"] or "[]")

        # 空向量没有检索价值，跳过。
        if not embedding:
            continue

        # 计算相似度。
        similarity = cosine_similarity(query_embedding, embedding)

        # 相似度太低的历史记录不放入上下文，避免噪声。
        if similarity >= 0.12:
            scored_rows.append((similarity, row))

    # 按相似度从高到低排序，并限制数量。
    scored_rows = sorted(scored_rows, key=lambda item: item[0], reverse=True)[:limit]

    # 如果没有足够相似的历史记录，返回空字符串。
    if not scored_rows:
        return ""

    # 把历史命中格式化成 prompt 可读文本。
    lines = ["以下是向量检索找到的相关历史资讯，可用于判断趋势延续性："]
    for index, (similarity, row) in enumerate(scored_rows, start=1):
        lines.append(
            f"{index}. [{row['source']}｜{row['category']}] {row['title']} "
            f"(发布时间：{row['published'] or '未知'}，历史分数：{row['score']}，相似度：{similarity:.2f})"
        )

    # 返回多行历史上下文。
    return "\n".join(lines)
