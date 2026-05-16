"""基于 MCP SDK 的 AI 日报 Agent Server。

Version 10 里我们手写了 JSON-RPC 协议：
- 自己解析 stdin
- 自己判断 method
- 自己返回 tools/list
- 自己处理 tools/call

Version 11 改成使用 MCP SDK：
- SDK 负责 MCP 协议细节
- 我们只负责定义工具函数
- 每个工具用 @mcp.tool() 注册

这样更接近真实工程中的 MCP Server 写法，也更方便后续扩展。
"""

# 启用更现代的类型注解行为。
from __future__ import annotations

# json 用于解析数据库中的 JSON 字段，也用于返回结构化数据。
import json

# asdict 用来把 dataclass 对象转成普通 dict，例如 FeedbackRules。
from dataclasses import asdict

# Any 表示任意类型，主要用于 sqlite3.Row 转换辅助函数。
from typing import Any

# run_daily_report 是完整日报 Agent 的主流程。
from ai_report_agent.agent import run_daily_report

# Settings 是配置对象，load_settings 用于读取 .env 和默认配置。
from ai_report_agent.config import Settings, load_settings

# connect 用于访问 SQLite，initialize_database 确保表结构存在。
from ai_report_agent.database import connect, initialize_database

# run_evaluation 用于生成离线评测报告。
from ai_report_agent.evaluation import run_evaluation

# load_feedback / save_feedback 用于读取和保存 feedback.json。
from ai_report_agent.feedback import load_feedback, save_feedback

# feedback_loop 中的函数用于保存事件反馈，并根据历史反馈更新偏好规则。
from ai_report_agent.feedback_loop import (
    build_feedback_rules_from_history,
    merge_feedback_rules,
    save_event_feedback,
)


# JsonDict 是一个小别名，让类型注解更易读。
JsonDict = dict[str, Any]


def run_mcp_server() -> None:
    """启动 MCP Server。

    注意：
    - 这里才导入 MCP SDK，而不是在文件顶部导入。
    - 这样做的好处是：如果你暂时没有安装 mcp 包，普通命令仍然能用。
    - 只有真正执行 `python catch_ai.py --mcp` 时，才需要 MCP SDK。
    """

    # 创建 FastMCP 应用对象。
    app = create_mcp_app(load_settings())

    # MCP SDK 会负责从 stdin 读取消息、向 stdout 写响应。
    # 新版本 SDK 支持 transport="stdio"；如果旧版本不接受该参数，就回退到 app.run()。
    try:
        app.run(transport="stdio")
    except TypeError:
        app.run()


def create_mcp_app(settings: Settings) -> Any:
    """创建并返回 MCP SDK 的 FastMCP 应用。

    参数：
    - settings：项目配置，包含数据库、目录、模型等路径。

    返回：
    - FastMCP 实例。这里返回 Any，是为了避免在没安装 mcp 包时影响静态编译。
    """

    # 只在创建 MCP 应用时导入 SDK。
    try:
        # FastMCP 是 MCP Python SDK 提供的高级封装。
        # 它会自动处理 initialize、tools/list、tools/call 等协议细节。
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        # 给出清晰的安装提示，而不是让用户看到一长串 import traceback。
        raise RuntimeError(
            "缺少 MCP Python SDK。请先运行：python -m pip install mcp"
        ) from exc

    # 确保数据库表存在；这样查询类工具可以直接使用。
    initialize_database(settings.database_path)

    # 创建 MCP Server 实例，名称会展示给 MCP 客户端。
    mcp = FastMCP("ai-report-agent")

    @mcp.tool()
    def generate_daily_report() -> JsonDict:
        """运行完整 AI 热点日报 Agent，并返回报告路径。"""

        # 这会真的执行采集、去重、聚类、LLM 调用、critic 等完整流程。
        report_path = run_daily_report(settings)

        # 返回结构化结果；MCP SDK 会把它序列化给客户端。
        return {
            "report_path": str(report_path),
            "message": "日报已生成。",
        }

    @mcp.tool()
    def evaluate_recent_runs(limit: int = 5) -> JsonDict:
        """评测最近若干次运行，并返回评测报告路径和 Markdown 内容。"""

        # run_evaluation 会读取 SQLite 和 trace，生成 data/eval 下的评测报告。
        report_path = run_evaluation(settings, limit=limit)

        # 同时返回路径和正文，方便外部 Agent 直接阅读。
        return {
            "eval_report_path": str(report_path),
            "markdown": report_path.read_text(encoding="utf-8"),
        }

    @mcp.tool()
    def list_recent_runs(limit: int = 5) -> JsonDict:
        """列出最近若干次 Agent 运行记录。"""

        # 连接 SQLite 查询 runs 表。
        with connect(settings.database_path) as connection:
            # 只查询摘要字段，避免一次返回太多内容。
            rows = connection.execute(
                """
                SELECT run_id, started_at, raw_item_count, unique_item_count,
                       selected_item_count, duplicate_count, report_path,
                       critic_result, updated_at
                FROM runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        # sqlite3.Row 不能直接 JSON 序列化，所以先转成普通 dict。
        return {
            "runs": [row_to_dict(row) for row in rows]
        }

    @mcp.tool()
    def get_run_details(run_id: str) -> JsonDict:
        """查询某次运行的详细决策轨迹、错误列表和最终事件。"""

        # 根据 run_id 查询 runs 表和 events 表。
        with connect(settings.database_path) as connection:
            # 查询运行主记录。
            run = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()

            # 如果 run_id 不存在，直接抛出清晰错误。
            if run is None:
                raise RuntimeError(f"找不到运行记录：{run_id}")

            # 查询这次运行生成的最终事件。
            events = connection.execute(
                """
                SELECT id, event_key, title, summary, sources_json,
                       categories_json, average_score, max_score,
                       item_count, representative_link, created_at
                FROM events
                WHERE run_id = ?
                ORDER BY max_score DESC, average_score DESC, id
                """,
                (run_id,),
            ).fetchall()

        # 转成普通 dict。
        run_payload = row_to_dict(run)

        # decisions_json 是数据库里的 JSON 字符串，这里还原成 list。
        run_payload["decisions"] = json.loads(run_payload.pop("decisions_json", "[]") or "[]")

        # errors_json 也是 JSON 字符串，这里还原成 list。
        run_payload["errors"] = json.loads(run_payload.pop("errors_json", "[]") or "[]")

        # 返回运行详情和事件列表。
        return {
            "run": run_payload,
            "events": [decode_event_row(row) for row in events],
        }

    @mcp.tool()
    def get_latest_report() -> JsonDict:
        """读取最近一份 Markdown 日报。"""

        # 从 reports 表中按创建时间倒序取最新一份报告。
        with connect(settings.database_path) as connection:
            row = connection.execute(
                """
                SELECT run_id, report_date, path, markdown, critic_result, created_at
                FROM reports
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()

        # 如果还没有报告，提示先生成日报。
        if row is None:
            raise RuntimeError("还没有日报记录，请先调用 generate_daily_report。")

        # 返回报告元数据和 Markdown 正文。
        return row_to_dict(row)

    @mcp.tool()
    def list_recent_events(limit: int = 10) -> JsonDict:
        """列出最近保存的事件级长期记忆。"""

        # 查询 events 表中最近的事件。
        with connect(settings.database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, run_id, event_key, title, summary, sources_json,
                       categories_json, average_score, max_score, item_count,
                       representative_link, created_at
                FROM events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        # 解码 sources_json/categories_json 后返回。
        return {
            "events": [decode_event_row(row) for row in rows]
        }

    @mcp.tool()
    def search_events(query: str, limit: int = 10) -> JsonDict:
        """按关键词搜索历史事件标题和摘要。"""

        # SQLite LIKE 查询使用 %keyword% 的形式。
        pattern = f"%{query}%"

        # 查询标题或摘要中包含关键词的事件。
        with connect(settings.database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, run_id, event_key, title, summary, sources_json,
                       categories_json, average_score, max_score, item_count,
                       representative_link, created_at
                FROM events
                WHERE title LIKE ? OR summary LIKE ?
                ORDER BY created_at DESC, max_score DESC
                LIMIT ?
                """,
                (pattern, pattern, limit),
            ).fetchall()

        # 返回查询词和命中的事件。
        return {
            "query": query,
            "events": [decode_event_row(row) for row in rows],
        }

    @mcp.tool()
    def get_run_trace(run_id: str) -> JsonDict:
        """读取某次运行的 trace JSON。"""

        # trace 文件默认保存在 data/traces/trace_<run_id>.json。
        trace_path = settings.raw_data_dir.parent / "traces" / f"trace_{run_id}.json"

        # 如果 trace 不存在，说明这次运行可能不是 version9+ 产生的，或文件被删除。
        if not trace_path.exists():
            raise RuntimeError(f"找不到 trace 文件：{trace_path}")

        # 返回 trace 路径和完整 JSON 内容。
        return {
            "trace_path": str(trace_path),
            "trace": json.loads(trace_path.read_text(encoding="utf-8")),
        }

    @mcp.tool()
    def submit_event_feedback(
        event_id: int,
        feedback_type: str,
        note: str = "",
    ) -> JsonDict:
        """给某个事件提交反馈，并刷新 feedback.json。"""

        # 限制反馈类型，避免写入脏数据。
        if feedback_type not in {"like", "dislike", "note"}:
            raise RuntimeError("feedback_type 只能是 like、dislike 或 note。")

        # 把反馈写入 SQLite 的 event_feedback 表。
        save_event_feedback(
            settings.database_path,
            event_id=event_id,
            feedback_type=feedback_type,
            note=note,
        )

        # 根据历史反馈重新生成动态偏好规则。
        dynamic_feedback = build_feedback_rules_from_history(settings.database_path)

        # 读取当前 feedback.json 中已有的手写或历史规则。
        file_feedback = load_feedback(settings.feedback_path)

        # 合并旧规则和新生成的动态规则。
        updated_feedback = merge_feedback_rules(file_feedback, dynamic_feedback)

        # 把合并后的偏好写回 feedback.json。
        save_feedback(settings.feedback_path, updated_feedback)

        # 返回反馈保存结果和更新后的偏好规则。
        return {
            "event_id": event_id,
            "feedback_type": feedback_type,
            "feedback_path": str(settings.feedback_path),
            "updated_feedback": asdict(updated_feedback),
        }

    # 返回注册好所有工具的 MCP 应用。
    return mcp


def row_to_dict(row: Any) -> JsonDict:
    """把 sqlite3.Row 转成普通 dict。

    sqlite3.Row 支持按列名访问，但它不是普通 JSON 对象。
    MCP 工具返回值最终需要可序列化，所以这里统一转换。
    """

    # row.keys() 会返回这一行包含的所有列名。
    return {key: row[key] for key in row.keys()}


def decode_event_row(row: Any) -> JsonDict:
    """把事件行里的 JSON 字段还原成 Python list。"""

    # 先把 sqlite3.Row 转成普通 dict。
    payload = row_to_dict(row)

    # sources_json 在数据库里是字符串，这里转换成 sources 列表。
    payload["sources"] = json.loads(payload.pop("sources_json", "[]") or "[]")

    # categories_json 同理，转换成 categories 列表。
    payload["categories"] = json.loads(payload.pop("categories_json", "[]") or "[]")

    # 返回解码后的事件对象。
    return payload
