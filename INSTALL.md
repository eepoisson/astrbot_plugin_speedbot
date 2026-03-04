# 📦 SpeedBot 加速引擎 — 打包下载安装说明

> 本文档面向初学者，手把手讲解如何将 SpeedBot 插件下载并放入 AstrBot 本地插件库，然后启动运行。  
> 已针对 **DeepSeek 3.2 Reasoner（deepseek-reasoner）** 模型进行专项调优说明。

---

## 目录

1. [环境要求](#1-环境要求)
2. [下载插件包](#2-下载插件包)
3. [放入本地插件库](#3-放入本地插件库)
4. [安装 Python 依赖](#4-安装-python-依赖)
5. [在 AstrBot 中启用插件](#5-在-astrbot-中启用插件)
6. [DeepSeek 3.2 Reasoner 专项配置](#6-deepseek-32-reasoner-专项配置)
7. [验证运行](#7-验证运行)
8. [常见问题](#8-常见问题)

---

## 1. 环境要求

| 组件 | 最低版本 |
|------|---------|
| Python | 3.10 |
| AstrBot | 4.0.0 |
| AstrBot 已配置的 LLM | DeepSeek 3.2 Reasoner（`deepseek-reasoner`） |

---

## 2. 下载插件包

### 方法 A：下载 ZIP 压缩包（推荐新手）

1. 打开浏览器访问：  
   `https://github.com/eepoisson/astrbot_plugin_speedbot`

2. 点击页面右上角绿色 **Code** 按钮 → 选择 **Download ZIP**。

3. 解压下载的 `astrbot_plugin_speedbot-main.zip`，得到文件夹  
   `astrbot_plugin_speedbot-main/`（下文以此名称为例）。

### 方法 B：使用 Git 克隆

```bash
git clone https://github.com/eepoisson/astrbot_plugin_speedbot.git
```

克隆完成后得到文件夹 `astrbot_plugin_speedbot/`。

---

## 3. 放入本地插件库

AstrBot 的本地插件库目录为：

```
<AstrBot 安装目录>/addons/plugins/
```

### 步骤

1. 找到你的 AstrBot 安装目录（下文以 `/opt/astrbot` 为例，根据实际路径替换）。

2. 将解压/克隆得到的插件文件夹，**整个**复制/移动到插件目录下：

   ```bash
   # 如果是 ZIP 解压
   cp -r astrbot_plugin_speedbot-main /opt/astrbot/addons/plugins/astrbot_plugin_speedbot

   # 如果是 Git 克隆
   cp -r astrbot_plugin_speedbot /opt/astrbot/addons/plugins/astrbot_plugin_speedbot
   ```

3. 完成后，目录结构应如下所示：

   ```
   /opt/astrbot/addons/plugins/
   └── astrbot_plugin_speedbot/
       ├── main.py
       ├── metadata.yaml
       ├── _conf_schema.json
       ├── config.yaml
       ├── requirements.txt
       ├── README.md
       ├── INSTALL.md
       ├── core/
       │   ├── __init__.py
       │   ├── semantic_cache.py
       │   ├── intent_router.py
       │   ├── priority_queue.py
       │   ├── connection_pool.py
       │   ├── stream_renderer.py
       │   └── async_executor.py
       └── utils/
           ├── __init__.py
           ├── monitor.py
           └── circuit_breaker.py
   ```

   > ⚠️ **注意**：插件目录名必须是 `astrbot_plugin_speedbot`（不能带 `-main` 后缀），  
   > 且 `main.py` 必须直接位于该目录下（不能再嵌套一层子目录）。

---

## 4. 安装 Python 依赖

在终端中运行以下命令（建议在 AstrBot 所用的 Python 虚拟环境中执行）：

```bash
pip install "numpy>=1.24.0" "aiohttp>=3.9.0"
```

或者利用插件目录中的 `requirements.txt` 一键安装：

```bash
pip install -r /opt/astrbot/addons/plugins/astrbot_plugin_speedbot/requirements.txt
```

> **提示**：如果 AstrBot 使用 Docker 部署，请在容器内执行上述命令，或将依赖添加到镜像。

---

## 5. 在 AstrBot 中启用插件

### 方法 A：通过 WebUI（推荐）

1. 打开浏览器访问 AstrBot WebUI（默认地址 `http://localhost:6185`）。
2. 进入 **插件管理** 页面。
3. 在插件列表中找到 **SpeedBot 加速引擎**。
4. 点击 **启用** 开关。
5. 点击 **重载** 或重启 AstrBot。

### 方法 B：通过聊天命令

在与 AstrBot 的对话窗口中发送：

```
/plugin enable astrbot_plugin_speedbot
```

---

## 6. DeepSeek 3.2 Reasoner 专项配置

由于 DeepSeek 3.2 Reasoner 模型使用**链式思考（chain-of-thought）**推理，响应时间明显长于普通模型，本插件已内置以下调优默认值，**无需手动修改即可直接使用**：

| 参数 | 通用默认值 | Reasoner 调优值 | 调优原因 |
|------|-----------|----------------|---------|
| `semantic_cache.similarity_threshold` | 0.92 | **0.88** | 覆盖措辞不同但语义等价的问题，节省高成本推理调用 |
| `semantic_cache.ttl_seconds` | 3600 | **7200** | 推理结果生成成本高，缓存有效期延长至 2 小时 |
| `connection_pool.keepalive_timeout` | 60 | **120** | 推理响应耗时 5-30s，防止连接在等待期间超时断开 |
| `priority_queue.max_concurrent` | 5 | **2** | 符合 DeepSeek API 免费/标准层的并发速率限制，避免 429 错误 |
| `monitor.slow_threshold_ms` | 3000 | **20000** | Reasoner 正常响应时间为 5-30s，避免误报慢请求警告 |

### 如何查看或修改配置

在 AstrBot WebUI → **插件管理** → **SpeedBot 加速引擎** → **配置** 页面中修改，  
或直接编辑插件目录下的 `config.yaml` 文件。

---

## 7. 验证运行

插件启动后，在 AstrBot 聊天窗口中发送以下命令验证：

```
/speed stats
```

若看到如下格式的输出，说明插件已正常运行：

```
🚀 SpeedBot 加速引擎 — 综合性能统计
========================================
📦 语义缓存统计
  总查询数: 0
  命中率:   0.0%
  当前条目: 0/1000
...
```

其他可用命令：

| 命令 | 说明 |
|------|------|
| `/speed stats` | 综合性能统计 |
| `/speed cache` | 语义缓存详情 |
| `/speed clear` | 清除缓存 |
| `/speed intent` | 意图路由统计 |
| `/speed pool` | 连接池统计 |

---

## 8. 常见问题

**Q: 放入插件目录后，WebUI 中找不到插件？**  
A: 确认目录名为 `astrbot_plugin_speedbot`，且 `main.py` 直接位于该目录下。  
然后重启 AstrBot（或在 WebUI 中点击"重载插件"）。

**Q: 启动时报 `ImportError: No module named 'numpy'`？**  
A: 执行 `pip install numpy>=1.24.0 aiohttp>=3.9.0` 后重启 AstrBot。

**Q: DeepSeek Reasoner 响应很慢，显示"慢响应"警告？**  
A: 这是正常现象。链式思考推理需要 5-30 秒，本插件已将慢响应阈值调整为 20 秒。  
若仍有频繁警告，在配置中将 `monitor.slow_threshold_ms` 调大（如 `30000`）。

**Q: 遇到 429 Too Many Requests 错误？**  
A: 将 `priority_queue.max_concurrent` 从 2 调低为 1，并联系 DeepSeek 申请更高速率限制。

**Q: 缓存命中率低？**  
A: 尝试将 `semantic_cache.similarity_threshold` 从 0.88 调低至 0.85，  
以匹配更多语义相似但措辞不同的问题。

---

*最后更新：2026-03-04 | 适配 AstrBot ≥4.0.0 + DeepSeek 3.2 Reasoner*
