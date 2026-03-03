"""
流式输出渲染器 / Streaming Output Renderer

将 LLM 的流式 token 输出转换为分段消息，实现"打字机"效果，
用户在首个 token 生成时即可看到回复，大幅提升主观体验速度。

Converts LLM streaming token output into segmented messages, delivering a
"typewriter" effect. Users see the first reply segment as soon as the first
token is generated, significantly improving perceived response speed.
"""

import asyncio
import re
import time
from typing import AsyncGenerator, Awaitable, Callable, Optional


# 分句正则：在句末标点后切分
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?\n])\s*")


class StreamRenderer:
    """
    流式输出渲染器 / Streaming Output Renderer.

    逐 token 消费异步生成器，按句子分割后调用回调函数发送给用户，
    首字节即开始显示，实现类打字机体验。

    Consumes an async token generator token-by-token, splits output by
    sentence boundaries, and calls a send callback so users see the first
    segment immediately — typewriter-style.
    """

    def __init__(
        self,
        min_chunk_size: int = 10,
        max_buffer_wait: float = 2.0,
        inter_chunk_delay: float = 0.05,
    ) -> None:
        """
        初始化流式渲染器 / Initialise the stream renderer.

        Args:
            min_chunk_size: 最小分段字符数，避免发送太碎的片段 / Min chars per chunk.
            max_buffer_wait: 缓冲区最长等待时间（秒） / Max buffer wait before forced flush.
            inter_chunk_delay: 分段间发送延迟（秒），营造打字机节奏 / Delay between chunks.
        """
        self.min_chunk_size = min_chunk_size
        self.max_buffer_wait = max_buffer_wait
        self.inter_chunk_delay = inter_chunk_delay

    def _split_sentences(self, text: str) -> list:
        """
        按句末标点分割文本 / Split text at sentence-ending punctuation.

        Args:
            text: 待分割文本 / Text to split.

        Returns:
            分句列表（去除空字符串） / List of sentences (empty strings removed).
        """
        parts = _SENTENCE_SPLIT_RE.split(text)
        return [p for p in parts if p.strip()]

    async def render_stream(
        self,
        token_generator: AsyncGenerator[str, None],
        send_callback: Callable[[str], Awaitable[None]],
    ) -> str:
        """
        渲染流式输出 / Render streaming output to the user.

        消费 token_generator 产出的每个 token，缓冲后按句子分割发送。
        Consumes each token from token_generator, buffers, and sends by sentence.

        Args:
            token_generator: LLM 流式 token 异步生成器 / Async token generator.
            send_callback: 发送分段文本的回调（接受单个字符串参数） / Send callback.

        Returns:
            完整回复文本 / Full concatenated reply text.
        """
        buffer = ""
        full_text = ""
        last_send_time = time.monotonic()

        async def _flush(text: str) -> None:
            """发送一段文本 / Send a text segment."""
            if text.strip():
                await send_callback(text)
                await asyncio.sleep(self.inter_chunk_delay)

        try:
            async for token in token_generator:
                buffer += token
                full_text += token
                now = time.monotonic()

                # 检查是否应该发送：超时或遇到句末标点
                should_flush = (now - last_send_time >= self.max_buffer_wait) or (
                    len(buffer) >= self.min_chunk_size
                    and _SENTENCE_SPLIT_RE.search(buffer)
                )

                if should_flush:
                    sentences = self._split_sentences(buffer)
                    if len(sentences) > 1:
                        # 发送除最后一个（可能不完整）之外的所有句子
                        for sentence in sentences[:-1]:
                            await _flush(sentence)
                        buffer = sentences[-1]
                    elif len(sentences) == 1 and len(buffer) >= self.min_chunk_size:
                        # 单句但足够长，也发送
                        if _SENTENCE_SPLIT_RE.search(buffer):
                            await _flush(buffer)
                            buffer = ""
                    last_send_time = time.monotonic()

            # 发送剩余缓冲区内容
            if buffer.strip():
                await _flush(buffer)

        except Exception:
            # 出错时仍尝试发送已缓冲内容
            if buffer.strip():
                try:
                    await _flush(buffer)
                except Exception:
                    pass
            raise

        return full_text
