"""用户偏好模块。

Version 2 开始，agent 不再只按固定 prompt 工作，而是会读取你的偏好。

这个文件的作用：
1. 定义 UserProfile 数据结构。
2. 定义一份默认偏好 DEFAULT_PROFILE。
3. 从 profile.json 读取你的真实偏好。

可以把 profile.json 理解成这个 agent 的“用户画像”。
它会影响：
- 哪些资讯更容易进入 DeepSeek 分析
- DeepSeek 生成报告时采用什么风格
- 自查报告时按照什么标准判断好坏
"""

from __future__ import annotations

# json 用来读取 profile.json。
import json

# dataclass 用来快速定义“只负责存数据”的类。
from dataclasses import dataclass

# Path 用来表示文件路径。
from pathlib import Path


@dataclass(frozen=True)
class UserProfile:
    """描述用户阅读偏好的数据类。

    frozen=True 表示对象创建后不能被修改。
    这适合配置类数据，因为偏好在一次运行中应该保持稳定。
    """

    # 你感兴趣的方向。
    # list[str] 表示“字符串组成的列表”。
    interests: list[str]

    # 你不希望日报重点展开的方向。
    avoid: list[str]

    # 你更偏好的资讯来源类别。
    # 这些类别来自 sources.json 中每个来源的 category 字段。
    preferred_categories: list[str]

    # 你希望报告采用的写作风格。
    report_style: str

    # 你每天看日报时最想回答的问题。
    top_questions: list[str]


# 默认用户偏好。
# 如果 profile.json 不存在，agent 会使用这份默认配置。
DEFAULT_PROFILE = UserProfile(
    interests=["AI应用", "办公效率", "内容创作", "企业落地", "自动化工具"],
    avoid=["纯论文", "数学推导", "底层算法细节"],
    preferred_categories=["应用与产品", "应用与商业", "企业应用", "产品与模型"],
    report_style="通俗、实用、偏应用场景，说明对用户或业务的影响。",
    top_questions=["这个进展能不能直接用？", "它改变了什么工作流？"],
)


def load_profile(profile_path: Path) -> UserProfile:
    """从 profile.json 读取用户偏好；文件不存在时使用默认偏好。

    参数：
    - profile_path: profile.json 文件路径

    返回：
    - UserProfile 对象
    """
    # 如果 profile.json 不存在，就直接返回 DEFAULT_PROFILE。
    # 这样即使用户还没有配置偏好，程序也能运行。
    if not profile_path.exists():
        return DEFAULT_PROFILE

    # 读取 JSON 文件文本，再转成 Python 字典。
    data = json.loads(profile_path.read_text(encoding="utf-8"))

    # data.get("xxx", 默认值) 的意思是：
    # 如果 JSON 里有 xxx 字段，就使用它；
    # 如果没有，就使用默认配置里的对应字段。
    #
    # [str(item) for item in ...] 是列表推导式：
    # 它会把列表里的每个元素都转成字符串，避免 JSON 中出现非字符串导致后续拼接报错。
    return UserProfile(
        # interests 控制哪些主题会被加分。
        interests=[str(item) for item in data.get("interests", DEFAULT_PROFILE.interests)],

        # avoid 控制哪些主题会被降权。
        avoid=[str(item) for item in data.get("avoid", DEFAULT_PROFILE.avoid)],

        # preferred_categories 控制哪些来源类别更优先。
        preferred_categories=[
            str(item) for item in data.get("preferred_categories", DEFAULT_PROFILE.preferred_categories)
        ],

        # report_style 会写进 DeepSeek prompt，影响报告语气和侧重点。
        report_style=str(data.get("report_style", DEFAULT_PROFILE.report_style)),

        # top_questions 会写进 prompt，引导报告回答用户每天最关心的问题。
        top_questions=[str(item) for item in data.get("top_questions", DEFAULT_PROFILE.top_questions)],
    )
