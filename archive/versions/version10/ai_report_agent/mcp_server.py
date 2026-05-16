"""Lightweight stdio MCP server for the AI report agent.

Version 10 turns the local report agent into a tool server that other agents
can call.  This file implements the small subset of MCP that we need:

- initialize
- tools/list
- tools/call

It intentionally avoids external dependencies.  The server reads JSON-RPC
messages from stdin and writes JSON-RPC responses to stdout.  Human logs go to
stderr so they do not corrupt the protocol stream.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from ai_report_agent.agent import run_daily_report
from ai_report_agent.config import Settings, load_settings
from ai_report_agent.database import connect, initialize_database
from ai_report_agent.evaluation import evaluate_single_run, latest_run_ids, run_evaluation
from ai_report_agent.feedback import load_feedback, save_feedback
from ai_report_agent.feedback_loop import (
    build_feedback_rules_from_history,
    merge_feedback_rules,
    save_event_feedback,
)


JsonDict = dict[str, Any]


def run_mcp_server() -> None:
    """Start the stdio MCP server loop."""

    server = AgentMCPServer(load_settings())
    server.log("AI report MCP server started.")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
            response = server.handle_message(request)
        except Exception as exc:
            response = json_rpc_error(None, -32603, f"Internal server error: {exc}")

        if response is not None:
            write_json(response)


class AgentMCPServer:
    """MCP tool server that exposes the local AI report agent."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        initialize_database(self.settings.database_path)
        self.tool_handlers: dict[str, Callable[[JsonDict], JsonDict]] = {
            "generate_daily_report": self.tool_generate_daily_report,
            "evaluate_recent_runs": self.tool_evaluate_recent_runs,
            "list_recent_runs": self.tool_list_recent_runs,
            "get_run_details": self.tool_get_run_details,
            "get_latest_report": self.tool_get_latest_report,
            "list_recent_events": self.tool_list_recent_events,
            "search_events": self.tool_search_events,
            "get_run_trace": self.tool_get_run_trace,
            "submit_event_feedback": self.tool_submit_event_feedback,
        }

    def handle_message(self, request: JsonDict) -> JsonDict | None:
        """Handle one JSON-RPC request or notification."""

        method = request.get("method")
        request_id = request.get("id")

        if method == "initialize":
            return json_rpc_result(request_id, self.initialize_result())

        if method == "notifications/initialized":
            return None

        if method == "tools/list":
            return json_rpc_result(request_id, {"tools": self.tools()})

        if method == "tools/call":
            params = request.get("params") or {}
            name = str(params.get("name", ""))
            arguments = params.get("arguments") or {}
            return json_rpc_result(request_id, self.call_tool(name, arguments))

        return json_rpc_error(request_id, -32601, f"Unknown method: {method}")

    def initialize_result(self) -> JsonDict:
        """Return MCP initialize metadata."""

        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "ai-report-agent",
                "version": "10.0.0",
            },
        }

    def tools(self) -> list[JsonDict]:
        """Describe tools exposed by this MCP server."""

        return [
            {
                "name": "generate_daily_report",
                "description": "Run the full AI trend report agent once and return the generated report path.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
            {
                "name": "evaluate_recent_runs",
                "description": "Generate an offline evaluation report for recent agent runs.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Number of recent runs to evaluate.",
                            "default": 5,
                        }
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "list_recent_runs",
                "description": "List recent run metadata from SQLite.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 5}
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_run_details",
                "description": "Return run decisions, errors, and events for one run_id.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"}
                    },
                    "required": ["run_id"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_latest_report",
                "description": "Return the latest saved Markdown report.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
            {
                "name": "list_recent_events",
                "description": "List recent event-level memory records.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 10}
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "search_events",
                "description": "Search historical events by keyword in title or summary.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_run_trace",
                "description": "Return the observability trace JSON for one run_id.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"}
                    },
                    "required": ["run_id"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "submit_event_feedback",
                "description": "Submit like/dislike/note feedback for an event and refresh feedback.json.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "integer"},
                        "feedback_type": {
                            "type": "string",
                            "enum": ["like", "dislike", "note"],
                        },
                        "note": {"type": "string", "default": ""},
                    },
                    "required": ["event_id", "feedback_type"],
                    "additionalProperties": False,
                },
            },
        ]

    def call_tool(self, name: str, arguments: JsonDict) -> JsonDict:
        """Call one registered tool and format the result for MCP."""

        handler = self.tool_handlers.get(name)
        if handler is None:
            return mcp_text(f"Unknown tool: {name}", is_error=True)

        try:
            payload = handler(arguments)
            return mcp_json(payload)
        except Exception as exc:
            return mcp_text(f"Tool {name} failed: {exc}", is_error=True)

    def tool_generate_daily_report(self, arguments: JsonDict) -> JsonDict:
        """Run the daily report workflow once."""

        report_path = run_daily_report(self.settings)
        return {
            "report_path": str(report_path),
            "message": "Daily report generated successfully.",
        }

    def tool_evaluate_recent_runs(self, arguments: JsonDict) -> JsonDict:
        """Generate an evaluation report and return its path and content."""

        limit = int(arguments.get("limit", 5))
        report_path = run_evaluation(self.settings, limit=limit)
        return {
            "eval_report_path": str(report_path),
            "markdown": report_path.read_text(encoding="utf-8"),
        }

    def tool_list_recent_runs(self, arguments: JsonDict) -> JsonDict:
        """List recent run rows."""

        limit = int(arguments.get("limit", 5))
        with connect(self.settings.database_path) as connection:
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

        return {
            "runs": [row_to_dict(row) for row in rows]
        }

    def tool_get_run_details(self, arguments: JsonDict) -> JsonDict:
        """Return detailed run state plus event rows."""

        run_id = require_string(arguments, "run_id")
        with connect(self.settings.database_path) as connection:
            run = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise RuntimeError(f"Run not found: {run_id}")

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

        run_payload = row_to_dict(run)
        run_payload["decisions"] = json.loads(run_payload.pop("decisions_json", "[]") or "[]")
        run_payload["errors"] = json.loads(run_payload.pop("errors_json", "[]") or "[]")
        return {
            "run": run_payload,
            "events": [decode_event_row(row) for row in events],
        }

    def tool_get_latest_report(self, arguments: JsonDict) -> JsonDict:
        """Return the newest report markdown stored in SQLite."""

        with connect(self.settings.database_path) as connection:
            row = connection.execute(
                """
                SELECT run_id, report_date, path, markdown, critic_result, created_at
                FROM reports
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()

        if row is None:
            raise RuntimeError("No reports found. Run generate_daily_report first.")

        return row_to_dict(row)

    def tool_list_recent_events(self, arguments: JsonDict) -> JsonDict:
        """List recent events from long-term memory."""

        limit = int(arguments.get("limit", 10))
        with connect(self.settings.database_path) as connection:
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

        return {
            "events": [decode_event_row(row) for row in rows]
        }

    def tool_search_events(self, arguments: JsonDict) -> JsonDict:
        """Search events by title or summary keyword."""

        query = require_string(arguments, "query")
        limit = int(arguments.get("limit", 10))
        pattern = f"%{query}%"

        with connect(self.settings.database_path) as connection:
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

        return {
            "query": query,
            "events": [decode_event_row(row) for row in rows],
        }

    def tool_get_run_trace(self, arguments: JsonDict) -> JsonDict:
        """Read a trace JSON file for one run."""

        run_id = require_string(arguments, "run_id")
        trace_path = self.settings.raw_data_dir.parent / "traces" / f"trace_{run_id}.json"
        if not trace_path.exists():
            raise RuntimeError(f"Trace file not found: {trace_path}")

        return {
            "trace_path": str(trace_path),
            "trace": json.loads(trace_path.read_text(encoding="utf-8")),
        }

    def tool_submit_event_feedback(self, arguments: JsonDict) -> JsonDict:
        """Save event feedback and refresh feedback.json."""

        event_id = int(arguments["event_id"])
        feedback_type = require_string(arguments, "feedback_type")
        note = str(arguments.get("note", ""))

        if feedback_type not in {"like", "dislike", "note"}:
            raise RuntimeError("feedback_type must be one of: like, dislike, note")

        save_event_feedback(
            self.settings.database_path,
            event_id=event_id,
            feedback_type=feedback_type,
            note=note,
        )

        dynamic_feedback = build_feedback_rules_from_history(self.settings.database_path)
        file_feedback = load_feedback(self.settings.feedback_path)
        updated_feedback = merge_feedback_rules(file_feedback, dynamic_feedback)
        save_feedback(self.settings.feedback_path, updated_feedback)

        return {
            "event_id": event_id,
            "feedback_type": feedback_type,
            "feedback_path": str(self.settings.feedback_path),
            "updated_feedback": asdict(updated_feedback),
        }

    def log(self, message: str) -> None:
        """Write human-readable logs to stderr."""

        print(message, file=sys.stderr, flush=True)


def row_to_dict(row: Any) -> JsonDict:
    """Convert a sqlite3.Row to a normal JSON-serializable dict."""

    return {key: row[key] for key in row.keys()}


def decode_event_row(row: Any) -> JsonDict:
    """Decode JSON columns from an event row."""

    payload = row_to_dict(row)
    payload["sources"] = json.loads(payload.pop("sources_json", "[]") or "[]")
    payload["categories"] = json.loads(payload.pop("categories_json", "[]") or "[]")
    return payload


def require_string(arguments: JsonDict, name: str) -> str:
    """Read a required string argument."""

    value = arguments.get(name)
    if value is None or str(value).strip() == "":
        raise RuntimeError(f"Missing required argument: {name}")
    return str(value)


def mcp_json(payload: JsonDict) -> JsonDict:
    """Return a JSON payload as MCP text content."""

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ],
        "isError": False,
    }


def mcp_text(text: str, is_error: bool = False) -> JsonDict:
    """Return plain text MCP content."""

    return {
        "content": [
            {
                "type": "text",
                "text": text,
            }
        ],
        "isError": is_error,
    }


def json_rpc_result(request_id: Any, result: JsonDict) -> JsonDict:
    """Build a JSON-RPC success response."""

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def json_rpc_error(request_id: Any, code: int, message: str) -> JsonDict:
    """Build a JSON-RPC error response."""

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def write_json(payload: JsonDict) -> None:
    """Write one JSON-RPC message to stdout."""

    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
