"""Command-line entry point for the AI report agent.

Common commands:
- Generate one report:
  python catch_ai.py --run-once

- Run a feedback session:
  python catch_ai.py --feedback

- Evaluate recent runs:
  python catch_ai.py --eval

- Keep the agent running on a daily schedule:
  python catch_ai.py --schedule 09:00
"""

from __future__ import annotations

import argparse

from ai_report_agent.agent import run_daily_report
from ai_report_agent.config import load_settings
from ai_report_agent.evaluation import run_evaluation
from ai_report_agent.feedback_loop import run_feedback_session
from ai_report_agent.scheduler import run_daily


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Collect AI news, generate a Markdown report, and evaluate agent quality."
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Generate one AI daily report immediately.",
    )
    parser.add_argument(
        "--schedule",
        metavar="HH:MM",
        help="Run daily at the given time, for example 09:00. Defaults to REPORT_TIME in .env.",
    )
    parser.add_argument(
        "--feedback",
        action="store_true",
        help="Give likes/dislikes/notes for the latest report events.",
    )
    parser.add_argument(
        "--eval",
        action="store_true",
        help="Evaluate recent runs and generate an offline evaluation report.",
    )
    parser.add_argument(
        "--eval-limit",
        type=int,
        default=5,
        help="How many recent runs to evaluate when using --eval.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the selected command."""

    args = parse_args()
    settings = load_settings()

    if args.feedback:
        run_feedback_session(settings.database_path, settings.feedback_path)
        return

    if args.eval:
        eval_path = run_evaluation(settings, limit=args.eval_limit)
        print(f"Evaluation report generated: {eval_path}")
        return

    if args.run_once:
        report_path = run_daily_report(settings)
        print(f"Daily report generated: {report_path}")
        return

    schedule_time = args.schedule or settings.report_time
    print(f"Agent started. It will generate a daily AI report at {schedule_time}. Press Ctrl+C to stop.")
    run_daily(schedule_time, lambda: run_daily_report(settings))


if __name__ == "__main__":
    main()
