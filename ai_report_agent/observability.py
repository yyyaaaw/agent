"""
此模块会为每次日常报告运行记录轻量级跟踪。

重要原因：
- 一个真实的代理不仅仅通过是否产生了答案来判断。
- 我们还需要知道哪些步骤执行了，这些步骤花了多长时间，消耗/产生了多少项目，以及哪里出现了故障。
- 这些跟踪使代理更易于调试、评估，并在面试中作为面向生产的系统进行描述。

该实现仅使用 Python 标准库，以便该项目可以轻松在本地运行。
"""

from __future__ import annotations

import json
import time
import traceback
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator


@dataclass
class TraceSpan:
    """测量步骤。

    跨度类似于围绕一个阶段的小型秒表，例如“collect_news”或“generate_report”。
    它存储时间、状态以及可选的指标，帮助我们了解该阶段内部发生的情况。
    """

    name: str
    started_at: str
    ended_at: str = ""
    duration_ms: float = 0.0
    status: str = "running"
    metrics: dict[str, int | float | str | bool] = field(default_factory=dict)
    error: str = ""


@dataclass
class AgentTrace:
    """一个agent运行的完整跟踪."""

    run_id: str
    started_at: str
    ended_at: str = ""
    duration_ms: float = 0.0
    spans: list[TraceSpan] = field(default_factory=list)
    metrics: dict[str, int | float | str | bool] = field(default_factory=dict)
    status: str = "running"


class TraceRecorder:
    """用于agent跟踪的小型过程内记录器。

    用法：
    trace = TraceRecorder("run_123")
    with trace.span("collect_news") as span:
    ...
    span.metrics["raw_items"] = 50
    trace.save(Path("data/traces"))

    这个记录器设计得很简单。对于一个简历项目来说，这已经足够展示可观测性思维，而无需引入庞大的跟踪系统。
    """

    def __init__(self, run_id: str) -> None:
        self.trace = AgentTrace(
            run_id=run_id,
            started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        self._started_monotonic = time.perf_counter()

    @contextmanager
    def span(self, name: str) -> Iterator[TraceSpan]:
        """Measure one named stage and capture failures automatically."""

        span = TraceSpan(
            name=name,
            started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        started = time.perf_counter()
        self.trace.spans.append(span)

        try:
            yield span
        except Exception as exc:
            span.status = "error"
            span.error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            raise
        else:
            span.status = "ok"
        finally:
            span.ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            span.duration_ms = round((time.perf_counter() - started) * 1000, 2)

    def set_metric(self, name: str, value: int | float | str | bool) -> None:
        """Attach a run-level metric."""

        self.trace.metrics[name] = value

    def finish(self, status: str = "ok") -> None:
        """Mark the trace as finished."""

        self.trace.status = status
        self.trace.ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.trace.duration_ms = round((time.perf_counter() - self._started_monotonic) * 1000, 2)

    def save(self, output_dir: Path) -> Path:
        """Write the trace as JSON and return the file path."""

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"trace_{self.trace.run_id}.json"
        output_path.write_text(
            json.dumps(asdict(self.trace), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return output_path


def trace_dir_from_data_path(raw_data_dir: Path) -> Path:
    """Return the default trace directory for the project.

    raw_data_dir is usually data/raw, so its parent is data.
    """

    return raw_data_dir.parent / "traces"
