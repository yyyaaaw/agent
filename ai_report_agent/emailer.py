"""日报邮件发送模块。

这个模块只负责一件事：在日报 Markdown 已经生成后，把报告内容通过 SMTP
发送到 `.env` 配置的邮箱。它不参与采集、LLM 分析或报告生成主流程。
"""

from __future__ import annotations

import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from ai_report_agent.config import Settings


def validate_email_settings(settings: Settings) -> None:
    """检查启用邮件发送时必须提供的 SMTP 配置。"""

    missing_fields: list[str] = []
    if not settings.email_smtp_host:
        missing_fields.append("EMAIL_SMTP_HOST")
    if not settings.email_from:
        missing_fields.append("EMAIL_FROM")
    if not settings.email_to:
        missing_fields.append("EMAIL_TO")

    if missing_fields:
        raise RuntimeError(
            "邮件发送配置不完整，请在 .env 中配置："
            + ", ".join(missing_fields)
        )


def build_report_email(
    settings: Settings,
    report_path: Path,
    markdown: str,
) -> EmailMessage:
    """把日报 Markdown 组装成一封邮件。"""

    today = datetime.now().strftime("%Y-%m-%d")
    subject_prefix = settings.email_subject_prefix or "AI 热点日报"

    message = EmailMessage()
    message["Subject"] = f"{subject_prefix} - {today}"
    message["From"] = settings.email_from
    message["To"] = ", ".join(settings.email_to)

    # 让正文直接显示日报内容，同时附上一份 Markdown 文件方便保存。
    message.set_content(markdown)
    message.add_attachment(
        markdown,
        subtype="markdown",
        filename=report_path.name,
    )
    return message


def send_report_email(settings: Settings, report_path: Path) -> None:
    """按配置把日报发送到邮箱。

    EMAIL_ENABLED=false 时只打印跳过信息，不访问外部网络。
    EMAIL_ENABLED=true 时，如果 SMTP 配置不完整或发送失败，会抛出异常，
    让 CLI / 调度器明确知道“日报已生成但邮件发送失败”。
    """

    if not settings.email_enabled:
        print("Email sending skipped: EMAIL_ENABLED is false.")
        return

    validate_email_settings(settings)

    markdown = report_path.read_text(encoding="utf-8")
    message = build_report_email(settings, report_path, markdown)

    smtp_kwargs: dict[str, Any] = {
        "host": settings.email_smtp_host,
        "port": settings.email_smtp_port,
    }
    if settings.email_timeout is not None:
        smtp_kwargs["timeout"] = settings.email_timeout

    smtp_class = smtplib.SMTP_SSL if settings.email_use_ssl else smtplib.SMTP
    with smtp_class(**smtp_kwargs) as smtp:
        if settings.email_use_tls and not settings.email_use_ssl:
            smtp.starttls()
        if settings.email_smtp_username:
            smtp.login(settings.email_smtp_username, settings.email_smtp_password)
        smtp.send_message(message)

    print(f"Daily report email sent to: {', '.join(settings.email_to)}")
