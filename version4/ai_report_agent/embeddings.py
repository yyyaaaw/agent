"""本地 embedding 模块。

Version 4 的第二阶段优化开始引入“向量检索版 RAG”。

真正的生产级 RAG 常会调用 embedding API，把文本转换成高质量语义向量。
为了保持本项目仍然只依赖 Python 标准库，这里先实现一个本地哈希 embedding：
1. 把标题、摘要、来源类别等文本切成 token。
2. 用稳定哈希把 token 映射到固定维度。
3. 得到一个可比较的向量。
4. 用余弦相似度判断两条新闻是否相似。

这个方案不如专业 embedding 模型聪明，但已经具备“文本 -> 向量 -> 相似度检索”的 RAG 骨架。
后续如果要升级成 OpenAI/DeepSeek/本地模型 embedding，只需要替换 embed_text()。

哈希embedding：
真正的 embedding 是：一段文本 -> 模型理解语义 -> 一串数字向量
而 哈希 embedding 不调用模型，它做得更简单：一段文本 -> 拆词 -> 用哈希函数把词分配到固定位置 -> 得到一串数字
eg:
    比如文本：OpenAI voice agent workflow.
    先拆成词：["openai", "voice", "agent", "workflow"]
    假设向量长度是 8，每个词通过哈希函数映射到某个位置：
    openai   -> 第 2 格
    voice    -> 第 5 格
    agent    -> 第 1 格
    workflow -> 第 5 格
    那么初始向量是：[0,0,0,0,0,0,0,0]
    加进去后：
        agent    -> [1,0,0,0,0,0,0,0]
        openai   -> [1,1,0,0,0,0,0,0]
        voice    -> [1,1,0,0,1,0,0,0]
        workflow -> [1,1,0,0,2,0,0,0]
    最后得到：[1,1,0,0,2,0,0,0]
    这个向量就代表了这段文本的语义特征，虽然不如真正的 embedding 聪明，但已经可以用来比较文本相似度了。

最后需要把向量归一化，归一化的原因是为了避免长文本的向量数字天然更大，导致相似度计算时不公平。归一化后，不管文本长短，向量长度都是 1，更能公平地比较它们的方向（语义）。
然后进行余弦相似度的计算。

哈希 embedding 的优缺点：
优点：
    不需要联网
    不需要 API Key
    不需要安装模型
    速度快
    代码简单
    适合理解 RAG 流程
缺点：
    不真正理解语义
    同义词不一定能匹配
    中英文混合效果一般
    哈希冲突会带来噪声
    比不上专业 embedding 模型
"""

from __future__ import annotations

# hashlib 提供稳定哈希函数，避免 Python 内置 hash 在不同进程间随机变化。
import hashlib

# math 用来计算向量长度和余弦相似度。
import math

# re 用来做简单分词。
import re

# 默认向量维度。维度越高冲突越少，但存储和计算也越多。
DEFAULT_EMBEDDING_DIMENSION = 128


def tokenize(text: str) -> list[str]:
    """把文本拆成适合向量化的 token。"""
    # lower 统一大小写，re.findall 提取英文/数字/中文连续片段。
    raw_tokens = re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+", text.lower())

    # 过滤掉太短的英文 token，保留中文 token。
    return [
        token
        for token in raw_tokens
        if len(token) >= 3 or re.search(r"[\u4e00-\u9fff]", token)
    ]


def stable_index(token: str, dimension: int) -> int:
    """把 token 稳定映射到向量下标。"""
    # sha256 返回固定字节序列，同一个 token 每次都会得到相同结果。
    digest = hashlib.sha256(token.encode("utf-8")).digest()

    # 取前 8 个字节转成整数，再对维度取模。
    return int.from_bytes(digest[:8], "big") % dimension


def embed_text(text: str, dimension: int = DEFAULT_EMBEDDING_DIMENSION) -> list[float]:
    """把文本转换成固定长度向量。"""
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
