"""
此模块会为每次日常报告运行记录轻量级跟踪。

重要原因：
- 一个真实的代理不仅仅通过是否产生了答案来判断。
- 我们还需要知道哪些步骤执行了，这些步骤花了多长时间，消耗/产生了多少项目，以及哪里出现了故障。
- 这些跟踪使代理更易于调试、评估，并在面试中作为面向生产的系统进行描述。

该实现仅使用 Python 标准库，以便该项目可以轻松在本地运行。
"""

from __future__ import annotations

# json 用来把 trace 结构写成可阅读的 JSON 文件。
import json

# time.perf_counter 提供高精度单调计时，适合计算耗时。
import time

# traceback 用于把异常类型和消息格式化进 span.error。
import traceback

# contextmanager 让 trace.span(...) 可以配合 with 使用。
from contextlib import contextmanager

# asdict 把 dataclass 递归转成 dict；dataclass/field 定义 trace 数据结构。
from dataclasses import asdict, dataclass, field

# datetime 用来记录人类可读的开始/结束时间。
from datetime import datetime

# Path 用来处理 trace 输出目录。
from pathlib import Path

# Iterator 是 contextmanager 返回值的类型注解。
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
    """一次 Agent 运行的完整跟踪。"""

    # 本次运行 ID，用来和 run_state、SQLite runs 表、报告文件对应。
    run_id: str

    # 整次运行开始时间。
    started_at: str

    # 整次运行结束时间。
    ended_at: str = ""

    # 整次运行耗时，单位毫秒。
    duration_ms: float = 0.0

    # 每个阶段的 span 列表。
    spans: list[TraceSpan] = field(default_factory=list)

    # run-level 指标，例如 raw_items、llm_total_tokens、actual_cost。
    metrics: dict[str, int | float | str | bool] = field(default_factory=dict)

    # ok/error/running。
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
        # 创建一条新的 run-level trace。
        self.trace = AgentTrace(
            run_id=run_id,
            started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        # perf_counter 用于计算耗时，不受系统时间调整影响。
        self._started_monotonic = time.perf_counter()

    @contextmanager
    def span(self, name: str) -> Iterator[TraceSpan]:
        """记录一个命名阶段的耗时，并自动捕获异常信息。"""

        # 进入 with 块前创建 span，并立即加入 trace.spans。
        span = TraceSpan(
            name=name,
            started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        started = time.perf_counter()
        self.trace.spans.append(span)

        try:
            # yield 把 span 暴露给调用方，调用方可以写 span.metrics["xxx"]。
            yield span
        except Exception as exc:
            # 如果 with 块里发生异常，标记 span 失败，并记录简短异常文本。
            span.status = "error"
            span.error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            raise
        else:
            # 没有异常则标记为 ok。
            span.status = "ok"
        finally:
            # 无论成功或失败，都记录结束时间和耗时。
            span.ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            span.duration_ms = round((time.perf_counter() - started) * 1000, 2)

    def set_metric(self, name: str, value: int | float | str | bool) -> None:
        """写入一个 run-level 指标。"""

        self.trace.metrics[name] = value

    def finish(self, status: str = "ok") -> None:
        """标记整次 trace 结束。"""

        # status 通常是 ok 或 error，由 agent.py 在成功/失败路径中设置。
        self.trace.status = status
        self.trace.ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.trace.duration_ms = round((time.perf_counter() - self._started_monotonic) * 1000, 2)

    def save(self, output_dir: Path) -> Path:
        """把 trace 写成 JSON 文件，并返回文件路径。"""

        # 确保 data/traces 目录存在。
        output_dir.mkdir(parents=True, exist_ok=True)

        # 文件名带 run_id，方便从 run_state 或数据库反查。
        output_path = output_dir / f"trace_{self.trace.run_id}.json"
        output_path.write_text(
            json.dumps(asdict(self.trace), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return output_path


def trace_dir_from_data_path(raw_data_dir: Path) -> Path:
    """返回项目默认 trace 目录。

    raw_data_dir 通常是 data/raw，因此它的 parent 是 data，
    trace 默认保存到 data/traces。
    """

    return raw_data_dir.parent / "traces"
