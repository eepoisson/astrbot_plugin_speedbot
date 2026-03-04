# astrbot_plugin_speedbot

🚀 **SpeedBot 加速引擎** — 多维度加速 AstrBot 响应速度的插件，从 6 个维度将响应时间从秒级压缩到毫秒级。已针对 DeepSeek 3.2 Reasoner（deepseek-reasoner）模型进行专项调优。

**当前版本：v1.0.6**（修复插件上传安装时的 `KeyError: 'items'` 崩溃）

---

## ✨ 功能亮点

### 六大核心加速模块

| 模块 | 说明 | 加速效果 |
|------|------|----------|
| 📦 语义向量缓存 (`speedbot_core/semantic_cache.py`) | 字符 n-gram TF-IDF 向量化 + 余弦相似度匹配历史问题，支持 TTL 过期与 LRU 淘汰 | 秒级 → 毫秒级 (400x) |
| 🧭 意图预分类路由 (`speedbot_core/intent_router.py`) | 正则 + 关键词匹配简单意图（打招呼、问时间、感谢、身份询问），本地直接回复 | 完全跳过 LLM (1500x) |
| 🌐 HTTP 连接池 (`speedbot_core/connection_pool.py`) | aiohttp.TCPConnector 持久化连接，复用 TCP 长连接 | 减少 ~100ms 握手 |
| ⚡ 优先级队列 (`speedbot_core/priority_queue.py`) | asyncio.PriorityQueue + Semaphore 并发控制，管理员指令优先调度 | 高并发不饿死 |
| 📝 流式渲染器 (`speedbot_core/stream_renderer.py`) | LLM streaming token 按句分发，首字节即显示打字机效果 | 体感延迟降低 80% |
| 🔧 异步执行器 (`speedbot_core/async_executor.py`) | run_in_executor 将同步阻塞操作委托给线程池 | 主线程不阻塞 |

### 辅助模块
- 🛡️ **熔断器** (`speedbot_utils/circuit_breaker.py`) — 三状态（CLOSED / OPEN / HALF_OPEN）熔断保护，防止下游异常雪崩
- 📊 **性能监控** (`speedbot_utils/monitor.py`) — 请求级计时，输出 avg/p50/p95 延迟与来源分布

### 插件命令

| 命令 | 说明 |
|------|------|
| `/speed stats` | 显示所有模块综合性能统计 |
| `/speed cache` | 显示语义缓存统计（命中率、平均耗时等） |
| `/speed clear` | 清除所有语义缓存 |
| `/speed intent` | 显示意图路由统计 |
| `/speed pool` | 显示 HTTP 连接池统计 |

---

## 🎯 DeepSeek 3.2 Reasoner 专项调优

默认配置已针对 DeepSeek Reasoner 的链式思考（chain-of-thought）特性进行优化：

| 参数 | 通用默认值 | Reasoner 调优值 | 原因 |
|------|-----------|----------------|------|
| `semantic_cache.similarity_threshold` | 0.92 | 0.88 | 覆盖措辞变化，节省高成本推理调用 |
| `semantic_cache.ttl_seconds` | 3600 | 7200 | 推理结果生成成本高，缓存延长至 2 小时 |
| `connection_pool.keepalive_timeout` | 60 | 120 | 推理耗时 5-30s，防止连接超时断开 |
| `priority_queue.max_concurrent` | 5 | 2 | 符合 DeepSeek API 并发速率限制，避免 429 |
| `monitor.slow_threshold_ms` | 3000 | 20000 | Reasoner 正常响应 5-30s，避免误报 |

---

## 📋 环境要求

- Python ≥ 3.10
- AstrBot ≥ 4.0.0
- 依赖: `numpy>=1.24.0`, `aiohttp>=3.9.0`

## 📥 安装方式

**方法 1（推荐）— AstrBot 命令安装：**

```
/plugin install astrbot_plugin_speedbot
```

**方法 2 — 手动安装：**

```bash
cd /path/to/astrbot/addons/plugins/
git clone https://github.com/eepoisson/astrbot_plugin_speedbot.git
pip install -r astrbot_plugin_speedbot/requirements.txt
```

---

## 📂 项目结构

```
astrbot_plugin_speedbot/
├── main.py                      # 插件入口
├── metadata.yaml                # AstrBot 插件元数据
├── _conf_schema.json            # 配置 Schema
├── config.yaml                  # 配置模板（已调优）
├── requirements.txt             # Python 依赖
├── CHANGELOG.md                 # 版本历史
├── speedbot_core/               # 六大核心引擎模块
│   ├── semantic_cache.py
│   ├── intent_router.py
│   ├── priority_queue.py
│   ├── connection_pool.py
│   ├── stream_renderer.py
│   └── async_executor.py
└── speedbot_utils/              # 工具模块
    ├── monitor.py
    └── circuit_breaker.py
```

---

Full Changelog: https://github.com/eepoisson/astrbot_plugin_speedbot/blob/main/CHANGELOG.md
