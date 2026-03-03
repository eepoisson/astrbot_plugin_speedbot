# 🚀 SpeedBot 加速引擎

> 多维度加速 AstrBot 响应速度的插件，从 6 个维度将响应时间从秒级压缩到毫秒级。

[![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D4.0.0-blue)](https://github.com/Soulter/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 架构图

```
用户消息
   │
   ▼
┌─────────────────────────────────────────────────────┐
│              SpeedBot 加速引擎                       │
│                                                     │
│  ① 意图路由 ──→ 本地直接回复 (打招呼/问时间等)       │
│       │ miss                                        │
│  ② 语义缓存 ──→ 命中则返回缓存结果 (毫秒级)          │
│       │ miss                                        │
│  ③ 优先级队列 ──→ 按优先级调度 LLM 请求              │
│       │                                             │
│  ④ 连接池 ──→ 复用 TCP 长连接发送 LLM API 请求       │
│       │                                             │
│  ⑤ 流式渲染 ──→ 首 token 即显示，打字机效果          │
│       │                                             │
│  ⑥ 异步执行器 ──→ 同步阻塞操作不卡主线程             │
└─────────────────────────────────────────────────────┘
   │
   ▼
LLM 回复 → 存入语义缓存
```

---

## 六大核心模块

| 模块 | 文件 | 功能 | 加速效果 |
|------|------|------|---------|
| 语义向量缓存 | `core/semantic_cache.py` | 字符 n-gram TF-IDF 向量化，余弦相似度匹配历史问题 | 秒级 → 毫秒级 |
| 意图预分类路由 | `core/intent_router.py` | 正则+关键词匹配简单意图，本地直接回复 | 完全跳过 LLM |
| HTTP 连接池 | `core/connection_pool.py` | aiohttp.TCPConnector 持久化连接，复用 TCP | 减少 ~100ms 握手 |
| 优先级队列 | `core/priority_queue.py` | asyncio.PriorityQueue 智能调度，Semaphore 控并发 | 高并发不饿死 |
| 流式渲染器 | `core/stream_renderer.py` | LLM streaming token 按句分发，首字节即显示；**DeepSeek R1：自动剥离 `<think>` 推理链** | 体感延迟降低 80% |
| 异步执行器 | `core/async_executor.py` | run_in_executor 将同步阻塞转异步 | 主线程不阻塞 |

---

## 安装与配置

> 📖 **完整打包下载安装说明**（含 DeepSeek Reasoner 专项配置）请参阅 **[INSTALL.md](INSTALL.md)**。

### 方法 1：通过 AstrBot 命令安装（推荐）

在 AstrBot 中输入：

```
/plugin install astrbot_plugin_speedbot
```

### 方法 2：手动安装（本地插件库）

1. 下载或克隆本仓库到 AstrBot 的 `addons/plugins/` 目录，**目录名必须为 `astrbot_plugin_speedbot`**：

```bash
cd /path/to/astrbot/addons/plugins/
git clone https://github.com/eepoisson/astrbot_plugin_speedbot.git
```

2. 安装依赖：

```bash
pip install numpy>=1.24.0 aiohttp>=3.9.0
```

3. 在 AstrBot WebUI 中启用插件并重启。

---

## 命令说明

| 命令 | 说明 |
|------|------|
| `/speed stats` | 显示所有模块综合性能统计 |
| `/speed cache` | 显示语义缓存统计（命中率、平均耗时等） |
| `/speed clear` | 清除所有语义缓存 |
| `/speed intent` | 显示意图路由统计 |
| `/speed pool`  | 显示 HTTP 连接池统计 |

---

## 配置项说明

通过 AstrBot WebUI 或编辑 `config.yaml` 进行配置：

### 语义缓存

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enable` | bool | `true` | 是否启用语义缓存 |
| `similarity_threshold` | float | `0.92` | 余弦相似度命中阈值（0.0–1.0），越高越严格 |
| `max_cache_size` | int | `1000` | 最大缓存条目数，超出时 LRU 淘汰 |
| `ttl_seconds` | int | `3600` | 缓存条目生存时间（秒） |

### 意图路由

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enable` | bool | `true` | 是否启用意图快速路由 |
| `custom_intents_path` | str | `""` | 自定义意图规则 JSON 文件路径（留空不加载） |

### 连接池

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enable` | bool | `true` | 是否启用连接池优化 |
| `pool_size` | int | `100` | 最大连接数 |
| `per_host_limit` | int | `30` | 每主机最大连接数 |
| `keepalive_timeout` | int | `60` | TCP 长连接保活时间（秒） |

### 优先级队列

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enable` | bool | `true` | 是否启用优先级队列 |
| `max_concurrent` | int | `5` | 最大并发 LLM 请求数 |
| `admin_priority_boost` | int | `10` | 管理员指令优先级提升值 |

### 性能监控

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enable` | bool | `true` | 是否启用性能监控 |
| `slow_threshold_ms` | int | `3000` | 慢响应阈值（毫秒），超过则记录警告 |

### DeepSeek Reasoner 推理链过滤（新功能）

当使用 DeepSeek R1 / Reasoner 模型时，可开启以下配置自动过滤 `<think>…</think>` 推理链，
让用户只看到干净的最终答案：

```yaml
deepseek_reasoner:
  enable: true              # 开启专项优化
  strip_thinking_tags: true # 自动剥离 <think>…</think>（推荐）
  thinking_hint: true       # 推理期间发送「⏳ 正在深度思考」提示
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enable` | bool | `false` | 启用 DeepSeek Reasoner 流式过滤 |
| `strip_thinking_tags` | bool | `true` | 剥离 `<think>…</think>` 推理链 |
| `thinking_hint` | bool | `true` | 推理期间向用户发送进度提示 |

---

## 性能预期对比

| 场景 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 重复/相似问题（缓存命中） | ~2000 ms | ~5 ms | **400x** |
| 简单意图（打招呼、问时间） | ~1500 ms | ~1 ms | **1500x** |
| 首次 LLM 请求（连接池） | ~2500 ms | ~2300 ms | ~8% |
| 流式输出（首字节可见） | 等待全部完成 | 首 token 即显示 | 体感 **80%↑** |
| 高并发（优先级队列） | 随机调度 | 按优先级有序 | 公平性 ✅ |

---

## 内置意图规则

SpeedBot 内置以下快速响应意图，命中后**不消耗 LLM 调用**：

| 意图 | 触发示例 | 回复类型 |
|------|---------|---------|
| `greeting` | 你好、hi、hello、嗨、哈喽 | 随机友好问候 |
| `ask_time` | 几点了、什么时间、当前时间 | 格式化当前时间 |
| `thanks` | 谢谢、感谢、thanks | 随机感谢回复 |
| `bot_identity` | 你是谁、叫什么名字 | SpeedBot 自我介绍 |

---

## DeepSeek 3.2 Reasoner 专项调优

当 AstrBot 配置使用 **DeepSeek 3.2 Reasoner（`deepseek-reasoner`）** 时，本插件的默认配置已自动针对该模型特性进行调整：

| 参数 | 通用值 | Reasoner 调优值 | 原因 |
|------|--------|----------------|------|
| `semantic_cache.similarity_threshold` | 0.92 | **0.88** | 覆盖措辞变化，减少高成本推理调用 |
| `semantic_cache.ttl_seconds` | 3600 | **7200** | 推理结果成本高，缓存时长延至 2 小时 |
| `connection_pool.keepalive_timeout` | 60 | **120** | 推理耗时 5-30s，防止连接等待期断开 |
| `priority_queue.max_concurrent` | 5 | **2** | 符合 DeepSeek API 并发速率限制，避免 429 |
| `monitor.slow_threshold_ms` | 3000 | **20000** | Reasoner 正常响应 5-30s，避免误报 |

> 详细说明与配置方法请参阅 **[INSTALL.md](INSTALL.md)**。

---

## 注意事项

1. **语义缓存精度**：相似度阈值默认 0.92，可根据实际效果调整。阈值过低可能导致误命中。
2. **numpy 依赖**：语义缓存依赖 numpy 进行向量计算，若未安装则退化为精确字符串匹配。
3. **连接池复用**：连接池主要优化插件自身的 HTTP 请求，不直接影响 AstrBot 框架的 LLM 连接（取决于 AstrBot 版本）。
4. **流式渲染**：需要 LLM 配置支持 streaming 模式。

---

## FAQ

**Q: 安装后没有明显加速效果？**  
A: 加速效果在重复/相似问题上最为显著。首次使用时缓存为空，需要一定量的历史问题积累。

**Q: 意图路由误触发了不该处理的消息？**  
A: 可适当调高关键词匹配的长度限制，或在配置中禁用意图路由（`intent_router.enable: false`）。

**Q: `/speed stats` 显示模块未初始化？**  
A: 请确认插件已在 AstrBot WebUI 中启用，并等待 `initialize()` 完成。

---

## 项目结构

```
astrbot_plugin_speedbot/
├── main.py                    # 插件入口：Star 子类，注册命令与钩子
├── metadata.yaml              # AstrBot 插件元数据
├── _conf_schema.json          # 插件配置 Schema（WebUI 可编辑）
├── requirements.txt           # Python 依赖
├── README.md                  # 本文件
├── INSTALL.md                 # 打包下载安装说明（含本地插件库部署指南）
├── config.yaml                # 用户自定义配置模板（已针对 DeepSeek Reasoner 调优）
│
├── core/                      # 核心引擎模块
│   ├── __init__.py
│   ├── semantic_cache.py      # 语义向量缓存引擎
│   ├── intent_router.py       # 意图预分类路由器
│   ├── priority_queue.py      # 优先级消息队列
│   ├── connection_pool.py     # HTTP 连接池管理
│   ├── stream_renderer.py     # 流式输出渲染器（含 DeepSeek R1 think-tag 过滤）
│   └── async_executor.py      # 异步执行器
│
└── utils/                     # 工具模块
    ├── __init__.py
    ├── monitor.py             # 性能监控与统计
    └── circuit_breaker.py     # 熔断器（异常保护）
```

---

## 作者

**eepoisson** — [GitHub](https://github.com/eepoisson/astrbot_plugin_speedbot)

欢迎 Issue 和 PR！🎉
