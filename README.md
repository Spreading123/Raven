# 🐦‍⬛ Raven

> **会使用工具的智慧渡鸦，栖息在你的桌面上。**

Raven 是一个基于 **PySide6** 的桌面 AI 智能助手（Agent）。如同渡鸦——自然界最擅长使用工具的智慧生物——Raven 能理解你的意图、调用工具、亲手帮你完成任务，让 AI 智能真正落地到你的日常工作流。

核心引擎采用 **DSH（DeepSeek-Harness）插件化架构**：`Model + Harness = Agent`，一切皆插件、Agent 主循环可插拔、事件总线贯穿始终。它不只是"聊天"，而是**会用工具的智能体**。

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![PySide6](https://img.shields.io/badge/GUI-PySide6-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)

## ✨ 功能特性

- 🖥️ **无边框深色 GUI**：左侧导航栏 + 右侧聊天区 + 底部输入栏，自定义标题栏，可拖拽缩放
- 💬 **聊天式气泡界面**：用户/助手/工具/错误四种独立气泡，**Markdown 渲染 + 代码高亮**
- 🤖 **Agent 核心**：对话管理、工具调用（Tool Calling）、**可插拔主循环（ReAct）**
- 🔌 **多模型供应商**：OpenAI 兼容 API（火山方舟 Ark、DeepSeek、OpenAI、本地 Ollama 等），界面可切换
- 🧩 **DSH 插件化架构**：`micro_kernel` 微内核 + `harness` 核心引擎（纯逻辑、零 UI 依赖）
- 🛠️ **工具注册表** + 文件读写内置工具（含**路径沙箱**）
- 🧠 **thinking 剥离**：模型思考内容不送入工具调用上下文
- 💾 **会话持久化**：多会话管理，历史自动保存、退出兜底存储
- 🎨 **多主题换肤**：深色 / 白色 / 青蓝黄 / 粉色，运行时一键切换
- ⚡ **流式输出**：LLM 调用运行在独立线程，最终回答逐块实时显示
- 🔍 **视觉输入**：支持多模态模型"看图"（按模型能力白名单控制）

## 📁 项目结构

```
raven/
├── main.py                     # GUI 程序入口
├── cli_main.py                 # CLI 入口（DSH 核心引擎验证，Model + Harness = Agent）
├── requirements.txt            # 依赖
│
├── config/
│   ├── settings.py             # 配置管理（.env：API key、模型、供应商注册表）
│   └── provider_store.py       # 供应商 API Key 持久化（providers.json，不入库）
│
├── micro_kernel/               # DSH 微内核（零业务逻辑）
│   ├── event_bus.py            #   事件总线（发布/订阅，解耦）
│   ├── service_ctx.py          #   服务上下文（轻量依赖注入）
│   └── plugin.py               #   插件基类 + 插件管理器（生命周期）
│
├── harness/                    # DSH 核心引擎（全部为插件，纯逻辑、零 UI）
│   ├── llm_adapter.py          #   LLM 适配插件（OpenAI 兼容 + thinking 剥离）
│   ├── tool_registry.py        #   工具注册插件
│   └── agent_loop.py           #   【核心】可插拔的 Agent 主循环（ReAct）
│
├── tools/                      # 内置工具实现（文件读写，含路径沙箱）
│   └── builtins.py
│
├── app/                        # GUI 界面层
│   ├── main_window.py          #   主窗口（无边框、主题、Agent 线程、会话管理）
│   ├── bridge.py               #   DSH 事件 ↔ Qt 信号桥接（Agent 线程通信）
│   ├── agent/                  #   LLM 客户端封装（llm.py / tools.py）
│   ├── ui/
│   │   ├── loader.py           #   QUiLoader 加载 .ui + 应用 QSS 样式
│   │   ├── chat_view.py        #   聊天区组件（QListWidget + 气泡）
│   │   ├── bubbles.py          #   用户/助手/工具/错误四类消息气泡
│   │   └── markdown_renderer.py#   Markdown 渲染 + 代码高亮
│   └── utils/
│       ├── logger.py           #   日志工具
│       ├── paths.py            #   路径定位（源码/打包）
│       └── session_store.py    #   会话持久化（sessions/，与 UI 解耦）
│
├── ui/
│   ├── main_window.ui          # 主界面结构（仅布局，不含样式）
│   ├── themes.py               # 多主题配色定义（深色/白/青蓝黄/粉）
│   └── styles/                 # QSS 样式文件（由 loader 按序拼接加载）
│       ├── base.qss            #   全局基础：背景、字体、滚动条、ToolTip
│       ├── titlebar.qss        #   标题栏样式
│       ├── sidebar.qss         #   左侧导航栏样式
│       ├── chat.qss            #   聊天区样式
│       └── input.qss           #   底部输入区样式
│
├── docs/
│   ├── ARCHITECTURE.md         # 架构规划方案（DSH 融合）
│   └── DEVELOPMENT_LOG.md      # 开发日志
│
├── .env.example                # 配置模板（复制为 .env 使用）
├── .gitignore                  # Git 忽略规则（.env、providers.json、sessions 等）
└── LICENSE                     # MIT 开源协议
```

## DSH 核心引擎（micro_kernel + harness）

### micro_kernel（微内核）

| 模块 | 职责 |
|------|------|
| `EventBus` | 发布/订阅总线：`on(event, handler)` / `emit(event, *args)`，解耦生产与消费 |
| `ServiceContext` | 轻量服务容器：`set(name, svc)` / `get(name)`，插件间不直接 import |
| `Plugin` + `PluginManager` | 插件基类（`setup`/`teardown` 生命周期）+ 批量装配/停止 |

### harness 插件

| 插件 | 职责 |
|------|------|
| `LLMAdapter` | 封装 LLM 调用，**剥离 thinking**（思考不进工具上下文），规范返回 `LLMResponse` |
| `ToolRegistryPlugin` | 管理全部工具，从 `tools/` 加载内置工具 |
| `ReActLoop` | Agent 主循环：思考 → 调工具 → 再思考，直至最终回答（**可插拔**） |

插件通过事件发布运行过程，上层可订阅：
- `agent.thinking` — 模型思考内容
- `agent.tool_call` — 工具调用（名称、参数）
- `agent.message` — 最终回答

> 核心引擎装配即 `Model + Harness = Agent`：LLM 适配 + 工具注册 + 主循环三者装配成可用 Agent，见 `cli_main.py`。

## 🎨 样式设计（QSS）

界面样式采用 **QSS（Qt Style Sheets）**，即 **Qt 版本的 CSS**，语法与 Web CSS 几乎一致（选择器 + 属性），仅选择器使用 Qt 控件类型与 `objectName`。

### 设计原则

1. **结构与样式分离**：`.ui` 文件只负责布局结构，**样式全部外置到 `ui/styles/*.qss` 文件**，不再内嵌在 `.ui` 的 `styleSheet` 属性里。
2. **分层组织**：样式按界面区域拆分为独立 `.qss` 文件，由 `loader.py` 按序拼接加载，便于维护与换肤。
3. **运行时加载**：样式通过 Qt 原生 `setStyleSheet()` 在程序启动时加载应用。

### 调用机制（如何"加载 CSS 文件"）

> 说明：这个机制**非常简单可靠**，是 Qt 的内置能力，无需任何第三方库。它不是"网页加载 CSS"那种复杂流程，而是 Qt 原生支持的整段样式文本应用。

`app/ui/loader.py` 在加载完 `.ui` 后，按区域顺序拼接 `ui/styles/*.qss` 并应用到窗口：

```python
# app/ui/loader.py 内部
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent.parent / "ui"
STYLE_DIR = UI_DIR / "styles"

# 样式加载顺序：先全局基础，再按界面区域叠加（顺序即优先级）。
_STYLE_FILES = (
    "base.qss",
    "titlebar.qss",
    "sidebar.qss",
    "chat.qss",
    "input.qss",
)

def _apply_style(host) -> None:
    """读取并应用 QSS 样式文件到宿主窗口。"""
    parts = []
    for file_name in _STYLE_FILES:
        path = STYLE_DIR / file_name
        parts.append(path.read_text(encoding="utf-8"))
    host.setStyleSheet("\n".join(parts))
```

> 说明：这里**没有采用 Qt 的 `@import`** 来汇总。因为 Qt 的 `@import` 相对路径是**按工作目录解析**而非按样式文件所在目录，直接使用容易踩坑；改为在代码侧**显式按序拼接**各 `.qss` 文件，路径解析更可靠、加载顺序更可控。

各区域 `.qss` 文件的分工：


### QSS 选择器示例

```css
/* base.qss —— 全局 */
#MainWindow { background-color: #1e1e2e; }
QWidget     { color: #e7e7ef; font-family: "Microsoft YaHei"; }
QScrollBar::handle { background: #3b3b58; border-radius: 4px; }

/* titlebar.qss —— 标题栏 */
#titleBar { background-color: #232334; border-bottom: 1px solid #33334a; }

/* sidebar.qss —— 左侧导航 */
#leftSideBar QListWidget::item:selected { background: #3b3b58; color: #ffffff; }

/* input.qss —— 输入区 */
#inputFrame { background-color: #2a2a3f; border-radius: 10px; }
#btn_send   { background: #7aa2f7; color: #111122; font-weight: bold; }
```

### 换肤 / 多主题

样式已完全外置，**更换主题只需替换 `ui/styles/*.qss` 文件**（或运行时切换加载不同的 QSS），无需改动任何 Python 代码或 `.ui` 结构。

Raven 内置**多套主题配色**（见 `ui/themes.py`），可在运行时一键切换：**深色 / 白色 / 青蓝黄 / 粉色**。每套主题独立定义背景、气泡、高亮等配色，并与 `ui/styles/*.qss` 协同生效。




## 安装

```bash
# 1. 克隆仓库
git clone https://github.com/<你的用户名>/raven.git
cd raven

# 2. 创建并激活虚拟环境（推荐）
python -m venv venv

#   Windows
venv\Scripts\activate
#   Linux / macOS
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt
```

> 依赖：`PySide6`（GUI）、`openai`（LLM API）、`pygments`（代码高亮）、`python-dotenv`（配置）。

## 配置

创建 `.env` 文件（或直接设置环境变量）：

```env
# LLM API 配置（OpenAI 兼容：火山方舟 / DeepSeek / OpenAI / Ollama 均可）
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
OPENAI_TEMPERATURE=0.7
OPENAI_MAX_TOKENS=2048
OPENAI_TIMEOUT=60
```

各供应商的独立 API Key（可选）可参考 `.env.example` 中的说明设置，也可直接在**应用界面的"供应商/模型/API Key"**里按供应商分别保存（持久化到 `providers.json`，不会被提交到仓库）。

> `.env.example` 是配置模板；真实 `.env` 与 `providers.json` 均已由 `.gitignore` 排除，不会提交到仓库。

## 运行

> ⚠️ **务必先激活安装了 PySide6 的环境**。项目依赖 PySide6（见 `requirements.txt`），
> 若在未安装它的 conda 环境（如 `base`）中直接运行，会报
> `ModuleNotFoundError: No module named 'PySide6'`。

```bash
# 激活已安装 PySide6 的环境（按实际环境名）
conda activate Yolo_pyside
# 或： conda activate Pyside
# 或：若用 venv： venv\Scripts\activate
```

**GUI 模式**（桌面聊天界面）：
```bash
python main.py
```

**CLI 模式**（DSH 核心引擎验证，命令行对话 + 工具调用）：
```bash
python cli_main.py
```
## 🚧 开发路线

| 阶段 | 内容 | 状态 |
|------|------|------|
| 阶段一 | DSH 核心引擎（micro_kernel + harness 插件 + CLI 验证） | ✅ 完成 |
| 阶段二 | Skill 管理、会话持久化（JSONL trajectory）、事件日志 | ⬜ 待开发 |
| 阶段三 | UI 桥接（DSH 事件 ↔ Qt 信号）、权限门控、沙箱 | ⬜ 待开发 |
| 阶段四 | MCP 接入、多 Loop 替换、多会话 | ⬜ 待开发 |

> 详细架构设计与演进路线见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)；各阶段开发过程记录见 [`docs/DEVELOPMENT_LOG.md`](docs/DEVELOPMENT_LOG.md)。

## 📄 开源协议

本项目基于 [MIT License](LICENSE) 开源。你可以自由使用、复制、修改、合并、发布、分发、再许可和/或出售软件副本，前提是保留原始版权声明和许可声明。

使用时请自行配置自己的 LLM API Key（存放在 `.env` / `providers.json`，不会提交到仓库），API 调用产生的费用由用户自行承担。

---

**Made with ❤️ by [Spreading123](https://github.com/Spreading123)** — 让 AI 智能如渡鸦般，栖于你的桌面。

