"""
语义向量缓存引擎 / Semantic Vector Cache Engine

使用字符 n-gram TF-IDF 向量化将用户提问转换为向量，
通过余弦相似度检索历史相似问题，命中则直接返回缓存结果，
将响应速度从秒级提升到毫秒级。

Uses character n-gram TF-IDF vectorization to convert user questions
into vectors. Retrieves historically similar questions via cosine similarity,
returning cached results directly on hit — upgrading response speed from
seconds to milliseconds.
"""

import re
import time
import asyncio
import math
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except (ImportError, RuntimeError, OSError):
    _NUMPY_AVAILABLE = False


@dataclass
class CacheStats:
    """语义缓存统计数据类 / Cache statistics dataclass."""

    total_queries: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_lookup_ms: float = 0.0

    @property
    def avg_lookup_ms(self) -> float:
        """平均查询耗时（毫秒）/ Average lookup time in ms."""
        if self.total_queries == 0:
            return 0.0
        return self.total_lookup_ms / self.total_queries

    @property
    def hit_rate(self) -> float:
        """缓存命中率 / Cache hit rate (0.0-1.0)."""
        if self.total_queries == 0:
            return 0.0
        return self.cache_hits / self.total_queries


@dataclass
class _CacheEntry:
    """缓存条目 / A single cache entry."""

    question: str
    answer: str
    vector: Optional[object]  # numpy array or None
    created_at: float = field(default_factory=time.time)
    ttl: float = 3600.0


class SemanticCache:
    """
    语义向量缓存引擎 / Semantic Vector Cache Engine.

    基于字符 n-gram TF-IDF 计算问题向量，使用余弦相似度进行语义匹配，
    支持 TTL 过期和 LRU 淘汰，线程安全（asyncio.Lock 保护）。

    Vector-based cache using character n-gram TF-IDF. Supports TTL expiry,
    LRU eviction and asyncio.Lock-based concurrency safety.
    """

    # 分句正则，用于粗粒度文本清洗
    _PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)

    def __init__(
        self,
        similarity_threshold: float = 0.92,
        max_cache_size: int = 1000,
        ttl_seconds: float = 3600.0,
        ngram_range: Tuple[int, int] = (2, 3),
    ) -> None:
        """
        初始化语义缓存引擎 / Initialise the semantic cache engine.

        Args:
            similarity_threshold: 余弦相似度命中阈值 / cosine similarity threshold.
            max_cache_size: 最大缓存条目数（LRU） / max entries before LRU eviction.
            ttl_seconds: 每条缓存的生存时间（秒） / TTL in seconds per entry.
            ngram_range: 字符 n-gram 范围 / character n-gram range (min, max).
        """
        self.similarity_threshold = similarity_threshold
        self.max_cache_size = max_cache_size
        self.ttl_seconds = ttl_seconds
        self.ngram_range = ngram_range

        # OrderedDict 同时作为 LRU 容器
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()
        # IDF 词汇表：term -> idf_weight
        self._vocab: Dict[str, float] = {}
        self._lock = asyncio.Lock()
        self.stats = CacheStats()

    # ------------------------------------------------------------------
    # 向量化工具 / Vectorisation helpers
    # ------------------------------------------------------------------

    def _extract_ngrams(self, text: str) -> List[str]:
        """
        提取字符 n-gram 列表 / Extract character n-grams from text.

        Args:
            text: 输入文本 / Input text.

        Returns:
            n-gram 列表 / List of n-gram strings.
        """
        text = text.strip().lower()
        ngrams: List[str] = []
        for n in range(self.ngram_range[0], self.ngram_range[1] + 1):
            ngrams.extend(text[i: i + n] for i in range(len(text) - n + 1))
        return ngrams

    def _tf(self, ngrams: List[str]) -> Dict[str, float]:
        """
        计算词频 TF / Compute term frequency.

        Args:
            ngrams: n-gram 列表 / List of n-grams.

        Returns:
            {term: tf} 字典 / Term-frequency dict.
        """
        tf: Dict[str, float] = {}
        total = len(ngrams)
        if total == 0:
            return tf
        for g in ngrams:
            tf[g] = tf.get(g, 0) + 1
        for k in tf:
            tf[k] /= total
        return tf

    def _update_idf(self, ngrams: List[str]) -> None:
        """
        增量更新 IDF 词汇表（近似IDF） / Incrementally update IDF vocabulary.

        Args:
            ngrams: 新文档的 n-gram 列表 / n-grams of the new document.
        """
        doc_count = len(self._store) + 1
        unique = set(ngrams)
        for term in unique:
            # 简化：每次新增文档时线性递增文档频率近似值
            prev = self._vocab.get(term, 0.0)
            # 文档频率增量估计
            df = math.exp(-prev) * doc_count + 1  # 近似文档数
            self._vocab[term] = math.log((doc_count + 1) / (df + 1)) + 1

    def _vectorize(self, text: str) -> Optional[object]:
        """
        将文本向量化为 TF-IDF numpy 数组 / Vectorise text to TF-IDF numpy array.

        Args:
            text: 输入文本 / Input text.

        Returns:
            numpy 数组或 None（numpy 不可用时） / numpy array or None.
        """
        if not _NUMPY_AVAILABLE:
            return None
        ngrams = self._extract_ngrams(text)
        if not ngrams:
            return None
        tf = self._tf(ngrams)
        # 只取词汇表中存在的 term
        terms = [t for t in tf if t in self._vocab]
        if not terms:
            return None
        values = [tf[t] * self._vocab[t] for t in terms]
        # 构造稀疏向量（使用词汇表索引）
        vocab_list = list(self._vocab.keys())
        vec = np.zeros(len(vocab_list), dtype=np.float32)
        term_to_idx = {t: i for i, t in enumerate(vocab_list)}
        for t in terms:
            if t in term_to_idx:
                vec[term_to_idx[t]] = tf[t] * self._vocab[t]
        norm = np.linalg.norm(vec)
        if norm == 0:
            return None
        return vec / norm

    def _cosine_similarity(self, vec_a: object, vec_b: object) -> float:
        """
        计算两个已归一化向量的余弦相似度 / Cosine similarity of two unit vectors.

        Args:
            vec_a: 归一化 numpy 数组 / Normalised numpy array.
            vec_b: 归一化 numpy 数组 / Normalised numpy array.

        Returns:
            余弦相似度（0.0-1.0） / Cosine similarity value.
        """
        if not _NUMPY_AVAILABLE:
            return 0.0
        # 向量维度可能不同（词汇表增长），对齐到最小维度
        min_len = min(len(vec_a), len(vec_b))
        if min_len == 0:
            return 0.0
        return float(np.dot(vec_a[:min_len], vec_b[:min_len]))

    # ------------------------------------------------------------------
    # 公共接口 / Public interface
    # ------------------------------------------------------------------

    async def lookup(self, question: str) -> Optional[str]:
        """
        在缓存中查询语义相似问题 / Look up a semantically similar question.

        Args:
            question: 用户提问 / User question text.

        Returns:
            缓存答案字符串，未命中返回 None / Cached answer or None on miss.
        """
        start = time.monotonic()
        async with self._lock:
            self.stats.total_queries += 1
            now = time.time()

            # 清理过期条目
            expired = [k for k, v in self._store.items() if now - v.created_at > v.ttl]
            for k in expired:
                del self._store[k]

            if not self._store:
                self.stats.cache_misses += 1
                elapsed = (time.monotonic() - start) * 1000
                self.stats.total_lookup_ms += elapsed
                return None

            query_vec = self._vectorize(question)
            best_score = 0.0
            best_answer: Optional[str] = None
            best_key: Optional[str] = None

            for key, entry in self._store.items():
                if query_vec is not None and entry.vector is not None:
                    score = self._cosine_similarity(query_vec, entry.vector)
                else:
                    # numpy 不可用时退化为精确匹配
                    score = 1.0 if entry.question == question else 0.0

                if score > best_score:
                    best_score = score
                    best_answer = entry.answer
                    best_key = key

            elapsed = (time.monotonic() - start) * 1000
            self.stats.total_lookup_ms += elapsed

            if best_score >= self.similarity_threshold and best_answer is not None:
                # LRU: 移动到末尾
                if best_key:
                    self._store.move_to_end(best_key)
                self.stats.cache_hits += 1
                return best_answer

            self.stats.cache_misses += 1
            return None

    async def store(self, question: str, answer: str) -> None:
        """
        将问答对存入缓存 / Store a question-answer pair in cache.

        Args:
            question: 用户提问 / User question.
            answer: LLM 回答 / LLM answer.
        """
        async with self._lock:
            ngrams = self._extract_ngrams(question)
            self._update_idf(ngrams)
            vec = self._vectorize(question)

            entry = _CacheEntry(
                question=question,
                answer=answer,
                vector=vec,
                ttl=self.ttl_seconds,
            )

            # LRU: 如果超出最大容量，淘汰最老条目
            if question in self._store:
                self._store.move_to_end(question)
            else:
                if len(self._store) >= self.max_cache_size:
                    self._store.popitem(last=False)
                self._store[question] = entry

    async def invalidate(self) -> None:
        """
        清除所有缓存条目 / Invalidate (clear) all cache entries.
        """
        async with self._lock:
            self._store.clear()
            self._vocab.clear()
            self.stats = CacheStats()

    def get_stats_text(self) -> str:
        """
        返回格式化的缓存统计文本 / Return formatted cache statistics text.

        Returns:
            多行统计字符串 / Multi-line statistics string.
        """
        s = self.stats
        return (
            f"📦 语义缓存统计\n"
            f"  总查询数: {s.total_queries}\n"
            f"  命中数:   {s.cache_hits}\n"
            f"  未命中:   {s.cache_misses}\n"
            f"  命中率:   {s.hit_rate:.1%}\n"
            f"  平均耗时: {s.avg_lookup_ms:.2f} ms\n"
            f"  当前条目: {len(self._store)}/{self.max_cache_size}\n"
            f"  词汇量:   {len(self._vocab)}"
        )
