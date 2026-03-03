"""
意图预分类路由器 / Intent Pre-classification Router

通过正则表达式和关键词匹配，在消息到达 LLM 之前对简单意图进行快速分类，
由插件本地逻辑直接处理，避免不必要的 LLM 调用。

Uses regex patterns and keyword matching to quickly classify simple intents
before messages reach the LLM, handling them locally to avoid unnecessary
LLM API calls.
"""

import re
import random
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple


@dataclass
class IntentRule:
    """
    意图规则定义 / Intent rule definition.

    Attributes:
        name: 意图名称 / Intent name.
        patterns: 预编译正则列表 / Pre-compiled regex pattern list.
        keywords: 关键词列表（短文本匹配用） / Keyword list for short-text matching.
        handler: 回复生成函数(sender_name) -> str / Reply generator function.
        priority: 优先级（越小越优先） / Priority (lower = higher priority).
    """

    name: str
    patterns: List[re.Pattern]
    keywords: List[str]
    handler: Callable[[str], str]
    priority: int = 50


@dataclass
class RouterStats:
    """路由统计 / Router statistics."""

    total_routed: int = 0
    by_intent: Dict[str, int] = field(default_factory=dict)

    def record(self, intent_name: str) -> None:
        """记录一次意图命中 / Record one intent hit."""
        self.total_routed += 1
        self.by_intent[intent_name] = self.by_intent.get(intent_name, 0) + 1


# 关键词匹配最大文本长度阈值
_KEYWORD_MAX_LEN = 10


def _make_greeting_handler() -> Callable[[str], str]:
    """生成打招呼回复处理函数 / Build greeting reply handler."""
    replies = [
        "你好！😊 很高兴见到你，有什么我可以帮你的？",
        "嗨！👋 我是 SpeedBot，随时为你服务！",
        "哈喽！😄 今天有什么需要帮助的吗？",
        "Hi！✨ 我在这里，请说！",
    ]

    def handler(sender_name: str) -> str:
        name_part = f"{sender_name}，" if sender_name else ""
        return f"{random.choice(replies).replace('你好！', f'你好，{name_part}！', 1)}"

    return handler


def _make_time_handler() -> Callable[[str], str]:
    """生成询问时间回复处理函数 / Build ask-time reply handler."""

    def handler(sender_name: str) -> str:
        now = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
        return f"⏰ 当前时间：{now}"

    return handler


def _make_thanks_handler() -> Callable[[str], str]:
    """生成感谢回复处理函数 / Build thanks reply handler."""
    replies = [
        "不客气！😊 有什么需要随时告诉我。",
        "很高兴能帮到你！🎉",
        "不用谢，这是我应该做的！💪",
        "随时为你服务！✨",
    ]

    def handler(sender_name: str) -> str:
        return random.choice(replies)

    return handler


def _make_identity_handler() -> Callable[[str], str]:
    """生成询问身份回复处理函数 / Build bot-identity reply handler."""

    def handler(sender_name: str) -> str:
        return (
            "🤖 我是 SpeedBot 加速引擎插件！\n"
            "我的职责是多维度加速 AstrBot 的响应速度：\n"
            "• 语义缓存 — 毫秒级命中历史问题\n"
            "• 意图路由 — 简单问题本地直接回复\n"
            "• 连接池 — 复用 TCP 长连接\n"
            "• 优先级队列 — 智能调度并发请求\n"
            "• 流式渲染 — 首字节即显示\n"
            "• 异步执行器 — 防止主线程阻塞"
        )

    return handler


# 内置意图规则配置
_BUILTIN_RULES_CONFIG = [
    {
        "name": "greeting",
        "patterns": [
            r"^(你好|hi|hello|嗨|哈喽|hey|您好|早上好|下午好|晚上好|早安|晚安)[!！,，.。\s]*$",
            r"^(hi|hello|hey)\b",
        ],
        "keywords": ["你好", "hi", "hello", "嗨", "哈喽", "hey", "您好"],
        "handler_factory": _make_greeting_handler,
        "priority": 10,
    },
    {
        "name": "ask_time",
        "patterns": [
            r"(几点了|什么时间|当前时间|现在几点|现在时间|时间是多少|time|what time)",
        ],
        "keywords": ["几点", "时间", "time"],
        "handler_factory": _make_time_handler,
        "priority": 20,
    },
    {
        "name": "thanks",
        "patterns": [
            r"^(谢谢|感谢|thanks|thank you|thx|多谢|非常感谢)[!！,，.。\s]*$",
        ],
        "keywords": ["谢谢", "感谢", "thanks", "thank", "多谢"],
        "handler_factory": _make_thanks_handler,
        "priority": 30,
    },
    {
        "name": "bot_identity",
        "patterns": [
            r"(你是谁|叫什么名字|你叫什么|你是什么|介绍一下你自己|who are you|what are you)",
        ],
        "keywords": ["你是谁", "叫什么", "你是什么"],
        "handler_factory": _make_identity_handler,
        "priority": 40,
    },
]


class IntentRouter:
    """
    意图预分类路由器 / Intent Pre-classification Router.

    在消息进入 LLM 流程之前，通过正则和关键词快速匹配简单意图，
    由本地逻辑直接生成回复，显著降低 LLM API 调用频率。

    Rapidly matches simple intents via regex and keywords before the LLM
    pipeline. Generates replies locally, significantly reducing LLM API calls.
    """

    def __init__(self) -> None:
        """初始化路由器，加载内置规则 / Initialise router with built-in rules."""
        self._rules: List[IntentRule] = []
        self._lock = asyncio.Lock()
        self.stats = RouterStats()
        self._load_builtin_rules()

    def _load_builtin_rules(self) -> None:
        """加载内置意图规则 / Load built-in intent rules."""
        for cfg in _BUILTIN_RULES_CONFIG:
            compiled_patterns = [
                re.compile(p, re.IGNORECASE | re.UNICODE)
                for p in cfg["patterns"]
            ]
            rule = IntentRule(
                name=cfg["name"],
                patterns=compiled_patterns,
                keywords=cfg["keywords"],
                handler=cfg["handler_factory"](),
                priority=cfg["priority"],
            )
            self._rules.append(rule)
        # 按优先级排序
        self._rules.sort(key=lambda r: r.priority)

    def add_rule(self, rule: IntentRule) -> None:
        """
        添加自定义意图规则 / Add a custom intent rule.

        Args:
            rule: IntentRule 实例 / IntentRule instance.
        """
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority)

    def _match_rule(self, text: str, rule: IntentRule) -> bool:
        """
        检测文本是否匹配某条规则 / Check if text matches a given rule.

        Args:
            text: 待匹配文本 / Text to match.
            rule: 意图规则 / Intent rule.

        Returns:
            是否命中 / Whether the rule matched.
        """
        # 正则匹配（全文）
        for pattern in rule.patterns:
            if pattern.search(text):
                return True
        # 关键词匹配（仅对短文本生效，避免长文误匹配）
        if len(text) <= _KEYWORD_MAX_LEN:
            text_lower = text.lower()
            for kw in rule.keywords:
                if kw.lower() in text_lower:
                    return True
        return False

    async def route(
        self, text: str, sender_name: str = ""
    ) -> Optional[Tuple[str, str]]:
        """
        路由消息，若命中意图则返回回复 / Route message; return reply on intent match.

        Args:
            text: 用户消息文本 / User message text.
            sender_name: 发送者名称（用于个性化回复） / Sender name for personalised reply.

        Returns:
            (intent_name, reply) 元组，未命中返回 None / (intent_name, reply) or None.
        """
        text = text.strip()
        if not text:
            return None

        for rule in self._rules:
            if self._match_rule(text, rule):
                reply = rule.handler(sender_name)
                async with self._lock:
                    self.stats.record(rule.name)
                return (rule.name, reply)

        return None

    def get_stats_text(self) -> str:
        """
        返回格式化的路由统计文本 / Return formatted routing statistics text.

        Returns:
            多行统计字符串 / Multi-line statistics string.
        """
        s = self.stats
        lines = [
            f"🧭 意图路由统计",
            f"  总路由数: {s.total_routed}",
        ]
        if s.by_intent:
            lines.append("  各意图命中:")
            for intent, count in sorted(s.by_intent.items(), key=lambda x: -x[1]):
                lines.append(f"    {intent}: {count}")
        return "\n".join(lines)
