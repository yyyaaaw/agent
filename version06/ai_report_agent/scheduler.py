"""定时调度模块。

这个文件提供 Python 内置的“常驻定时运行”能力。

注意：
如果你已经使用 Windows 任务计划程序每天运行 `python catch_ai.py --run-once`，
那么这个文件在你的日常使用里基本用不上。

它主要支持这种模式：
python catch_ai.py --schedule 09:00

这种模式需要终端进程一直开着。
"""

from __future__ import annotations

# time.sleep 用来让程序暂停等待一段时间。
import time

# datetime 表示具体时间点。
# timedelta 表示时间差，例如 1 天、300 秒。
from datetime import datetime, timedelta

# Path 用在类型注解中，表示任务可能返回一个文件路径。
from pathlib import Path

# Callable 表示“可调用对象”，通常就是函数。
from typing import Callable


def parse_hhmm(value: str) -> tuple[int, int]:
    """解析 HH:MM 格式的每日运行时间。

    例如：
    - 输入 "09:30"
    - 返回 (9, 30)

    tuple[int, int] 表示返回一个包含两个整数的元组。
    """
    try:
        # split(":", 1) 按第一个冒号拆分字符串。
        # "09:30" 会拆成 "09" 和 "30"。
        hour_text, minute_text = value.split(":", 1)

        # int(...) 把字符串转换成整数。
        hour = int(hour_text)
        minute = int(minute_text)

    # 如果格式不对，例如 "abc"，split 或 int 会抛出 ValueError。
    except ValueError as exc:
        # from exc 表示保留原始异常信息，方便调试。
        raise ValueError("定时时间必须是 HH:MM 格式，例如 09:00") from exc

    # 校验小时和分钟是否在合理范围内。
    # `not 0 <= hour <= 23` 是 Python 支持的链式比较。
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("定时时间超出范围，小时应为 0-23，分钟应为 0-59")

    # 返回小时和分钟。
    return hour, minute


def seconds_until_next_run(schedule_time: str) -> float:
    """计算距离下一次运行还剩多少秒。

    比如现在是 08:50，schedule_time 是 09:00，
    返回值大约是 600 秒。
    """
    # 先把 "09:00" 解析成 hour=9、minute=0。
    hour, minute = parse_hhmm(schedule_time)

    # 获取当前时间。
    now = datetime.now()

    # replace 会基于当前日期，替换小时、分钟、秒、微秒。
    # 例如今天 08:50 -> 今天 09:00。
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # 如果目标时间已经过去，例如现在 10:00，目标是今天 09:00，
    # 那就把目标时间改成明天 09:00。
    if target <= now:
        target += timedelta(days=1)

    # target - now 得到一个 timedelta。
    # total_seconds() 把时间差转换成秒数。
    return (target - now).total_seconds()


def run_daily(schedule_time: str, job: Callable[[], Path | None]) -> None:
    """每天在指定时间运行传入的任务函数。

    参数：
    - schedule_time: 每天运行时间，例如 "09:00"
    - job: 到点后要执行的函数

    Callable[[], Path | None] 的意思是：
    job 是一个函数；
    它不需要参数；
    它可能返回 Path，也可能返回 None。
    """
    # 先解析一次时间，如果格式不对，可以立刻报错。
    parse_hhmm(schedule_time)

    # while True 表示无限循环。
    # 这个函数会一直运行，直到用户按 Ctrl+C 或进程被关闭。
    while True:
        # 计算距离下一次运行还有多少秒。
        wait_seconds = seconds_until_next_run(schedule_time)

        # 计算下一次运行的具体时间，用于打印提示。
        next_time = datetime.now() + timedelta(seconds=wait_seconds)
        print(f"下一次运行时间：{next_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # 暂停等待，直到到达运行时间。
        time.sleep(wait_seconds)

        try:
            # 到点后执行传入的任务函数。
            output = job()

            # 打印任务输出，通常是报告文件路径。
            print(f"任务完成：{output}")

        # 捕获任务中的所有异常，避免一次失败导致定时程序退出。
        except Exception as exc:
            print(f"任务失败：{exc}")
