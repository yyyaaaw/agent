"""配置模块。

这个文件专门负责读取配置。
配置来源主要是项目根目录下的 `.env` 文件，例如 DeepSeek API Key、模型名、定时时间等。

把配置读取逻辑单独放在这里的好处：
1. 其他模块不用关心 .env 怎么读。
2. 所有配置项集中管理，后续新增配置更方便。
3. 代码更容易测试和维护。
"""

# 启用更现代的类型注解处理方式。
from __future__ import annotations

# os 是 Python 标准库，常用于读取环境变量、操作系统相关信息。
import os

# dataclass 可以快速创建“只用来存数据的类”。
# 下面的 Settings 就是一个配置数据类。
from dataclasses import dataclass

# Path 是 pathlib 模块里的路径类，比普通字符串路径更好用。
# 例如 Path("reports") / "a.md" 可以自动拼接路径。
from pathlib import Path


# __file__ 表示当前这个 config.py 文件的路径。
# Path(__file__).resolve() 得到当前文件的绝对路径。
# parent 表示上一级目录。
# config.py 在 ai_report_agent 目录里，所以 parent.parent 就是项目根目录 agent。
ROOT_DIR = Path(__file__).resolve().parent.parent

# @dataclass(frozen=True) 是 Python 里的一个“装饰器”写法，用来快速创建一个主要负责存数据的类。
'''@dataclass(frozen=True)
    class NewsSource:
        name: str
        url: str
        category: str = "应用与产品"
        enabled: bool = True
它大概等价于你手写：
    class NewsSource:
        def __init__(self, name, url, category="应用与产品", enabled=True): #__init__ 是创建类对象时初始化数据的方法
            self.name = name
            self.url = url
            self.category = category
            self.enabled = enabled
也就是说，@dataclass 会自动帮你生成初始化方法，所以你可以直接写.
frozen=True 表示这个对象创建后就不能再修改。
'''
@dataclass(frozen=True)
class Settings:
    """agent 运行所需配置。

    @dataclass 会自动帮我们生成 __init__ 等方法。
    frozen=True 表示这个对象创建后不能随意修改，避免运行中配置被误改。

    下面每一行都是一个字段：
    `字段名: 类型`
    例如 deepseek_model: str 表示 deepseek_model 应该是字符串。
    """

    # DeepSeek API Key，用来鉴权。
    deepseek_api_key: str

    # DeepSeek 模型名称，例如 deepseek-chat。
    deepseek_model: str

    # 每天定时运行的时间，例如 09:00。
    report_time: str

    # 报告输出目录，例如 reports。
    report_dir: Path

    # 原始采集数据输出目录，例如 data/raw。
    raw_data_dir: Path

    # 资讯源配置文件路径，例如 sources.json。
    sources_path: Path

    # 用户偏好文件路径，例如 profile.json。
    profile_path: Path

    # 用户反馈文件路径，例如 feedback.json。
    feedback_path: Path

    # 每次运行状态日志保存目录，例如 data/runs。
    run_log_dir: Path

    # SQLite 数据库文件路径，例如 data/agent_v5.sqlite3。
    database_path: Path

    # 每个 RSS 来源最多抓多少条。
    max_items_per_source: int

    # 最多选多少条资讯进入 DeepSeek 分析。
    max_analysis_items: int

    # 低于这个分数的资讯会被降级，优先不进入分析。
    min_item_score: int

    # 每批送给 DeepSeek 分析多少条资讯。
    batch_size: int

    # 请求超时时间。
    # int | None 表示可以是整数，也可以是 None。
    # None 表示不主动设置超时。
    request_timeout: int | None

    # DeepSeek temperature 参数，控制回答随机性。
    deepseek_temperature: float

    # DeepSeek 单次最大输出 token 数。
    deepseek_max_tokens: int

    # 是否把 DeepSeek 的输出打印到终端。
    show_deepseek_output: bool

    # 是否保存发送给 DeepSeek 的 prompt，方便调试。
    save_debug_prompts: bool


def load_dotenv(env_path: Path) -> None:
    """读取 .env 文件并写入环境变量。

    参数：
    - env_path: .env 文件路径

    返回：
    - None，表示这个函数只做事情，不返回结果。

    .env 文件格式示例：
    DEEPSEEK_MODEL=deepseek-chat
    REQUEST_TIMEOUT=120
    """
    # 如果 .env 文件不存在，就直接返回。
    # exists() 是 Path 对象的方法，用来判断路径是否存在。
    if not env_path.exists():
        return

    # read_text() 读取整个文件内容。
    # encoding="utf-8" 表示按 UTF-8 读取，适合中文。
    # splitlines() 会按行拆分成列表。
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        # strip() 去掉一行开头和结尾的空白字符。
        line = raw_line.strip()

        # 跳过空行、注释行，以及没有等号的非法行。
        # not line 表示 line 是空字符串。
        # line.startswith("#") 表示这一行以 # 开头，是注释。
        if not line or line.startswith("#") or "=" not in line:
            continue

        # split("=", 1) 表示只按第一个等号切分。
        # 这样即使 value 里也有等号，也不会被错误拆开。
        key, value = line.split("=", 1)

        # 清理 key 两边空格。
        key = key.strip()

        # 清理 value 两边空格，并去掉可能包裹的引号。
        value = value.strip().strip('"').strip("'")

        # os.environ 是当前程序的环境变量字典。
        # setdefault 的意思是：如果这个 key 还不存在，就设置；如果已经存在，就不覆盖。
        # 这样系统环境变量的优先级高于 .env 文件。
        os.environ.setdefault(key, value)


def getenv_int(name: str, default: int) -> int:
    """读取整数型环境变量，格式错误时回退到默认值。

    例如：
    MAX_ITEMS_PER_SOURCE=6 会被转换成整数 6。
    """
    # os.getenv(name) 从环境变量中读取 name 对应的值。
    # 如果没有这个变量，会返回 None。
    value = os.getenv(name)

    # 如果没配置，就使用默认值。
    if value is None:
        return default

    # try/except 用来捕获可能发生的错误。
    # int(value) 如果遇到 "abc" 这种无法转整数的字符串，会抛出 ValueError。
    try:
        return int(value)
    except ValueError:
        return default


def getenv_float(name: str, default: float) -> float:
    """读取浮点型环境变量，格式错误时回退到默认值。

    浮点数就是小数，例如 0.3。
    """
    # 从环境变量读取原始字符串。
    value = os.getenv(name)

    # 没有配置时使用默认值。
    if value is None:
        return default

    # 尝试把字符串转换成 float。
    try:
        return float(value)

    # 如果配置了非法内容，比如 abc，就回退到默认值。
    except ValueError:
        return default


def getenv_bool(name: str, default: bool) -> bool:
    """读取布尔型环境变量，支持 true/false、1/0、yes/no。

    布尔值只有两种：True 或 False。
    """
    # 从环境变量读取原始字符串。
    value = os.getenv(name)

    # 没有配置时使用默认布尔值。
    if value is None:
        return default

    # lower() 转成小写，方便兼容 TRUE、True、true。
    # `in {...}` 判断某个值是否在集合里。
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def getenv_timeout(name: str, default: int | None) -> int | None:
    """读取超时时间；如果配置为空或 none，则表示一直等待。

    返回类型是 int | None：
    - int：例如 120，表示最多等待 120 秒。
    - None：表示不主动设置超时。
    """
    # 从环境变量读取原始超时配置。
    value = os.getenv(name)

    # 没有配置时直接使用默认值。
    if value is None:
        return default

    # normalized 是清理后的配置值。
    normalized = value.strip().lower()

    # 这些写法都表示“不设置超时”。
    if normalized in {"", "none", "null", "0"}:
        return None

    # 尝试把超时配置转换为整数秒数。
    try:
        return int(normalized)

    # 格式错误时回退到默认值。
    except ValueError:
        return default


def load_settings() -> Settings:
    """加载所有配置，并确保输出目录存在。

    这是配置模块最核心的函数。
    其他地方通常只需要调用它一次，然后拿到 Settings 对象。
    """
    # 先读取项目根目录下的 .env，把里面的键值放进 os.environ。
    load_dotenv(ROOT_DIR / ".env")

    # os.getenv("REPORT_DIR", "reports") 的意思是：
    # 如果配置了 REPORT_DIR，就用配置值；否则默认用 reports。
    # ROOT_DIR / xxx 会把项目根目录和子路径拼起来。
    report_dir = ROOT_DIR / os.getenv("REPORT_DIR", "reports")

    # 原始数据目录，默认是 data/raw。
    raw_data_dir = ROOT_DIR / os.getenv("RAW_DATA_DIR", "data/raw")

    # 运行状态日志目录，默认是 data/runs。
    run_log_dir = ROOT_DIR / os.getenv("RUN_LOG_DIR", "data/runs")

    # SQLite 数据库路径，默认放在 data 目录下。
    database_path = ROOT_DIR / os.getenv("DATABASE_PATH", "data/agent_v5.sqlite3")

    # mkdir 用来创建目录。
    # parents=True 表示父目录不存在时也一起创建。
    # exist_ok=True 表示目录已存在时不要报错。
    report_dir.mkdir(parents=True, exist_ok=True)
    raw_data_dir.mkdir(parents=True, exist_ok=True)
    run_log_dir.mkdir(parents=True, exist_ok=True)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    # 创建并返回 Settings 对象。
    # 这里集中定义每个配置项的默认值。
    return Settings(
        # DeepSeek API Key，默认为空；为空时调用模型会主动报错。
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),

        # DeepSeek 模型名，默认使用 deepseek-chat。
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),

        # 每日定时运行时间，默认上午 09:00。
        report_time=os.getenv("REPORT_TIME", "09:00"),

        # Markdown 报告输出目录。
        report_dir=report_dir,

        # 原始采集 JSON 输出目录。
        raw_data_dir=raw_data_dir,

        # RSS 来源配置文件路径。
        sources_path=ROOT_DIR / os.getenv("SOURCES_FILE", "sources.json"),

        # 用户偏好配置文件路径。
        profile_path=ROOT_DIR / os.getenv("PROFILE_FILE", "profile.json"),

        # 用户反馈配置文件路径。
        feedback_path=ROOT_DIR / os.getenv("FEEDBACK_FILE", "feedback.json"),

        # 运行状态日志目录。
        run_log_dir=run_log_dir,

        # SQLite 数据库文件路径。
        database_path=database_path,

        # 每个来源最多采集的资讯条数。
        max_items_per_source=getenv_int("MAX_ITEMS_PER_SOURCE", 8),

        # 最多送入 DeepSeek 分析的资讯条数。
        max_analysis_items=getenv_int("MAX_ANALYSIS_ITEMS", 40),

        # 资讯入选 DeepSeek 分析的最低分数。
        min_item_score=getenv_int("MIN_ITEM_SCORE", 2),

        # 每批 DeepSeek 请求包含的资讯条数。
        batch_size=getenv_int("BATCH_SIZE", 20),

        # RSS 和 API 请求超时时间。
        request_timeout=getenv_timeout("REQUEST_TIMEOUT", 120),

        # DeepSeek 输出随机性参数。
        deepseek_temperature=getenv_float("DEEPSEEK_TEMPERATURE", 0.3),

        # DeepSeek 单次最大输出 token 数。
        deepseek_max_tokens=getenv_int("DEEPSEEK_MAX_TOKENS", 4096),

        # 是否在终端显示 DeepSeek 输出。
        show_deepseek_output=getenv_bool("SHOW_DEEPSEEK_OUTPUT", True),

        # 是否保存 prompt 调试文件。
        save_debug_prompts=getenv_bool("SAVE_DEBUG_PROMPTS", True),
    )
