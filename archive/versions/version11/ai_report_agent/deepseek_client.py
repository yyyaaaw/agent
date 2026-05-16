"""DeepSeek API 调用模块。

这个文件负责所有和 DeepSeek 有关的事情：
1. 把采集到的资讯整理成 prompt。
2. 按批次调用 DeepSeek，避免一次性材料太多导致超时。
3. 把多批结果再综合成最终日报。
4. 保存调试 prompt，方便你查看“模型看到了什么”。
"""

from __future__ import annotations

# json 用来把 Python 字典转换成 API 需要的 JSON 请求体。
import json

# socket 里有 timeout 错误类型，用来捕获网络读取超时。
import socket

# datetime 用来生成调试文件的时间戳。
from datetime import datetime

# urllib 是 Python 标准库里的 HTTP 请求工具。
import urllib.error
import urllib.request

# Settings 是我们自己定义的配置数据类。
from ai_report_agent.config import Settings

# UserProfile 保存你的阅读偏好，Version 2 会把它写进 prompt。
from ai_report_agent.profile import UserProfile

# NewsItem 是采集模块定义的资讯数据类。
from ai_report_agent.sources import NewsItem

# NewsEvent 是事件聚类后的结构。
from ai_report_agent.events import NewsEvent, format_events_for_prompt, rebuild_events_from_groups


# DeepSeek Chat Completions API 地址。
# 这个常量集中放在文件顶部，后续如果 API 地址变化，只改这里即可。
DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"


def chunk_items(items: list[NewsItem], batch_size: int) -> list[list[NewsItem]]:
    """把资讯条目切成多个批次，避免单次请求过大。

    例如：
    - items 有 56 条
    - batch_size 是 20
    - 返回结果就是 3 批：20 条、20 条、16 条
    """
    # 如果 batch_size <= 0，就不分批，直接把全部 items 放在一个批次里。
    if batch_size <= 0:
        return [items]

    # range(0, len(items), batch_size) 会生成 0、20、40 这样的起始下标。
    # items[index : index + batch_size] 是列表切片，取一批数据。
    # 外层 list[...] 表示返回“批次数组”，也就是 list[list[NewsItem]]。
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def format_items(items: list[NewsItem]) -> str:
    """把资讯条目格式化为 prompt 中的原始材料文本。

    DeepSeek 不能直接理解 Python 对象，所以要把 NewsItem 转成普通文本。
    """
    # 创建空列表，用来保存每条资讯格式化后的文本。
    lines = []

    # enumerate(items, start=1) 会同时给出序号和元素。
    # index 从 1 开始，item 是当前 NewsItem。
    for index, item in enumerate(items, start=1):
        # "\n".join([...]) 表示用换行符把多行文本拼成一个字符串。
        lines.append(
            "\n".join(
                [
                    f"{index}. [{item.source}｜{item.category}] {item.title}",
                    f"发布时间：{item.published or '未知'}",
                    f"链接：{item.link or '无'}",
                    f"摘要：{item.summary or '无'}",
                ]
            )
        )

    # 每条资讯之间用两个换行分隔，让 prompt 更容易读。
    return "\n\n".join(lines)


def format_profile(profile: UserProfile | None) -> str:
    """把用户偏好格式化成 prompt 文本。

    profile 可以是 None，这样保持兼容：即使没有 profile.json，也能继续运行。
    """
    # 如果没有传入偏好对象，就返回一段默认偏好说明。
    if profile is None:
        return "用户偏好：偏 AI 应用、产品和商业落地。"

    # 把用户偏好的多个字段整理成多行文本，方便写进 prompt。
    return "\n".join(
        [
            # 用户最关注的方向。
            f"关注方向：{', '.join(profile.interests)}",

            # 用户希望减少展开的内容。
            f"尽量少写：{', '.join(profile.avoid)}",

            # 用户偏好的资讯类别。
            f"偏好类别：{', '.join(profile.preferred_categories)}",

            # 用户希望的报告写作风格。
            f"报告风格：{profile.report_style}",

            # 用户每天希望通过日报回答的问题。
            f"核心问题：{'; '.join(profile.top_questions)}",
        ]
    )


def build_batch_prompt(
    items: list[NewsItem],
    batch_index: int,
    batch_count: int,
    profile: UserProfile | None,
) -> str:
    """构造单批资讯提炼 prompt。

    第一阶段不直接生成最终日报，而是让 DeepSeek 先从这一批里提炼候选热点。
    这样每次请求更短，也能覆盖所有资讯。
    """
    # f"""...""" 是多行 f-string。
    # 花括号里的 batch_index、batch_count、format_items(items) 会被替换成真实内容。
    return f"""你是一个专业的 AI 应用趋势研究助理。下面是第 {batch_index}/{batch_count} 批 AI 资讯。

用户偏好：
{format_profile(profile)}

请从这一批材料中提炼“值得进入日报候选池”的应用热点。

要求：
1. 优先关注新产品、新功能、工具、工作流、企业应用、创作者应用和商业落地。
2. 论文、算法、底层技术只在它们明显影响产品能力或应用场景时保留。
3. 最多输出 8 条候选热点。
4. 每条包含：标题、来源、发生了什么、应用影响、建议关注动作、原始链接。
5. 只基于给定材料，不要编造链接或事实。

原始材料：
{format_items(items)}
"""


def build_final_prompt(
    batch_summaries: list[str],
    profile: UserProfile | None,
    history_context: str = "",
    event_context: str = "",
) -> str:
    """构造最终日报 prompt。

    第二阶段会把每批候选热点交给 DeepSeek，让它综合成最终日报。
    history_context 是从数据库检索出的历史背景，用于第一阶段 RAG 增强。
    """
    # 这里用 enumerate 给每个批次摘要加编号。
    summaries = "\n\n".join(
        f"## 批次 {index}\n{summary}" for index, summary in enumerate(batch_summaries, start=1)
    )

    # 如果有历史上下文，就把它加入 prompt；否则提示模型只看本次材料。
    history_block = history_context or "暂无相关历史记录；请主要基于本次候选热点判断。"

    # 如果有事件上下文，就把它作为最终汇总的主要材料。
    event_block = event_context or "暂无事件聚类结果；请基于批次候选热点生成。"

    # 返回最终汇总 prompt。
    return f"""你是一个专业的 AI 应用趋势研究助理。请基于下面各批次候选热点，生成一份中文 AI 应用热点日报。

用户偏好：
{format_profile(profile)}

历史检索上下文：
{history_block}

本次事件聚类结果：
{event_block}

要求：
1. 优先关注“普通用户、职场、企业、创作者、开发者可以直接感知或使用的 AI 应用新变化”。
2. 论文、算法、底层技术只在它们明显会影响产品能力或应用场景时保留，最多占全文三分之一。
3. 先给出 5 条以内最值得关注的应用热点，并用通俗语言说明。
4. 按“新产品/新功能、典型应用场景、公司与商业动态、值得了解的技术进展、风险与监管”分类整理。
5. 每条热点说明：发生了什么、对普通用户或业务有什么影响、建议关注动作。
6. 最后给出“今日应用观察”和“明日可继续跟踪的问题”。
7. 优先基于“本次事件聚类结果”组织日报，避免重复报道同一事件。
8. 只基于给定材料，不要编造链接或事实；如果材料不足，请明确说明。

各批次候选热点：
{summaries}
"""


def save_debug_prompt(settings: Settings, name: str, prompt: str) -> None:
    """保存发送给 DeepSeek 的 prompt，便于人工检查分析输入。

    如果你想知道 DeepSeek 到底看到了什么，就去 data/debug 目录看这些文件。
    """
    # 如果 .env 里 SAVE_DEBUG_PROMPTS=false，就不保存调试 prompt。
    if not settings.save_debug_prompts:
        return

    # settings.raw_data_dir 默认是 data/raw。
    # parent 表示它的上一级 data。
    # 所以 debug_dir 默认就是 data/debug。
    debug_dir = settings.raw_data_dir.parent / "debug"

    # 确保 debug 目录存在。
    debug_dir.mkdir(parents=True, exist_ok=True)

    # 生成时间戳，避免文件重名。
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 拼出调试 prompt 文件路径，例如 data/debug/20260508_090000_batch_1_prompt.md。
    output_path = debug_dir / f"{timestamp}_{name}.md"

    # 写入 prompt 文本。
    output_path.write_text(prompt, encoding="utf-8")


def extract_message_text(result: dict) -> str:
    """从 DeepSeek 响应 JSON 中提取文本内容。

    普通模型通常返回 message.content。
    某些推理模型可能还会返回 message.reasoning_content。
    reasoning_content 是模型内部推理摘要，不应该混入日报正文。
    """
    # result 是 API 返回的 Python 字典。
    # choices[0] 表示取第一个回答。
    # ["message"] 是模型消息内容。
    message = result["choices"][0]["message"]

    # 这里只读取 content，也就是模型真正给用户看的回答。
    # 如果把 reasoning_content 拼进去，最终 Markdown 报告会混入“模型推理摘要”。
    content = message.get("content", "")

    # 返回清理首尾空白后的正式回答。
    return content.strip()


def call_deepseek(settings: Settings, prompt: str, debug_name: str) -> str:
    """调用 DeepSeek Chat Completions API 并返回模型文本。

    参数：
    - settings: 配置对象，里面包含 API Key、模型名、temperature 等
    - prompt: 要发给 DeepSeek 的用户提示词
    - debug_name: 保存调试 prompt 时使用的文件名标识
    """
    # 如果没有 API Key，就提前报错。
    # raise RuntimeError 表示主动抛出一个运行时错误。
    if not settings.deepseek_api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY，请先在 .env 中配置 DeepSeek API Key。")

    # payload 是要发送给 DeepSeek API 的请求体。
    # 它是一个 Python 字典，稍后会转换成 JSON。
    payload = {
        # 使用 .env 中配置的模型名，例如 deepseek-chat。
        "model": settings.deepseek_model,

        # messages 是 Chat Completions API 的核心字段。
        # system 表示给模型设定角色。
        # user 表示用户输入，也就是我们的 prompt。
        "messages": [
            {
                "role": "system",
                "content": "你擅长从杂乱资讯中提炼 AI 应用趋势，输出通俗、准确、可行动的中文汇报。",
            },
            {"role": "user", "content": prompt},
        ],

        # temperature 控制随机性，越低越稳定。
        "temperature": settings.deepseek_temperature,

        # max_tokens 控制模型这次最多输出多长。
        "max_tokens": settings.deepseek_max_tokens,
    }

    # 保存这次请求的 prompt，方便你查看模型输入。
    save_debug_prompt(settings, debug_name, prompt)

    # json.dumps 把 Python 字典转成 JSON 字符串。
    # encode("utf-8") 再把字符串转成字节，因为 HTTP 请求体需要 bytes。
    data = json.dumps(payload).encode("utf-8")

    # 构造 HTTP POST 请求。
    request = urllib.request.Request(
        DEEPSEEK_CHAT_URL,
        data=data,
        headers={
            # Authorization 是鉴权头，Bearer 后面跟 API Key。
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            # 告诉服务器我们发送的是 JSON。
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        # 发起请求。
        # timeout 如果是 120，就最多等 120 秒。
        # timeout 如果是 None，就不主动设置这个超时。
        with urllib.request.urlopen(request, timeout=settings.request_timeout) as response:
            # response.read() 读取返回内容。
            # decode("utf-8") 把字节转换成字符串。
            body = response.read().decode("utf-8")

    # HTTPError 表示服务器返回了 4xx/5xx 错误，比如 401、429、500。
    except urllib.error.HTTPError as exc:
        # 读取服务器返回的错误详情。
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API 请求失败：HTTP {exc.code} {error_body}") from exc

    # TimeoutError/socket.timeout 表示请求或读取响应超时。
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError(
            "DeepSeek API 响应超时。可以在 .env 中把 REQUEST_TIMEOUT 调大，"
            "或把 BATCH_SIZE 调小，例如 BATCH_SIZE=10。"
        ) from exc

    # URLError 通常表示网络问题，例如无法连接、DNS 失败等。
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DeepSeek API 网络请求失败：{exc}") from exc

    # DeepSeek 返回的是 JSON 字符串，这里转成 Python 字典。
    result = json.loads(body)

    # 从返回字典里提取模型回答文本。
    text = extract_message_text(result)

    # 如果配置允许，就把 DeepSeek 输出打印到终端。
    if settings.show_deepseek_output:
        print(text)

    # 返回模型回答文本，交给后续流程生成报告。
    return text


def build_event_refinement_prompt(events: list[NewsEvent]) -> str:
    """构造事件整合 prompt，让 LLM 合并粗聚类结果并重新命名事件。"""
    blocks: list[str] = []
    for event in events:
        item_lines = []
        for index, entry in enumerate(event.scored_items[:8], start=1):
            item_lines.append(
                "\n".join(
                    [
                        f"{index}. [{entry.item.source}｜{entry.item.category}] {entry.item.title}",
                        f"   摘要：{entry.item.summary[:220] or '无'}",
                        f"   链接：{entry.item.link or '无'}",
                    ]
                )
            )
        blocks.append(
            "\n".join(
                [
                    f"候选事件ID：{event.event_id}",
                    f"粗聚类标题：{event.title}",
                    f"来源：{', '.join(event.sources)}",
                    f"类别：{', '.join(event.categories)}",
                    "候选事件包含的新闻：",
                    *item_lines,
                ]
            )
        )

    event_material = "\n\n---\n\n".join(blocks)

    return f"""你是一个新闻编辑台的事件归并助手。下面是 embedding 粗聚类得到的候选事件。

请你判断哪些候选事件其实在讲同一个真实新闻事件，并把它们合并。
同时为每个合并后的事件重新生成一个中文事件标题，不要直接复制任何一条新闻标题。

判断标准：
1. 同一个公司/产品/政策/事故在同一时间段的同一进展，应合并为一个事件。
2. 官方发布、媒体跟进、案例报道、影响分析，只要核心事实相同，应合并。
3. 只是同一领域但主体或核心进展不同，不要合并。
4. 单条新闻也要保留为事件，但标题要概括“发生了什么”，不要照抄新闻标题。
5. 只基于给定材料，不要编造事实。

请只输出 JSON，不要输出 Markdown。格式：
{{
  "events": [
    {{
      "event_ids": ["event_1", "event_3"],
      "title": "概括后的中文事件标题",
      "summary": "1-2 句说明这个事件是什么，以及为什么这些新闻属于同一事件",
      "merge_reason": "简短说明合并依据；单事件可写：单独成事件"
    }}
  ]
}}

候选事件材料：
{event_material}
"""


def parse_event_refinement_json(text: str) -> list[dict]:
    """从 LLM 输出中解析事件整合 JSON。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        return []

    try:
        payload = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return []

    events = payload.get("events", [])
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def refine_events_with_llm(
    settings: Settings,
    events: list[NewsEvent],
) -> tuple[list[NewsEvent], list[str]]:
    """用 LLM 对 embedding 粗聚类事件做二次整合和重新命名。"""
    if not events:
        return [], ["LLM事件整合跳过：没有候选事件。"]

    prompt = build_event_refinement_prompt(events)
    response = call_deepseek(settings, prompt, "event_refinement_prompt")
    event_specs = parse_event_refinement_json(response)

    if not event_specs:
        return events, ["LLM事件整合未产出可解析 JSON，已保留 embedding 粗聚类结果。"]

    groups: list[tuple[list[str], str, str]] = []
    decision_lines = ["LLM事件整合完成：模型已重新合并候选事件并生成事件标题。"]

    for spec in event_specs:
        event_ids = spec.get("event_ids", [])
        if not isinstance(event_ids, list):
            continue

        normalized_event_ids = [str(event_id) for event_id in event_ids]
        title = str(spec.get("title", "")).strip()
        summary = str(spec.get("summary", "")).strip()
        reason = str(spec.get("merge_reason", "")).strip()
        groups.append((normalized_event_ids, title, summary))

        decision_lines.append(
            f"LLM事件整合：{title or '未命名事件'} <- {', '.join(normalized_event_ids)}"
            f"｜依据：{reason or '模型判断为同一事件或独立事件'}"
        )

    if not groups:
        return events, ["LLM事件整合结果为空，已保留 embedding 粗聚类结果。"]

    refined_events = rebuild_events_from_groups(groups, events)
    decision_lines.append(f"LLM事件整合结果：{len(events)} 个候选事件 -> {len(refined_events)} 个最终事件。")
    return refined_events, decision_lines


def analyze_news(
    settings: Settings,
    items: list[NewsItem],
    profile: UserProfile | None = None,
    history_context: str = "",
    events: list[NewsEvent] | None = None,
) -> str:
    """对新闻条目进行 AI 分析，生成日报正文。

    这里采用“两阶段分析”：
    1. 先把所有资讯分批，让 DeepSeek 每批提炼候选热点。
    2. 再把所有批次候选热点交给 DeepSeek，生成最终日报。
    3. Version 8 会把 LLM 整合后的事件结果和事件级历史上下文加入最终汇总 prompt。
    """
    # 按 settings.batch_size 分批。
    batches = chunk_items(items, settings.batch_size)

    # 保存每一批的分析结果。
    batch_summaries: list[str] = []

    # 逐批调用 DeepSeek。
    for index, batch in enumerate(batches, start=1):
        # len(batches) 是总批次数。
        # len(batch) 是当前批次的资讯条数。
        print(f"DeepSeek 正在分析第 {index}/{len(batches)} 批，共 {len(batch)} 条...")

        # 构造当前批次的 prompt。
        prompt = build_batch_prompt(batch, index, len(batches), profile)

        # 调用 DeepSeek，得到当前批次的候选热点摘要。
        summary = call_deepseek(settings, prompt, f"batch_{index}_prompt")

        # 保存这一批结果。
        batch_summaries.append(summary)

    # 所有批次分析完后，再做最终汇总。
    print("DeepSeek 正在综合所有批次，生成最终日报...")

    # 把事件列表格式化成最终汇总 prompt 的主要材料。
    event_context = format_events_for_prompt(events or [])

    # 构造最终汇总 prompt。
    final_prompt = build_final_prompt(batch_summaries, profile, history_context, event_context)

    # 返回最终日报正文。
    return call_deepseek(settings, final_prompt, "final_report_prompt")
