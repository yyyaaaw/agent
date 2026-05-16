"""报告自查模块。

这个模块让 agent 生成报告后再检查一遍。
如果报告偏离用户偏好、重复、太技术化或来源不足，它会要求 DeepSeek 修订。
如果出现日期错误等硬错误，它会直接触发修订，不管模型怎么说。
"""

from __future__ import annotations

# re 用来更稳地识别“结论：FAIL/PASS”和报告里的日期。
import re

# date 用来获取当天日期，并和报告标题、生成时间做硬性比对。
from datetime import date, datetime

from ai_report_agent.config import Settings

# call_deepseek 是统一的 DeepSeek API 调用函数。
from ai_report_agent.deepseek_client import call_deepseek

# UserProfile 提供用户偏好，用来构造检查和修订标准。
from ai_report_agent.profile import UserProfile


def build_critic_prompt(report: str, profile: UserProfile) -> str:
    """构造报告质量检查 prompt。"""
    # 当前日期是 critic 判断“今天/昨日/未来日期”的基准。
    today = date.today().strftime("%Y-%m-%d")

    # 使用 f-string 把用户偏好和待检查报告嵌入 prompt。
    # 这个 prompt 会要求模型明确输出 PASS 或 FAIL，便于程序自动判断。
    return f"""请你作为 AI 应用日报的质量检查员，检查下面这份日报。

今天日期：{today}

用户偏好：
- 关注：{', '.join(profile.interests)}
- 不想重点看：{', '.join(profile.avoid)}
- 风格：{profile.report_style}

检查标准：
1. 是否明显偏 AI 应用，而不是偏论文或底层技术？
2. 是否有重复热点？
3. 是否每个关键热点都说明了应用影响？
4. 是否有明确的关注建议？
5. 是否存在看起来像编造的事实或没有来源支撑的判断？
6. 日期、年份、相对时间是否正确？报告标题日期、生成时间、“今天/昨日/本周”等说法必须和今天日期一致。
7. 是否把历史 RAG 内容、旧新闻或未来日期误写成今天热点？

硬性判定规则：
- 只要发现日期错误、年份错误、未来日期误用、相对时间错误，结论必须是 FAIL。
- 只要发现报告标题日期或生成时间与今天日期不一致，结论必须是 FAIL。
- 只要发现事实无法从参考来源支撑，结论必须是 FAIL。

请用以下格式输出：
结论：PASS 或 FAIL
主要问题：
- ...
修改建议：
- ...

待检查日报：
{report}
"""


def build_revision_prompt(report: str, critique: str, profile: UserProfile) -> str:
    """构造报告修订 prompt。"""
    # 当前日期用于修订阶段校正标题、生成时间和相对时间表达。
    today = date.today().strftime("%Y-%m-%d")

    # 把原报告和自查意见一起交给模型，让它只基于已有材料修订。
    # “不新增没有来源支撑的事实”用于降低模型编造风险。
    return f"""请根据质量检查意见，修订下面的 AI 应用日报。

今天日期：{today}

用户偏好：
{profile.report_style}

质量检查意见：
{critique}

修订要求：
1. 保留 Markdown 结构。
2. 更偏应用场景和实际影响。
3. 删除重复或弱相关内容。
4. 不新增没有来源支撑的事实。
5. 修正所有日期、年份、相对时间错误。
6. 报告标题日期必须是 {today}。
7. 如果某条内容来自历史 RAG，只能作为趋势延续背景，不能写成今天新发生的新闻。

原日报：
{report}
"""


def local_critic_issues(report: str, today: date | None = None) -> list[str]:
    """用本地规则检查 LLM 容易放过的硬错误。"""
    # 默认使用当前日期。
    today = today or date.today()

    # 存放所有硬性问题。
    issues: list[str] = []

    # 检查标题中的日报日期，例如 "# AI 热点日报 - 2026-05-10"。
    title_match = re.search(r"^#\s*AI\s*热点日报\s*-\s*(\d{4}-\d{2}-\d{2})", report, re.MULTILINE)
    if title_match:
        title_date = parse_iso_date(title_match.group(1))
        if title_date and title_date != today:
            issues.append(
                f"报告标题日期是 {title_date.isoformat()}，但今天日期是 {today.isoformat()}。"
            )

    # 检查生成时间中的日期，例如 "生成时间：2026-05-10 09:00:00"。
    generated_match = re.search(r"生成时间\s*[:：]\s*(\d{4}-\d{2}-\d{2})", report)
    if generated_match:
        generated_date = parse_iso_date(generated_match.group(1))
        if generated_date and generated_date != today:
            issues.append(
                f"生成时间日期是 {generated_date.isoformat()}，但今天日期是 {today.isoformat()}。"
            )

    # 扫描报告正文中的 ISO 日期，发现未来日期时标为硬风险。
    # 这里允许明天以内的日期，因为新闻中可能提到即将发布/明日活动。
    for raw_date in sorted(set(re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", report))):
        parsed = parse_iso_date(raw_date)
        if parsed and (parsed - today).days > 1:
            issues.append(f"报告中出现明显未来日期 {raw_date}，需要核对是否误写。")

    # 当前日报不应该包含很旧的标题日期或生成时间；如果没有匹配到元信息，也提示修复。
    if not title_match:
        issues.append("没有找到标准报告标题日期，无法确认日报日期是否正确。")
    if not generated_match:
        issues.append("没有找到生成时间，无法确认报告时间是否正确。")

    # 返回硬性问题列表。
    return issues


def parse_iso_date(value: str) -> date | None:
    """把 YYYY-MM-DD 字符串转成 date，失败时返回 None。"""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def format_local_critique(issues: list[str]) -> str:
    """把本地硬性检查结果格式化成 critic 文本。"""
    # 没有问题时返回空字符串，避免影响 LLM 自查结果。
    if not issues:
        return ""

    # 本地硬性检查命中时，第一行直接输出 FAIL，确保 should_revise 能识别。
    issue_lines = "\n".join(f"- [本地硬性检查] {issue}" for issue in issues)
    return f"""结论：FAIL
主要问题：
{issue_lines}
修改建议：
- 先修正上述日期/时间硬错误，再检查内容质量。
"""


def critique_report(settings: Settings, report: str, profile: UserProfile) -> str:
    """调用 DeepSeek 检查报告质量。"""
    # 先运行本地硬性检查，弥补 LLM 可能漏判的日期问题。
    local_critique = format_local_critique(local_critic_issues(report))

    # 先根据报告和用户偏好生成检查 prompt。
    prompt = build_critic_prompt(report, profile)

    # 再把 prompt 交给 DeepSeek，返回自查结果文本。
    llm_critique = call_deepseek(settings, prompt, "critic_prompt")

    # 如果本地检查发现硬错误，就把 FAIL 放在最前面。
    if local_critique:
        return f"{local_critique}\nLLM 检查结果：\n{llm_critique}"

    # 没有本地硬错误时，直接返回 LLM 检查结果。
    return llm_critique


def should_revise(critique: str) -> bool:
    """根据检查结论判断是否需要修订。"""
    # 统一转大写，便于匹配 PASS/FAIL。
    normalized = critique.upper()

    # 如果模型虽然写了 PASS，但正文提到了严重日期问题，也触发修订。
    # 这类问题属于硬错误，优先级高于模型自己的 PASS/FAIL 结论。
    date_error_patterns = [
        "日期错误",
        "年份错误",
        "时间错误",
        "未来日期",
        "相对时间错误",
        "日期不一致",
        "生成时间不一致",
        "标题日期不一致",
    ]
    date_error_negations = [
        "无日期错误",
        "没有日期错误",
        "未发现日期错误",
        "不存在日期错误",
        "日期无误",
    ]
    has_date_error = any(pattern in critique for pattern in date_error_patterns)
    has_date_error_negation = any(pattern in critique for pattern in date_error_negations)
    if has_date_error and not has_date_error_negation:
        return True

    # 优先查找类似“结论：FAIL”的明确结论。
    conclusion_match = re.search(r"结论\s*[:：]\s*(PASS|FAIL)", normalized)

    # 如果找到了明确结论，就只根据结论判断。
    if conclusion_match:
        return conclusion_match.group(1) == "FAIL"

    # 如果模型没有按格式输出，则保守地在全文中查找 FAIL。
    return "FAIL" in normalized


def revise_report(settings: Settings, report: str, critique: str, profile: UserProfile) -> str:
    """调用 DeepSeek 根据检查意见修订报告。"""
    # 根据原报告、自查意见和用户偏好构造修订 prompt。
    prompt = build_revision_prompt(report, critique, profile)

    # 调用 DeepSeek 返回修订后的 Markdown 报告。
    return call_deepseek(settings, prompt, "revision_prompt")
