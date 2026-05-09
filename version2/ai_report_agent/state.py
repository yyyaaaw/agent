"""运行状态模块。

Version 2 开始，agent 会记录一次运行中的关键决策。
这让它更像 agent：不仅输出结果，也留下“为什么这样处理”的轨迹。
"""

from __future__ import annotations

# json 用来把运行状态保存为 JSON 文件。
import json

# asdict 可以把 dataclass 对象转成字典。
# dataclass 用来定义状态数据类。
# field 用来给列表字段设置安全的默认值。
from dataclasses import asdict, dataclass, field

# datetime 用来生成本次运行的 ID 和开始时间。
from datetime import datetime

# Path 用来处理输出文件路径。
from pathlib import Path


@dataclass
class AgentRunState:
    """一次日报任务的运行状态。"""

    # 本次运行 ID，使用时间戳生成，便于和日志文件对应。
    run_id: str

    # 本次运行开始时间，方便人工阅读。
    started_at: str

    # 原始采集到的资讯条数。
    raw_item_count: int = 0

    # 去重后剩余的唯一资讯条数。
    unique_item_count: int = 0

    # 最终进入 DeepSeek 分析的资讯条数。
    selected_item_count: int = 0

    # 去重阶段跳过的重复资讯条数。
    duplicate_count: int = 0

    # decisions 记录 agent 每一步的重要决策。
    # default_factory=list 可以避免多个状态对象共用同一个列表。
    decisions: list[str] = field(default_factory=list)

    # errors 记录采集或处理中的非致命错误。
    errors: list[str] = field(default_factory=list)

    # 最终 Markdown 报告路径。
    report_path: str = ""

    # 原始采集 JSON 文件路径。
    raw_data_path: str = ""

    # 报告质量自查模型返回的结果。
    critic_result: str = ""


def create_run_state() -> AgentRunState:
    """创建本次运行状态对象。"""
    # 获取当前本地时间。
    now = datetime.now()

    # 创建状态对象，并用时间戳填入基础字段。
    return AgentRunState(
        run_id=now.strftime("%Y%m%d_%H%M%S"),
        started_at=now.strftime("%Y-%m-%d %H:%M:%S"),
    )


def save_run_state(state: AgentRunState, output_dir: Path) -> Path:
    """把运行状态保存成 JSON 文件。"""
    # 确保日志目录存在。
    output_dir.mkdir(parents=True, exist_ok=True)

    # 根据运行 ID 生成日志文件名。
    output_path = output_dir / f"run_state_{state.run_id}.json"

    # asdict(state) 把 dataclass 转成普通字典。
    # ensure_ascii=False 保留中文。
    # indent=2 让 JSON 更易读。
    output_path.write_text(
        json.dumps(asdict(state), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 返回实际写入的文件路径。
    return output_path
