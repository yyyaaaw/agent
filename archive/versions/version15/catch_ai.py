"""AI 日报 Agent 的命令行入口。

这个文件相当于项目的“总开关”：用户在终端输入不同参数时，
这里负责把请求分发到对应模块。

常用命令：
- 立即生成一份日报：
  python catch_ai.py --run-once

- 进入交互式反馈：
  python catch_ai.py --feedback

- 评估最近几次运行：
  python catch_ai.py --eval

- 运行固定回归用例：
  python catch_ai.py --eval-regression

- 常驻进程，每天定时生成：
  python catch_ai.py --schedule 09:00

- 启动 MCP Server：
  python catch_ai.py --mcp
"""

from __future__ import annotations

# argparse 是 Python 标准库的命令行参数解析工具。
import argparse

# run_daily_report 是完整日报生成主流程。
from ai_report_agent.agent import run_daily_report

# load_settings 会读取 .env 和默认配置，得到 Settings 对象。
from ai_report_agent.config import load_settings

# run_evaluation 读取 SQLite / trace，生成离线评估报告。
from ai_report_agent.evaluation import run_evaluation

# run_feedback_session 提供命令行点赞、点踩和备注反馈。
from ai_report_agent.feedback_loop import run_feedback_session

# run_mcp_server 把本项目暴露为 MCP 工具服务。
from ai_report_agent.mcp_server import run_mcp_server

# run_regression_evaluation 运行固定输入的确定性回归检查。
from ai_report_agent.regression_eval import run_regression_evaluation

# run_daily 提供常驻定时调度能力。
from ai_report_agent.scheduler import run_daily


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    返回 argparse.Namespace，里面会包含每个开关的布尔值或参数值。
    例如用户输入 `--run-once` 时，args.run_once 会是 True。
    """

    # 创建参数解析器，description 会显示在 `python catch_ai.py --help` 中。
    parser = argparse.ArgumentParser(
        description="Collect AI news, generate a Markdown report, and evaluate agent quality."
    )

    # store_true 表示：只要命令行出现这个开关，对应字段就是 True。
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Generate one AI daily report immediately.",
    )

    # schedule 后面需要跟一个 HH:MM 字符串，例如 --schedule 09:00。
    parser.add_argument(
        "--schedule",
        metavar="HH:MM",
        help="Run daily at the given time, for example 09:00. Defaults to REPORT_TIME in .env.",
    )

    # 交互式反馈不会调用 LLM，只会读写 SQLite 和 feedback.json。
    parser.add_argument(
        "--feedback",
        action="store_true",
        help="Give likes/dislikes/notes for the latest report events.",
    )

    # 离线评估读取已有运行记录，不会生成新日报。
    parser.add_argument(
        "--eval",
        action="store_true",
        help="Evaluate recent runs and generate an offline evaluation report.",
    )

    # eval-limit 只在 --eval 开启时生效，用来限制读取最近多少次运行。
    parser.add_argument(
        "--eval-limit",
        type=int,
        default=5,
        help="How many recent runs to evaluate when using --eval.",
    )

    # 回归评估使用 evals/regression_cases.json 中的固定样例。
    parser.add_argument(
        "--eval-regression",
        action="store_true",
        help="Run fixed regression cases for deterministic agent behavior checks.",
    )

    # MCP 模式会长期占用 stdin/stdout 和客户端通信。
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Start a stdio MCP server exposing the agent as tools.",
    )

    # 统一返回解析结果，main() 再根据优先级执行。
    return parser.parse_args()


def main() -> None:
    """根据命令行参数执行对应功能。"""

    # 先解析用户输入的命令行参数。
    args = parse_args()

    # MCP 模式最特殊：它需要保持标准输入输出给 MCP 协议使用，
    # 因此优先处理，并且不额外加载日报运行流程。
    if args.mcp:
        run_mcp_server()
        return

    # 其他模式都需要项目配置，例如数据库路径、报告目录、API 配置等。
    settings = load_settings()

    # 反馈模式：读取最近事件，让用户输入喜欢/不喜欢，再更新 feedback.json。
    if args.feedback:
        run_feedback_session(settings.database_path, settings.feedback_path)
        return

    # 离线评估模式：只分析已有运行记录，不采集 RSS，也不调用 LLM。
    if args.eval:
        eval_path = run_evaluation(settings, limit=args.eval_limit)
        print(f"Evaluation report generated: {eval_path}")
        return

    # 回归评估模式：用固定样例检查去重、评分、critic、事件词典等核心规则。
    if args.eval_regression:
        regression_path = run_regression_evaluation(settings)
        print(f"Regression evaluation report generated: {regression_path}")
        return

    # 立即运行一次完整日报流程。
    if args.run_once:
        report_path = run_daily_report(settings)
        print(f"Daily report generated: {report_path}")
        return

    # 如果没有指定 --run-once 等一次性命令，就进入常驻定时模式。
    # args.schedule 优先级高于 .env 中的 REPORT_TIME。
    schedule_time = args.schedule or settings.report_time
    print(f"Agent started. It will generate a daily AI report at {schedule_time}. Press Ctrl+C to stop.")

    # lambda 把带 settings 参数的 run_daily_report 包装成一个无参数函数，
    # 以满足 scheduler.run_daily 的 Callable[[], Path | None] 类型要求。
    run_daily(schedule_time, lambda: run_daily_report(settings))


# 只有直接执行 `python catch_ai.py` 时才运行 main()。
# 如果这个文件被其他模块 import，则不会自动启动 Agent。
if __name__ == "__main__":
    main()
