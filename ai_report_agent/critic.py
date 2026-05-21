"""报告自查模块。

这个模块让 agent 生成报告后再检查一遍。
如果报告偏离用户偏好、重复、太技术化或来源不足，它会要求 DeepSeek 修订。
如果出现日期错误等硬错误，它会直接触发修订，不管模型怎么说。
"""

from __future__ import annotations

# json 用来解析修订计划的结构化输出。
import json

# re 用来更稳地识别“结论：FAIL/PASS”和报告里的日期。
import re

# dataclass 用来表达报告区块和修订工作流结果。
from dataclasses import dataclass, field

# date 用来获取当天日期，并和报告标题、生成时间做硬性比对。
from datetime import date, datetime

from ai_report_agent.config import Settings

# call_deepseek 是统一的 DeepSeek API 调用函数。
from ai_report_agent.deepseek_client import call_deepseek

# UserProfile 提供用户偏好，用来构造检查和修订标准。
from ai_report_agent.profile import UserProfile


@dataclass(frozen=True)
class ReportSection:
    """Markdown 日报中的一个可修订区块。"""

    title: str
    content: str
    index: int


@dataclass(frozen=True)
class RevisionPlan:
    """结构化修订计划。"""

    global_instructions: list[str] = field(default_factory=list)
    section_instructions: dict[str, list[str]] = field(default_factory=dict)
    rejected_reason: str = ""

    @property
    def valid(self) -> bool:
        """计划是否包含可执行的区块修订。"""

        return not self.rejected_reason and bool(self.section_instructions)


@dataclass(frozen=True)
class RevisionWorkflowResult:
    """区块修订工作流结果。"""

    markdown: str
    plan_valid: bool
    plan_reason: str
    revised_sections: list[str] = field(default_factory=list)
    rejected_sections: list[str] = field(default_factory=list)


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
8. 必须输出完整修订后的 Markdown 日报，不要只输出“收到、正在整理、下面开始生成”等过渡语。
9. 如果无法完整修订，请直接原样返回原日报并只修正明显日期，不要输出半截内容。
10. 输出必须以一级标题 "# AI" 开头，并保留“今日摘要”“参考来源”“采集状态”等主要结构。

原日报：
{report}
"""


def build_revision_plan_prompt(report: str, critique: str, profile: UserProfile) -> str:
    """构造“先生成修订计划”的 prompt。"""

    today = date.today().strftime("%Y-%m-%d")
    section_titles = ", ".join(section.title for section in split_report_sections(report) if section.title != "__metadata__")

    return f"""请根据质量检查意见，为下面这份 AI 应用日报制定“局部修订计划”。

今天日期：{today}

用户偏好：
{profile.report_style}

可修订区块：
{section_titles or "未识别到二级标题区块"}

质量检查意见：
{critique}

计划要求：
1. 只输出 JSON，不要输出 Markdown 或解释文字。
2. 不要要求整篇重写；只能指定需要修改的区块。
3. “参考来源”“采集状态”默认保留，除非质量检查明确指出它们有问题。
4. 每个 section_title 必须来自“可修订区块”列表。
5. instructions 要具体说明要删除、补充、改写或核对什么。
6. 不允许新增没有来源支撑的事实。
7. 如果只有标题日期或生成时间错误，写入 global_instructions 即可，sections 可以为空。

JSON 格式：
{{
  "global_instructions": ["全局修订要求，例如修正日期、删掉无来源判断"],
  "sections": [
    {{
      "section_title": "今日摘要",
      "instructions": ["具体修订动作 1", "具体修订动作 2"]
    }}
  ]
}}

待修订日报：
{report}
"""


def build_section_revision_prompt(
    section: ReportSection,
    critique: str,
    global_instructions: list[str],
    section_instructions: list[str],
    profile: UserProfile,
) -> str:
    """构造单个区块的修订 prompt。"""

    today = date.today().strftime("%Y-%m-%d")

    return f"""请只修订下面这个 Markdown 区块，不要输出整篇日报。

今天日期：{today}

用户偏好：
{profile.report_style}

质量检查意见：
{critique}

全局修订要求：
{format_instruction_list(global_instructions)}

本区块修订要求：
{format_instruction_list(section_instructions)}

严格输出要求：
1. 只输出修订后的这个区块本身。
2. 必须保留原区块标题：## {section.title}
3. 不要输出一级标题，不要输出其他区块，不要输出“收到/我将/下面是”等过渡语。
4. 不新增没有来源支撑的事实。
5. 如果本区块无需改动，请原样返回本区块。

原区块：
{section.content}
"""


def format_instruction_list(instructions: list[str]) -> str:
    """把修订要求列表格式化为 prompt 文本。"""

    if not instructions:
        return "- 无"
    return "\n".join(f"- {instruction}" for instruction in instructions)


def validate_revision_report(original_report: str, revised_report: str) -> tuple[bool, str]:
    """校验修订版是否足够完整，避免短输出覆盖完整日报。

    本次异常报告的直接原因是：LLM 修订阶段只返回了 207 个字符，
    但程序没有判断它是否完整，就把原本 11809 个字符的完整报告覆盖了。
    因此这里增加一个“修订输出闸门”：太短、结构缺失、像中间话术的输出，
    都会被判定为无效修订，调用方应该保留原报告。
    """
    # 去掉首尾空白，避免换行和空格影响长度判断。
    revised = (revised_report or "").strip()
    original = (original_report or "").strip()

    # 空输出一定无效。
    if not revised:
        return False, "修订版为空。"

    # 修订版不应明显短于原报告。正常修订可以删减内容，
    # 但不应该从上万字符变成几百字符。
    min_length = max(800, int(len(original) * 0.45))
    if len(revised) < min_length:
        return False, f"修订版过短：{len(revised)} 字符，最低要求 {min_length} 字符。"

    # 完整日报应以 Markdown 标题开头。
    if not revised.lstrip().startswith("#"):
        return False, "修订版没有以 Markdown 一级标题开头。"

    # 完整日报至少应保留多个 Markdown 二级标题。
    # 这里不强依赖“参考来源/采集状态”等中文词，因为旧版本文件可能存在编码显示异常。
    section_count = len(re.findall(r"^##\s+", revised, flags=re.MULTILINE))
    if section_count < 3:
        return False, f"修订版二级标题过少：{section_count} 个，至少需要 3 个。"

    required_sections = ["## 今日摘要", "## 参考来源", "## 采集状态"]
    missing_sections = [section for section in required_sections if section not in revised]
    if missing_sections:
        return False, f"修订版缺少必要区块：{', '.join(missing_sections)}。"

    # 如果模型只返回“收到、正在生成”一类中间话术，不允许覆盖报告。
    transitional_phrases = ["收到", "现在将", "下面开始", "我将", "正在整理", "生成一份", "我会根据"]
    if len(revised) < 2000 and any(phrase in revised for phrase in transitional_phrases):
        return False, "修订版像模型过渡话术，而不是完整日报。"

    return True, "修订版通过完整性校验。"


def validate_section_revision(
    original_section: ReportSection,
    revised_section: str,
) -> tuple[bool, str]:
    """校验单区块修订，避免模型输出整篇报告或过短话术。"""

    revised = (revised_section or "").strip()
    original = original_section.content.strip()

    if not revised:
        return False, "区块修订为空。"

    if revised.lstrip().startswith("# "):
        return False, "区块修订返回了整篇日报一级标题。"

    expected_heading = f"## {original_section.title}"
    if not revised.lstrip().startswith(expected_heading):
        return False, f"区块修订没有保留标题：{expected_heading}。"

    min_length = max(80, int(len(original) * 0.35))
    if len(revised) < min_length:
        return False, f"区块修订过短：{len(revised)} 字符，最低要求 {min_length} 字符。"

    transitional_phrases = ["收到", "我将", "下面是", "下面开始", "正在整理", "我会根据"]
    if len(revised) < 500 and any(phrase in revised for phrase in transitional_phrases):
        return False, "区块修订像模型过渡话术。"

    return True, "区块修订通过校验。"


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


def repair_report_metadata(report: str, today: date | None = None) -> str:
    """用本地确定性规则修正日报标题日期和生成时间日期。"""

    today = today or date.today()
    today_text = today.isoformat()

    repaired = re.sub(
        r"^#\s*AI\s*热点日报\s*-\s*\d{4}-\d{2}-\d{2}",
        f"# AI 热点日报 - {today_text}",
        report,
        count=1,
        flags=re.MULTILINE,
    )
    repaired = re.sub(
        r"(生成时间\s*[:：]\s*)\d{4}-\d{2}-\d{2}",
        rf"\g<1>{today_text}",
        repaired,
        count=1,
    )
    return repaired


def split_report_sections(report: str) -> list[ReportSection]:
    """按二级标题拆分 Markdown 日报。"""

    matches = list(re.finditer(r"^##\s+(.+?)\s*$", report, flags=re.MULTILINE))
    sections: list[ReportSection] = []

    if not matches:
        return [ReportSection(title="__metadata__", content=report, index=0)]

    if matches[0].start() > 0:
        sections.append(
            ReportSection(
                title="__metadata__",
                content=report[: matches[0].start()].rstrip(),
                index=0,
            )
        )

    for index, match in enumerate(matches, start=1):
        end = matches[index].start() if index < len(matches) else len(report)
        sections.append(
            ReportSection(
                title=match.group(1).strip(),
                content=report[match.start() : end].strip(),
                index=index,
            )
        )

    return sections


def merge_report_sections(sections: list[ReportSection]) -> str:
    """把区块重新拼回完整 Markdown。"""

    return "\n\n".join(section.content.strip() for section in sections if section.content.strip()).strip() + "\n"


def parse_revision_plan_response(response: str, report: str) -> RevisionPlan:
    """解析并校验 LLM 生成的修订计划。"""

    payload = extract_json_object(response)
    if not payload:
        return RevisionPlan(rejected_reason="修订计划不是可解析 JSON。")

    sections = split_report_sections(report)
    valid_titles = {
        normalize_section_title(section.title): section.title
        for section in sections
        if section.title != "__metadata__"
    }

    section_instructions: dict[str, list[str]] = {}
    raw_sections = payload.get("sections", [])
    if isinstance(raw_sections, list):
        for raw_section in raw_sections:
            if not isinstance(raw_section, dict):
                continue
            raw_title = str(raw_section.get("section_title", "")).strip()
            title_key = normalize_section_title(raw_title)
            matched_title = valid_titles.get(title_key)
            if not matched_title:
                continue
            instructions = read_instruction_list(raw_section.get("instructions"))
            if instructions:
                section_instructions[matched_title] = instructions

    global_instructions = read_instruction_list(payload.get("global_instructions"))
    if not section_instructions and global_instructions:
        return RevisionPlan(
            global_instructions=global_instructions,
            section_instructions={},
            rejected_reason="修订计划只有全局要求，没有需要 LLM 局部改写的区块。",
        )

    if not section_instructions:
        return RevisionPlan(rejected_reason="修订计划没有可执行区块。")

    return RevisionPlan(
        global_instructions=global_instructions,
        section_instructions=section_instructions,
    )


def extract_json_object(text: str) -> dict[str, object]:
    """从模型输出里提取 JSON 对象。"""

    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        return {}

    try:
        payload = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return {}

    if not isinstance(payload, dict):
        return {}
    return payload


def read_instruction_list(value: object) -> list[str]:
    """读取修订要求列表。"""

    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def normalize_section_title(value: str) -> str:
    """归一化区块标题，便于匹配修订计划。"""

    return re.sub(r"\s+", "", value.strip().lower().strip("#：: "))


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
    return revise_report_with_plan(settings, report, critique, profile).markdown


def revise_report_with_plan(
    settings: Settings,
    report: str,
    critique: str,
    profile: UserProfile,
) -> RevisionWorkflowResult:
    """使用“修订计划 + 区块修订”的稳定修订链路。"""

    original_report = report
    repaired_report = repair_report_metadata(report)

    plan_prompt = build_revision_plan_prompt(repaired_report, critique, profile)
    plan_response = call_deepseek(settings, plan_prompt, "revision_plan_prompt")
    plan = parse_revision_plan_response(plan_response, repaired_report)

    if not plan.valid:
        return RevisionWorkflowResult(
            markdown=repaired_report,
            plan_valid=False,
            plan_reason=plan.rejected_reason or "修订计划无效。",
        )

    sections = split_report_sections(repaired_report)
    revised_sections: list[str] = []
    rejected_sections: list[str] = []
    updated_sections: list[ReportSection] = []

    for section in sections:
        instructions = plan.section_instructions.get(section.title)
        if not instructions:
            updated_sections.append(section)
            continue

        prompt = build_section_revision_prompt(
            section=section,
            critique=critique,
            global_instructions=plan.global_instructions,
            section_instructions=instructions,
            profile=profile,
        )
        debug_name = f"revision_section_{safe_debug_name(section.title)}_prompt"
        revised_content = call_deepseek(settings, prompt, debug_name)
        section_ok, section_reason = validate_section_revision(section, revised_content)
        if section_ok:
            updated_sections.append(
                ReportSection(
                    title=section.title,
                    content=revised_content.strip(),
                    index=section.index,
                )
            )
            revised_sections.append(section.title)
        else:
            updated_sections.append(section)
            rejected_sections.append(f"{section.title}: {section_reason}")

    merged_report = merge_report_sections(updated_sections)
    merged_report = repair_report_metadata(merged_report)

    # 如果所有区块修订都被拒绝，保留确定性元信息修复后的原报告。
    if not revised_sections:
        return RevisionWorkflowResult(
            markdown=repaired_report,
            plan_valid=False,
            plan_reason="所有区块修订都被本地校验拒绝。",
            revised_sections=revised_sections,
            rejected_sections=rejected_sections,
        )

    return RevisionWorkflowResult(
        markdown=merged_report,
        plan_valid=True,
        plan_reason="修订计划已执行。",
        revised_sections=revised_sections,
        rejected_sections=rejected_sections,
    )


def safe_debug_name(value: str) -> str:
    """把区块标题转换成适合调试文件名的短标识。"""

    cleaned = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "_", value).strip("_")
    return cleaned[:40] or "section"
