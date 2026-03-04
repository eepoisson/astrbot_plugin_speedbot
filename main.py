"""
SpeedBot 加速引擎插件主入口 / SpeedBot Acceleration Engine Plugin Entry

AstrBot 插件主类，继承 Star，注册命令与钩子，协调六大核心模块。
集成：语义缓存、意图路由、连接池、优先级队列、流式渲染、异步执行器。

Main AstrBot plugin class. Inherits Star, registers commands and hooks,
and orchestrates the six core acceleration modules:
semantic cache, intent router, connection pool, priority queue,
stream renderer, and async executor.
"""

import os
import sys
import uuid

# Ensure the plugin directory is on sys.path so that the `core` and `utils`
# sub-packages can be imported by name regardless of how AstrBot loads the module.
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.event.filter import (
    EventMessageType,
    command,
    command_group,
    event_message_type,
    on_llm_request,
)
from astrbot.api.star import Context, Star

from core.async_executor import AsyncExecutor
from core.connection_pool import ConnectionPool
from core.intent_router import IntentRouter
from core.priority_queue import Priority, PriorityQueue
from core.semantic_cache import SemanticCache
from core.stream_renderer import StreamRenderer
from utils.circuit_breaker import CircuitBreaker
from utils.monitor import PerformanceMonitor


class Main(Star):
    """
    SpeedBot 加速引擎插件主类 / SpeedBot Acceleration Engine Plugin Main Class.

    从六个维度加速 AstrBot 响应：
    1. 语义向量缓存  — 毫秒级命中历史相似问题
    2. 意图预分类    — 本地直接处理简单意图
    3. 连接池管理    — 复用 TCP 长连接
    4. 优先级队列    — 高并发下智能调度
    5. 流式渲染      — 首 token 即显示
    6. 异步执行器    — 阻塞操作不卡主线程

    Accelerates AstrBot responses across six dimensions:
    1. Semantic cache — ms-level hit for similar past questions
    2. Intent router  — handle simple intents locally
    3. Connection pool — reuse TCP keep-alive connections
    4. Priority queue — smart scheduling under high concurrency
    5. Stream renderer — display from first token
    6. Async executor — offload blocking ops from event loop
    """

    def __init__(self, context: Context, config=None) -> None:
        """
        初始化插件 / Initialise the plugin.

        Args:
            context: AstrBot 上下文 / AstrBot context object.
            config: 插件配置字典（来自 _conf_schema.json） / Plugin config dict.
        """
        super().__init__(context)
        self.config: dict = config or {}

        # 子模块实例，在 initialize() 中根据配置创建
        self.semantic_cache: SemanticCache = None
        self.intent_router: IntentRouter = None
        self.connection_pool: ConnectionPool = None
        self.priority_queue: PriorityQueue = None
        self.stream_renderer: StreamRenderer = None
        self.async_executor: AsyncExecutor = None
        self.monitor: PerformanceMonitor = None
        self.circuit_breaker: CircuitBreaker = None

    async def initialize(self) -> None:
        """
        插件激活时调用，读取配置并初始化所有子模块。
        Called when the plugin is activated. Reads config and initialises all sub-modules.
        """
        logger.info("[SpeedBot] 正在初始化加速引擎插件...")

        # --- 语义缓存 ---
        cache_cfg = self.config.get("semantic_cache", {})
        self.semantic_cache = SemanticCache(
            similarity_threshold=float(cache_cfg.get("similarity_threshold", 0.92)),
            max_cache_size=int(cache_cfg.get("max_cache_size", 1000)),
            ttl_seconds=float(cache_cfg.get("ttl_seconds", 3600)),
        )

        # --- 意图路由 ---
        self.intent_router = IntentRouter()

        # --- 连接池 ---
        pool_cfg = self.config.get("connection_pool", {})
        self.connection_pool = ConnectionPool(
            pool_size=int(pool_cfg.get("pool_size", 100)),
            per_host_limit=int(pool_cfg.get("per_host_limit", 30)),
            keepalive_timeout=int(pool_cfg.get("keepalive_timeout", 60)),
        )

        # --- 优先级队列 ---
        pq_cfg = self.config.get("priority_queue", {})
        self.priority_queue = PriorityQueue(
            max_concurrent=int(pq_cfg.get("max_concurrent", 5)),
        )
        await self.priority_queue.start()

        # --- 流式渲染 ---
        dr_cfg = self.config.get("deepseek_reasoner", {})
        strip_tags = dr_cfg.get("enable", False) and dr_cfg.get("strip_thinking_tags", True)
        self.stream_renderer = StreamRenderer(strip_thinking_tags=strip_tags)

        # --- 异步执行器 ---
        self.async_executor = AsyncExecutor()

        # --- 性能监控 ---
        monitor_cfg = self.config.get("monitor", {})
        self.monitor = PerformanceMonitor(
            slow_threshold_ms=float(monitor_cfg.get("slow_threshold_ms", 3000)),
        )

        # --- 熔断器 ---
        self.circuit_breaker = CircuitBreaker(name="llm_api")

        logger.info("[SpeedBot] 加速引擎插件初始化完成 ✅")

    async def terminate(self) -> None:
        """
        插件禁用/重载时调用，释放所有资源。
        Called when the plugin is disabled or reloaded. Releases all resources.
        """
        logger.info("[SpeedBot] 正在关闭加速引擎插件...")
        try:
            if self.priority_queue:
                await self.priority_queue.stop()
            if self.connection_pool:
                await self.connection_pool.close()
            if self.async_executor:
                self.async_executor.shutdown(wait=False)
        except Exception as e:
            logger.warning(f"[SpeedBot] 关闭资源时出现异常: {e}")
        logger.info("[SpeedBot] 加速引擎插件已关闭 ✅")

    # ------------------------------------------------------------------
    # LLM 请求拦截钩子 / LLM request intercept hook
    # ------------------------------------------------------------------

    @on_llm_request()
    async def on_llm_request_hook(self, event: AstrMessageEvent):
        """
        在 LLM 被调用前拦截，先查缓存再查意图路由。
        Intercepts before LLM is called: checks cache first, then intent router.

        Args:
            event: AstrMessageEvent 实例 / AstrMessageEvent instance.
        """
        if not self._modules_ready():
            return

        text = event.message_str.strip()
        if not text:
            return

        request_id = str(uuid.uuid4())[:8]

        async with self.monitor.track(request_id) as metrics:
            # 0. DeepSeek Reasoner 模式：发送「正在思考」提示
            dr_cfg = self.config.get("deepseek_reasoner", {})
            if dr_cfg.get("enable", False) and dr_cfg.get("thinking_hint", True):
                yield event.plain_result("⏳ 正在深度思考，请稍候…")

            # 1. 语义缓存查询
            cache_cfg = self.config.get("semantic_cache", {})
            if cache_cfg.get("enable", True):
                cached = await self.semantic_cache.lookup(text)
                if cached:
                    metrics.cache_hit = True
                    metrics.source = "cache"
                    logger.debug(f"[SpeedBot] 缓存命中: {text[:30]}...")
                    event.stop_event()
                    yield event.plain_result(f"[⚡缓存] {cached}")
                    return

            # 2. 意图路由查询
            intent_cfg = self.config.get("intent_router", {})
            if intent_cfg.get("enable", True):
                sender_name = ""
                try:
                    sender_name = event.get_sender_name() or ""
                except Exception:
                    pass
                result = await self.intent_router.route(text, sender_name)
                if result:
                    intent_name, reply = result
                    metrics.intent_routed = True
                    metrics.source = "intent"
                    logger.debug(f"[SpeedBot] 意图命中: {intent_name}")
                    event.stop_event()
                    yield event.plain_result(reply)
                    return

            # 未命中，放行给 LLM
            metrics.source = "llm"

    # ------------------------------------------------------------------
    # 全类型消息监听（用于存储 LLM 回复到缓存）
    # ------------------------------------------------------------------

    @event_message_type(EventMessageType.ALL)
    async def on_all_messages(self, event: AstrMessageEvent):
        """
        监听所有消息，将非命令消息的 LLM 回复存入语义缓存。
        Listens to all messages; stores LLM replies for non-command messages.

        Note: 此处仅作占位；实际 LLM 回复的缓存写入由 on_llm_request_hook 处理，
        或可扩展为监听 LLM 回复事件后写入缓存。
        This serves as a placeholder; cache writes after LLM replies can be
        extended here or via a dedicated LLM response hook.
        """
        pass

    # ------------------------------------------------------------------
    # 命令组 /speed
    # ------------------------------------------------------------------

    @command_group("speed")
    async def speed_cmd_group(self):
        """
        /speed 命令组入口 / /speed command group entry.
        """
        pass

    @speed_cmd_group.command("stats")
    async def speed_stats(self, event: AstrMessageEvent):
        """
        显示所有模块的综合性能统计 / Show comprehensive stats for all modules.

        Usage: /speed stats
        """
        if not self._modules_ready():
            yield event.plain_result("⚠️ SpeedBot 模块尚未初始化，请稍候重试。")
            return

        parts = [
            "🚀 SpeedBot 加速引擎 — 综合性能统计",
            "=" * 40,
            self.semantic_cache.get_stats_text(),
            "",
            self.intent_router.get_stats_text(),
            "",
            self.priority_queue.get_stats_text(),
            "",
            self.connection_pool.get_stats_text(),
            "",
            self.async_executor.get_stats_text(),
            "",
            self.monitor.get_stats_text(),
            "",
            self.circuit_breaker.get_stats_text(),
        ]
        yield event.plain_result("\n".join(parts))

    @speed_cmd_group.command("cache")
    async def speed_cache(self, event: AstrMessageEvent):
        """
        显示语义缓存统计 / Show semantic cache statistics.

        Usage: /speed cache
        """
        if not self._modules_ready():
            yield event.plain_result("⚠️ SpeedBot 模块尚未初始化。")
            return
        yield event.plain_result(self.semantic_cache.get_stats_text())

    @speed_cmd_group.command("clear")
    async def speed_clear(self, event: AstrMessageEvent):
        """
        清除所有语义缓存 / Clear all semantic cache entries.

        Usage: /speed clear
        """
        if not self._modules_ready():
            yield event.plain_result("⚠️ SpeedBot 模块尚未初始化。")
            return
        await self.semantic_cache.invalidate()
        yield event.plain_result("✅ 语义缓存已清除！")

    @speed_cmd_group.command("intent")
    async def speed_intent(self, event: AstrMessageEvent):
        """
        显示意图路由统计 / Show intent router statistics.

        Usage: /speed intent
        """
        if not self._modules_ready():
            yield event.plain_result("⚠️ SpeedBot 模块尚未初始化。")
            return
        yield event.plain_result(self.intent_router.get_stats_text())

    @speed_cmd_group.command("pool")
    async def speed_pool(self, event: AstrMessageEvent):
        """
        显示连接池统计 / Show connection pool statistics.

        Usage: /speed pool
        """
        if not self._modules_ready():
            yield event.plain_result("⚠️ SpeedBot 模块尚未初始化。")
            return
        yield event.plain_result(self.connection_pool.get_stats_text())

    # ------------------------------------------------------------------
    # 内部工具方法 / Internal helpers
    # ------------------------------------------------------------------

    def _modules_ready(self) -> bool:
        """
        检查核心模块是否已初始化 / Check if all core modules are initialised.

        Returns:
            全部就绪返回 True / True if all modules are ready.
        """
        return all([
            self.semantic_cache is not None,
            self.intent_router is not None,
            self.connection_pool is not None,
            self.priority_queue is not None,
            self.monitor is not None,
            self.circuit_breaker is not None,
        ])
