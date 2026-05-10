"""AI 热点日报 agent 的命令行入口。

这个文件是整个程序最先被执行的地方。
你在终端里运行 `python catch_ai.py --run-once` 时，Python 会从这里开始执行。

运行方式：
- 立即生成一次日报：python catch_ai.py --run-once
- 常驻并每天定时生成：python catch_ai.py --schedule 09:00
- 如果不加参数：python catch_ai.py，会读取 .env 里的 REPORT_TIME 并常驻等待。
"""

# __future__ 是 Python 的“未来特性”模块。
# annotations 表示让类型注解延迟解析，写复杂类型注解时更稳。
from __future__ import annotations

# argparse 是 Python 标准库，用来解析命令行参数。
# 比如识别用户有没有输入 --run-once 或 --schedule 09:00。
import argparse

# 从 agent.py 中导入 run_daily_report 函数。
# 它负责真正执行“采集 -> 分析 -> 生成报告”的完整流程。
from ai_report_agent.agent import run_daily_report

# 从 config.py 中导入 load_settings 函数。
# 它负责读取 .env 里的配置，并整理成 Settings 对象。
from ai_report_agent.config import load_settings

# 从 feedback_loop.py 导入交互式反馈入口。
from ai_report_agent.feedback_loop import run_feedback_session

# 从 scheduler.py 中导入 run_daily 函数。
# 它负责让程序常驻，并每天在指定时间执行一次任务。
from ai_report_agent.scheduler import run_daily


def parse_args() -> argparse.Namespace:
    """解析命令行参数，决定立即执行还是进入每日定时模式。

    `-> argparse.Namespace` 是类型注解，表示这个函数会返回 argparse.Namespace 对象。
    Namespace 可以理解成“装着命令行参数结果的小对象”。
    """
    # 创建一个命令行参数解析器。
    # description 会显示在 `python catch_ai.py --help` 的帮助信息里。
    parser = argparse.ArgumentParser(description="每天定时收集 AI 热点并生成 Markdown 汇报")

    # 添加 --run-once 参数。
    # action="store_true" 表示：如果用户写了 --run-once，则 args.run_once 为 True；
    # 如果用户没写，则 args.run_once 为 False。
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="立即收集热点并生成一份日报",
    )

    # 添加 --schedule 参数。
    # metavar="HH:MM" 只是帮助信息里的占位显示，例如 --schedule HH:MM。
    # 用户实际可以输入：python catch_ai.py --schedule 09:00。
    parser.add_argument(
        "--schedule",
        metavar="HH:MM",
        help="每天在指定时间运行，例如 09:00。不填写时使用 .env 中的 REPORT_TIME",
    )

    # 添加 --feedback 参数。
    # 用户运行这个命令后，可以对最近一次日报事件进行点赞、点踩和备注。
    parser.add_argument(
        "--feedback",
        action="store_true",
        help="对最近一次日报事件进行交互式反馈",
    )

    # parse_args() 会读取终端里输入的参数，并返回解析结果。
    return parser.parse_args()


def main() -> None:
    """程序主入口。

    `-> None` 表示这个函数不返回有意义的值，只负责执行流程。
    """
    # 解析命令行参数，例如 --run-once、--schedule。
    args = parse_args()

    # 读取 .env 配置，得到 Settings 对象。
    # 后续模块会从 settings 中拿 API Key、模型名、报告目录等配置。
    settings = load_settings()

    # 如果用户输入 --feedback，就进入反馈交互，不生成日报。
    if args.feedback:
        run_feedback_session(settings.database_path, settings.feedback_path)
        return

    # 如果用户输入了 --run-once，就立即生成一次日报。
    if args.run_once:
        # run_daily_report 会返回生成的 Markdown 报告路径。
        report_path = run_daily_report(settings)

        # f-string 是 Python 的格式化字符串写法。
        # 花括号里的 report_path 会被替换成变量的真实值。
        print(f"日报已生成：{report_path}")

        # return 表示结束 main 函数，后面的定时逻辑不再执行。
        return

    # 如果用户没有使用 --run-once，就进入定时模式。
    # `args.schedule or settings.report_time` 的意思是：
    # 优先使用命令行传入的时间；如果没有传入，就使用 .env 里的 REPORT_TIME。
    schedule_time = args.schedule or settings.report_time

    # 打印提示，让用户知道程序正在常驻等待。
    print(f"agent 已启动，将在每天 {schedule_time} 生成 AI 热点日报。按 Ctrl+C 停止。")

    # run_daily 需要两个参数：
    # 1. 每天运行的时间，例如 "09:00"
    # 2. 到时间后要执行的函数
    #
    # lambda 是一个小型匿名函数。
    # 这里 lambda: run_daily_report(settings) 的意思是：
    # “等 scheduler 到点后，再调用 run_daily_report(settings)”。
    run_daily(schedule_time, lambda: run_daily_report(settings))


# 这是 Python 常见入口判断。
# 当你直接运行 `python catch_ai.py` 时，__name__ 会等于 "__main__"，于是执行 main()。
# 如果这个文件被别的文件 import，则不会自动执行 main()。
if __name__ == "__main__":
    main()
