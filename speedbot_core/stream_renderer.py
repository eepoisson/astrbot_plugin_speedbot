"""
流式输出渲染器 / Streaming Output Renderer

将 LLM 的流式 token 输出转换为分段消息，实现"打字机"效果，
用户在首个 token 生成时即可看到回复，大幅提升主观体验速度。

针对 DeepSeek R1 系列推理模型（DeepSeek Reasoner）进行了专项优化：
模型在输出最终答案前会先输出 <think>…</think> 推理链，
本渲染器可在转发给用户前自动剥离这些内部推理块，
让用户直接看到干净的最终答案。

Converts LLM streaming token output into segmented messages, delivering a
"typewriter" effect. Users see the first reply segment as soon as the first
token is generated, significantly improving perceived response speed.

Includes a DeepSeek R1 / Reasoner optimisation: the model wraps its
chain-of-thought inside <think>…</think> blocks before the final answer.
When strip_thinking_tags=True, those blocks are silently discarded so users
only receive the clean final answer.
"""

import asyncio
import re
import time
from typing import AsyncGenerator, Awaitable, Callable, Optional


# 分句正则：在句末标点后切分
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?\n])\s*")

# DeepSeek R1 推理链标签正则（贪婪，跨行匹配）
# Matches the full <think>...</think> block produced by DeepSeek R1 reasoner.
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class StreamRenderer:
    """
    流式输出渲染器 / Streaming Output Renderer.

    逐 token 消费异步生成器，按句子分割后调用回调函数发送给用户，
    首字节即开始显示，实现类打字机体验。

    针对 DeepSeek R1 推理模型：当 strip_thinking_tags=True 时，
    自动过滤 <think>…</think> 推理链，只向用户呈现最终答案。

    Consumes an async token generator token-by-token, splits output by
    sentence boundaries, and calls a send callback so users see the first
    segment immediately — typewriter-style.

    DeepSeek R1 mode: when strip_thinking_tags=True, internal reasoning
    wrapped in <think>…</think> is stripped before delivery to the user.
    """

    def __init__(
        self,
        min_chunk_size: int = 10,
        max_buffer_wait: float = 2.0,
        inter_chunk_delay: float = 0.05,
        strip_thinking_tags: bool = False,
    ) -> None:
        """
        初始化流式渲染器 / Initialise the stream renderer.

        Args:
            min_chunk_size: 最小分段字符数，避免发送太碎的片段 / Min chars per chunk.
            max_buffer_wait: 缓冲区最长等待时间（秒） / Max buffer wait before forced flush.
            inter_chunk_delay: 分段间发送延迟（秒），营造打字机节奏 / Delay between chunks.
            strip_thinking_tags: 是否剥离 DeepSeek R1 的 <think>…</think> 推理块。
                                 Set True when using DeepSeek R1 / Reasoner models.
        """
        self.min_chunk_size = min_chunk_size
        self.max_buffer_wait = max_buffer_wait
        self.inter_chunk_delay = inter_chunk_delay
        self.strip_thinking_tags = strip_thinking_tags

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
        当 strip_thinking_tags=True 时（DeepSeek R1 模式），在 <think>…</think>
        推理链期间静默缓冲，</think> 出现后才开始向用户推送最终答案，
        实现"思考中静默，答案即时显示"的体验。

        Consumes each token from token_generator, buffers, and sends by sentence.
        In DeepSeek R1 mode (strip_thinking_tags=True), tokens inside the
        <think>…</think> block are silently buffered; streaming to the user
        only begins after </think>, delivering the final answer immediately.

        Args:
            token_generator: LLM 流式 token 异步生成器 / Async token generator.
            send_callback: 发送分段文本的回调（接受单个字符串参数） / Send callback.

        Returns:
            完整回复文本（含推理链） / Full concatenated reply text (including think blocks).
        """
        buffer = ""
        full_text = ""
        last_send_time = time.monotonic()

        # DeepSeek R1 推理链过滤状态（两阶段流式过滤）
        # DeepSeek R1 two-phase streaming filter:
        # Phase 1 – accumulate silently until </think> found (or determined absent)
        # Phase 2 – stream displayable content normally
        #
        # think_end_pos: index in full_text right after </think>, or 0 if no think block;
        #                None while still searching
        # no_think_block: True once we determine the response has no think block
        # answer_committed: chars from the answer portion already added to buffer
        _THINK_END_TAG = "</think>"
        _THINK_END_LEN = len(_THINK_END_TAG)
        _THINK_START_MARKER = "<think>"
        # DeepSeek R1 always outputs <think> as the very first non-whitespace token.
        # After _THINK_LOOKAHEAD characters, if the text (stripped of leading whitespace)
        # doesn't start with <think>, we can safely assume no think block follows.
        # 20 chars covers any leading whitespace/BOM and the 7-char "<think>" tag itself.
        _THINK_LOOKAHEAD = 20

        think_end_pos: Optional[int] = None
        no_think_block: bool = False
        answer_committed: int = 0

        async def _flush(text: str) -> None:
            """发送一段文本 / Send a text segment."""
            if text.strip():
                await send_callback(text)
                await asyncio.sleep(self.inter_chunk_delay)

        try:
            async for token in token_generator:
                full_text += token

                if self.strip_thinking_tags:
                    # ── Phase 1: find the end of the think block ──────────────
                    if think_end_pos is None and not no_think_block:
                        end_idx = full_text.find(_THINK_END_TAG)
                        if end_idx != -1:
                            # </think> found; answer starts right after it
                            think_end_pos = end_idx + _THINK_END_LEN
                        elif (
                            len(full_text) >= _THINK_LOOKAHEAD
                            and not full_text.lstrip().startswith(_THINK_START_MARKER)
                        ):
                            # Enough chars seen, no think block present
                            no_think_block = True
                            think_end_pos = 0

                    # ── Phase 2: stream answer portion ───────────────────────
                    if think_end_pos is None:
                        # Still waiting for </think>; nothing to display yet
                        continue

                    answer_portion = full_text[think_end_pos:]
                    new_content = answer_portion[answer_committed:]
                    if not new_content:
                        continue
                    answer_committed += len(new_content)
                    buffer += new_content
                else:
                    buffer += token
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
            # End-of-stream: if think block was started but </think> never arrived
            # (malformed output), discard the incomplete think content entirely.
            if self.strip_thinking_tags and think_end_pos is None and not no_think_block:
                if full_text.lstrip().startswith(_THINK_START_MARKER):
                    # Whole response was an unclosed think block – output nothing
                    pass
                else:
                    # No think block detected; output any remaining clean content
                    leftover = full_text[answer_committed:]
                    if leftover.strip():
                        buffer += leftover
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
