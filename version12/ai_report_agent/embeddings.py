"""Embedding 模块。

Version 5 把 Version 4 的“哈希 embedding”升级为本地 BGE-M3 embedding。

推荐配置：
EMBEDDING_PROVIDER=bge
EMBEDDING_MODEL_PATH=E:\\Agent_zr\\embedding_model\\bge-m3

BGE-M3 会把文本转换成真正的语义向量。
相比哈希 embedding，它能更好理解：
- 中英文混合内容
- 同义表达
- 语义相近但关键词不完全相同的新闻

为了保证项目在没有安装模型时仍便于调试，本文件也保留 hash fallback。
但正式使用 Version 5 时，建议使用 bge。
"""

from __future__ import annotations

# hashlib 用于 hash fallback。
import hashlib

# json 不在本文件直接写库，但保留清晰的标准库边界。
import math

# os 用来读取 .env 写入的环境变量。
import os

# re 用来做 hash fallback 的简单分词。
import re

# lru_cache 用来缓存本地 BGE 模型，避免每条新闻都重新加载一次模型。
from functools import lru_cache

# Path 用来处理本地模型路径。
from pathlib import Path


# hash fallback 的默认向量维度。
DEFAULT_HASH_EMBEDDING_DIMENSION = 128

# BGE-M3 dense embedding 的维度通常是 1024。
BGE_M3_EMBEDDING_DIMENSION = 1024


def getenv_bool(name: str, default: bool) -> bool:
    """读取布尔环境变量。"""
    # 读取环境变量原始值。
    value = os.getenv(name)

    # 没有配置时使用默认值。
    if value is None:
        return default

    # 支持常见 true 写法。
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def getenv_int(name: str, default: int) -> int:
    """读取整数环境变量。"""
    # 读取环境变量原始值。
    value = os.getenv(name)

    # 没有配置时使用默认值。
    if value is None:
        return default

    # 尝试转换为整数。
    try:
        return int(value)
    except ValueError:
        return default


def embedding_provider() -> str:
    """读取当前 embedding 提供商。"""
    # 默认使用 bge，因为 Version 5 的目标就是本地 BGE-M3。
    return os.getenv("EMBEDDING_PROVIDER", "bge").strip().lower()


def bge_model_path() -> str:
    """读取 BGE 模型路径。"""
    # 默认使用用户指定的 E 盘模型目录。
    return os.getenv("EMBEDDING_MODEL_PATH", r"E:\Agent_zr\embedding_model\bge-m3").strip()


def bge_use_fp16() -> bool:
    """读取 BGE 是否使用 fp16。"""
    # CPU 下一般用 fp32 更稳，所以默认 false。
    return getenv_bool("EMBEDDING_USE_FP16", False)


def embedding_batch_size() -> int:
    """读取 embedding 批大小。"""
    return getenv_int("EMBEDDING_BATCH_SIZE", 8)


def embedding_max_length() -> int:
    """读取 embedding 最大输入长度。"""
    return getenv_int("EMBEDDING_MAX_LENGTH", 512)


def fallback_to_hash() -> bool:
    """读取 BGE 加载失败时是否回退到 hash embedding。"""
    # 默认不回退，避免用户以为自己在用 BGE，实际却悄悄用了 hash。
    return getenv_bool("EMBEDDING_FALLBACK_TO_HASH", False)


@lru_cache(maxsize=1)
def load_bge_model():
    """懒加载 BGE-M3 模型。

    第一次调用时加载模型，后续调用复用同一个模型对象。
    """
    # 延迟导入 FlagEmbedding，只有 provider=bge 时才需要这个依赖。
    try:
        from FlagEmbedding import BGEM3FlagModel
    except ImportError as exc:
        raise RuntimeError(
            "缺少 FlagEmbedding。请先运行：python -m pip install -U FlagEmbedding"
        ) from exc

    # 读取模型路径。
    model_path = bge_model_path()

    # 明确检查路径是否存在，错误信息比底层异常更容易理解。
    if not Path(model_path).exists():
        raise RuntimeError(f"BGE 模型路径不存在：{model_path}")

    # 加载本地 BGE-M3 模型。
    return BGEM3FlagModel(model_path, use_fp16=bge_use_fp16())


def embed_text(text: str) -> list[float]:
    """把文本转换成 embedding 向量。"""
    # 根据配置决定使用 BGE 还是 hash。
    provider = embedding_provider()

    # 正式路径：使用本地 BGE-M3。
    if provider == "bge":
        try:
            return embed_text_with_bge(text)
        except Exception:
            # 如果用户明确允许 fallback，就退回 hash，方便临时调试。
            if fallback_to_hash():
                return embed_text_with_hash(text)
            raise

    # 调试路径：继续支持 hash。
    if provider == "hash":
        return embed_text_with_hash(text)

    # 未知 provider 直接报错。
    raise RuntimeError(f"未知 EMBEDDING_PROVIDER：{provider}")


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量把文本转换成 embedding 向量。"""
    # 空列表直接返回空列表。
    if not texts:
        return []

    # 根据配置决定使用 BGE 还是 hash。
    provider = embedding_provider()

    # BGE 支持批量编码，批量处理比逐条更快。
    if provider == "bge":
        try:
            return embed_texts_with_bge(texts)
        except Exception:
            if fallback_to_hash():
                return [embed_text_with_hash(text) for text in texts]
            raise

    # hash fallback 逐条处理即可。
    if provider == "hash":
        return [embed_text_with_hash(text) for text in texts]

    # 未知 provider 直接报错。
    raise RuntimeError(f"未知 EMBEDDING_PROVIDER：{provider}")


def embed_text_with_bge(text: str) -> list[float]:
    """使用本地 BGE-M3 生成单条文本 embedding。"""
    # 复用批量函数，保持实现一致。
    return embed_texts_with_bge([text])[0]


def embed_texts_with_bge(texts: list[str]) -> list[list[float]]:
    """使用本地 BGE-M3 批量生成 embedding。"""
    # 获取模型对象。
    model = load_bge_model()

    # 调用 BGE-M3，返回 dense_vecs。
    result = model.encode(
        texts,
        batch_size=embedding_batch_size(),
        max_length=embedding_max_length(),
    )

    # FlagEmbedding 返回 numpy.ndarray，这里转成普通 list，方便 JSON 入库。
    dense_vectors = result["dense_vecs"]

    # BGE 输出通常已经适合相似度计算；这里仍做一次归一化，保证余弦计算稳定。
    return [normalize_vector(vector.tolist()) for vector in dense_vectors]


def tokenize(text: str) -> list[str]:
    """hash fallback：把文本拆成 token。"""
    # lower 统一大小写，re.findall 提取英文/数字/中文连续片段。
    raw_tokens = re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+", text.lower())

    # 过滤掉太短的英文 token，保留中文 token。
    return [
        token
        for token in raw_tokens
        if len(token) >= 3 or re.search(r"[\u4e00-\u9fff]", token)
    ]


def stable_index(token: str, dimension: int) -> int:
    """hash fallback：把 token 稳定映射到向量下标。"""
    # sha256 返回固定字节序列，同一个 token 每次都会得到相同结果。
    digest = hashlib.sha256(token.encode("utf-8")).digest()

    # 取前 8 个字节转成整数，再对维度取模。
    return int.from_bytes(digest[:8], "big") % dimension


def embed_text_with_hash(
    text: str,
    dimension: int = DEFAULT_HASH_EMBEDDING_DIMENSION,
) -> list[float]:
    """hash fallback：把文本转换成固定长度向量。"""
    # 初始化全 0 向量。
    vector = [0.0] * dimension

    # 逐个 token 写入对应维度。
    for token in tokenize(text):
        # 找到 token 对应的维度。
        index = stable_index(token, dimension)

        # 使用词频累加，出现越多权重越高。
        vector[index] += 1.0

    # 归一化向量，避免长文本天然相似度更高。
    return normalize_vector(vector)


def normalize_vector(vector: list[float]) -> list[float]:
    """把向量长度归一化为 1。"""
    # 计算欧几里得长度。
    norm = math.sqrt(sum(value * value for value in vector))

    # 空向量直接返回原值，避免除以 0。
    if norm == 0:
        return vector

    # 每个维度除以向量长度。
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    # zip 会逐维配对，乘积求和就是点积。
    return sum(left_value * right_value for left_value, right_value in zip(left, right))
