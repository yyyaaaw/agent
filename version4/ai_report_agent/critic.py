"""报告自查模块。

这个模块让 agent 生成报告后再检查一遍。
如果报告偏离用户偏好、重复、太技术化或来源不足，它会要求 DeepSeek 修订。
"""

from __future__ import annotations

# re 用来更稳地识别“结论：FAIL/PASS”。
import re

from ai_report_agent.config import Settings

# call_deepseek 是统一的 DeepSeek API 调用函数。
from ai_report_agent.deepseek_client import call_deepseek

# UserProfile 提供用户偏好，用来构造检查和修订标准。
from ai_report_agent.profile import UserProfile


def build_critic_prompt(report: str, profile: UserProfile) -> str:
    """构造报告质量检查 prompt。"""
    # 使用 f-string 把用户偏好和待检查报告嵌入 prompt。
    # 这个 prompt 会要求模型明确输出 PASS 或 FAIL，便于程序自动判断。
    return f"""请你作为 AI 应用日报的质量检查员，检查下面这份日报。

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
    # 把原报告和自查意见一起交给模型，让它只基于已有材料修订。
    # “不新增没有来源支撑的事实”用于降低模型编造风险。
    return f"""请根据质量检查意见，修订下面的 AI 应用日报。

用户偏好：
{profile.report_style}

质量检查意见：
{critique}

修订要求：
1. 保留 Markdown 结构。
2. 更偏应用场景和实际影响。
3. 删除重复或弱相关内容。
4. 不新增没有来源支撑的事实。

原日报：
{report}
"""


def critique_report(settings: Settings, report: str, profile: UserProfile) -> str:
    """调用 DeepSeek 检查报告质量。"""
    # 先根据报告和用户偏好生成检查 prompt。
    prompt = build_critic_prompt(report, profile)

    # 再把 prompt 交给 DeepSeek，返回自查结果文本。
    return call_deepseek(settings, prompt, "critic_prompt")


def should_revise(critique: str) -> bool:
    """根据检查结论判断是否需要修订。"""
    # 统一转大写，便于匹配 PASS/FAIL。
    normalized = critique.upper()

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
