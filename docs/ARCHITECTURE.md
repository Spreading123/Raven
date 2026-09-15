# Raven —— 架构规划方案

> 目标：面向**大型商用场景**的**通用型 Agent 智能体**。
> 原则：**分层清晰、职责单一、模块化、可扩展、可测试**，同时保持简洁优雅、避免过度工程。
>
> **核心引擎方向**：以 **DeepSeek-Harness（DSH）设计思想**为核心引擎，即 **`Model + Harness = Agent`**，一切皆插件、Agent 主循环可插拔、事件总线贯穿、工具/技能/会话/权限分层。
> 复刻自官方 DSH（底层 Cordis TS 微内核），Python 无现成移植，故**复刻设计思想而非源码**。
> 与 LangChain 的根本区别：**Agent 主循环（Loop）本身是插件，可卸载替换，而非框架写死**。

---

## 一、现状诊断（诚实评估）

当前代码是**原型/教学级别**结构，足以跑通功能，但撑不起"大型商用通用型"目标。

### 1.1 当前结构

```
raven/
├── main.py              # 入口（健康，保持精简）
├── config/settings.py   # 配置（.env）
├── app/
│   ├── main_window.py   # ⚠️ 上帝对象：356 行，职责混杂
│   ├── agent/
│   │   ├── agent.py     # ⚠️ Agent 单类，职责过杂
│   │   ├── llm.py       # ⚠️ 仅支持 OpenAI 兼容 + 非流式
│   │   └── tools.py     # 硬编码工具注册
│   ├── ui/loader.py     # .ui 加载
│   └── utils/logger.py
└── ui/main_window.ui
```

### 1.2 核心问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | **MainWindow 是上帝对象**：窗口交互 + 聊天渲染 + Agent 线程 + 业务事件全混在一个类 | 加设置/多会话/插件时无限膨胀 |
| 2 | **业务逻辑与 UI 强耦合**：`_on_send` 既管控件又管线程又管 Agent | 无法复用、无法单测业务 |
| 3 | **Agent 单类职责过杂**：对话状态 + 工具循环 + 中断 + 信号全在一个类 | 无法做多模型/多 Agent/记忆编排 |
| 4 | **LLM 层只支持 OpenAI 兼容 + 非流式** | 商用需要流式打字机、多 provider |
| 5 | **工具硬编码注册** | 无法插件化扩展 |
| 6 | **无状态持久化**：会话只能 reset 清空 | 无法存/载历史 |
| 7 | **无测试、无插件机制、无配置 UI、无重试降级** | 不满足商用基础要求 |

### 1.3 现状与 DSH 融合的关系

现有代码**不是推倒重来**，而是**进化为 DSH 插件**：

| 现有代码 | 进化为 DSH 插件 |
|---------|----------------|
| `app/agent/llm.py`（OpenAI 兼容封装） | `harness/llm_adapter`（含 thinking 剥离） |
| `app/agent/tools.py`（ToolRegistry） | `harness/tool_registry`（含 MCP 接入能力） |
| `app/agent/agent.py`（ReAct 循环） | `harness/agent_loop`（可插拔 Loop 插件） |
| `config/settings.py` | 供 `llm_adapter` 复用 |
| `app/utils/logger.py` | 供所有插件复用 |
| `_AgentWorker(QThread)` + Qt 信号 | `app/bridge.py`（DSH 事件 ↔ Qt 信号桥接） |

---

## 二、目标分层架构

### 2.1 总览（DSH 融合）

```
raven/
├── main.py                        # 入口：组装 App + 装配 DSH 插件 profile
│
├── micro_kernel/                  # 🆕 DSH 微内核（仿 Cordis，零业务逻辑）
│   ├── plugin.py                  #    插件基类（load/unload 生命周期、服务注入）
│   ├── event_bus.py               #    全局事件总线（发布/订阅）
│   └── service_ctx.py             #    服务上下文 + 依赖注入
│
├── harness/                       # 🆕 DSH 核心引擎（全部为插件，纯逻辑、零 UI）
│   ├── llm_adapter/               #    LLM 适配插件（OpenAI 兼容 + thinking 剥离）
│   ├── agent_loop/                #    【核心】可插拔的 Agent 主循环（ReAct 等）
│   ├── tool_registry/             #    工具注册插件（本地函数 + MCP 接入）
│   ├── skill_manager/             #    Skill 管理插件（SKILL.md 解析、技能编排）
│   ├── session_store/             #    会话持久化插件（JSONL trajectory 回放）
│   ├── permission_gate/           #    权限门控插件（bash/文件/网络审批）
│   └── sandbox/                   #    简易沙箱（目录隔离 + subprocess 隔离）
│
├── tools/                         # 内置工具实现（read_file/write_file/bash）
├── skills/                        # SKILL.md 技能包
│
├── app/                           # 🎯 界面层：只负责"怎么显示"
│   ├── ui/
│   │   ├── main_window.py         #    主窗口：组装布局 + 事件路由（不再承载业务）
│   │   ├── frameless.py           # 🆕 无边框窗口基类（缩放/拖动/光标）
│   │   ├── chat_view.py           # 🆕 聊天渲染组件（流式/富文本）
│   │   ├── panels/                # 🆕 各面板（设置/历史/工具）
│   │   └── loader.py              #    .ui 加载
│   ├── bridge.py                  # 🆕 桥接层：DSH 事件 ↔ Qt 信号，QThread 内跑 asyncio
│   └── controllers/               # 🆕 控制器：UI 事件 → 业务调用
│       ├── chat_controller.py
│       └── window_controller.py
│
├── config/
│   └── settings.py                # 配置（复用，供 llm_adapter 等插件读取）
│
├── app/utils/logger.py            # 日志（复用，供所有插件使用）
└── tests/                         # 🆕 测试（核心引擎可脱离 UI 单测）
    ├── unit/
    └── integration/
```

### 2.2 依赖方向（单向，不允许反向）

```
app(ui)  →  app/bridge  →  harness(插件)  →  micro_kernel
                              ↓
                        config / utils
```

- **micro_kernel**：最底层，只提供插件生命周期/事件总线/服务注入，**不含任何 Agent 业务**
- **harness**：所有业务都是插件，**零 UI 依赖**，可独立运行、独立测试、独立复用（可移植到 CLI/Web）
- **bridge**：唯一"懂 UI 又懂 DSH"的适配层，把 DSH 异步事件桥接成 Qt 信号
- **app(ui)**：只做显示与输入收集，不直接碰 harness

> **DSH 精髓落地**：`agent_loop` 是插件。换 `PlanSolve` / `Reflexion` 只改 profile 装配，**不修改任何其它代码**。

### 2.3 各模块职责边界

| 层 | 职责 | 禁止做的事 |
|----|------|-----------|
| **micro_kernel** | 插件生命周期、事件总线、服务注入 | 不得包含 Agent/LLM 业务 |
| **harness/llm_adapter** | 模型通信、流式、thinking 剥离 | 不得包含工具/会话业务 |
| **harness/agent_loop** | 推理编排、工具调用循环 | 不得 import PySide6 控件 |
| **harness/tool_registry** | 工具注册与执行（含 MCP） | 不得依赖 UI |
| **harness/session_store** | 会话/轨迹持久化 | 不得包含推理逻辑 |
| **harness/permission_gate** | 权限审批（bash/文件/网络） | 不得反向依赖 UI |
| **harness/sandbox** | 目录/subprocess 隔离 | 不得包含业务 |
| **bridge** | DSH 事件 ↔ Qt 信号、asyncio ↔ QThread | 不得放业务算法 |
| **app(ui)** | 显示、渲染、输入收集 | 不得直接调 LLM、写存储 |

---

### 2.4 解耦维度与手段

架构的**第一目标**是**高度解耦**。解耦不是"文件多"，而是**各模块之间的依赖尽可能少、方向明确、可独立替换**。DSH 复刻天然提供了强大的解耦能力。下面列出本架构在所有维度上的解耦方式。

#### 2.4.1 分层解耦（结构性解耦）
- 单向依赖：`app(ui) → bridge → harness → micro_kernel`
- **harness 核心引擎完全不依赖 UI**（不 import 任何 PySide6 控件），可脱离界面独立运行、独立测试、独立复用
- 每一层只通过**接口/抽象**与相邻层交互，不直接 new 对方实现

#### 2.4.2 插件解耦（DSH 核心：可插拔性）
- **Agent 主循环（agent_loop）是插件**：ReAct / PlanSolve / Reflexion 都是独立插件，替换只改 profile 装配，**不修改任何其它代码**——这是与 LangChain 的本质区别
- 一切业务（LLM、工具、会话、权限、Skill、沙箱）皆为插件，通过 `load/unload` 生命周期热插拔
- 用 **工厂（Factory）/ profile** 按配置装配插件集合，调用方只依赖服务上下文

#### 2.4.3 事件解耦（时序解耦，DSH 事件总线）
- `micro_kernel/event_bus.py` 提供全局发布-订阅：`agent.step.start` / `agent.done` / `tool_called` / `permission.request`
- **Agent 只发事件，不知道谁在听**；UI/日志/持久化各自订阅
- 通过 **bridge** 把 DSH 事件桥接成 Qt 信号，生产与消费在时间上解耦

#### 2.4.4 数据解耦（状态隔离）
- 会话/轨迹状态归 `harness/session_store`，不散落在 UI 控件里
- UI 只持有"展示用"状态，业务状态归 harness
- 通过 DTO/数据类在层间传递，不互相透传控件对象

#### 2.4.5 技术栈解耦
- harness 核心引擎**零 UI 依赖**，可替换 PySide6 为 CLI/Web，复用同一核心
- `llm_adapter` 支持多 provider（OpenAI 兼容/DeepSeek/Ollama），换模型不影响上层
- 工具注册支持 **MCP 接入**，外部服务可注册为 Tool

#### 2.4.6 解耦的边界（防止过度设计）
高度解耦 ≠ 无限拆分。解耦的**唯一目的**是可独立演化、可替换、可测试。
- 不为"解耦"而引入不必要的接口层（接口有真实多实现时才值得抽象）
- 层内的小模块按内聚分组，不强行拆碎
- 每个解耦点必须回答："它会被替换吗？需要独立测试吗？"——答案为否则不抽象

---

## 三、为什么要这样设计（对应商用/通用目标）

| 商用/通用需求 | 架构支撑（DSH） |
|--------------|---------|
| **模型可切换**（OpenAI/DeepSeek/通义/Ollama） | `harness/llm_adapter` 插件 + provider 抽象 |
| **流式打字机输出** | `llm_adapter` 提供流式 + `chat_view` 增量渲染 |
| **Agent 主循环可替换**（DSH 精髓） | `harness/agent_loop` 是插件，ReAct/PlanSolve/Reflexion 可插拔 |
| **工具插件化扩展** | `harness/tool_registry` 插件 + `@tool` + **MCP 接入** |
| **技能编排（Skill）** | `harness/skill_manager` 解析 SKILL.md，组合 Tool+prompt |
| **会话/轨迹持久化** | `harness/session_store`（JSONL trajectory 回放） |
| **安全与权限** | `harness/permission_gate` + `harness/sandbox`（目录隔离） |
| **UI 永不膨胀** | `main_window.py` 只做显示，业务全在 harness 插件 |
| **可测试、可回归** | harness 核心零 UI 依赖，可纯单测；`tests/` 独立 |
| **可移植**（CLI/Web/GUI 复用同一核心） | harness 与 UI 完全解耦，靠 `bridge` 桥接 |
| **代码简洁可维护** | 微型内核 + 插件化，避免上帝对象与过度工程 |

---

## 四、演进路线（分阶段，不一次到位）

> 原则：**每阶段可独立交付、可验证、可回退**，避免大规模重构风险。

### 阶段一：DSH 核心引擎（最小可用，纯 CLI 验证）
**目标**：跑通 `Model + Harness = Agent`，核心引擎可独立运行，不碰 UI。
- [ ] `micro_kernel/`：plugin / event_bus / service_ctx 三件套
- [ ] `harness/llm_adapter`：OpenAI 兼容 + thinking 剥离
- [ ] `harness/agent_loop`：ReAct 插件（可插拔）
- [ ] `harness/tool_registry` + `tools/`（read_file/write_file/bash）
- [ ] `main.py`：profile 装配，CLI 跑通
- **验证**：命令行输入任务 → Agent 思考 → 调工具 → 输出结果

### 阶段二：Skill / 会话 / 事件日志
**目标**：补足编排与可观察性。
- [ ] `harness/skill_manager`：SKILL.md 解析、技能加载
- [ ] `harness/session_store`：JSONL trajectory 持久化 + 回放
- [ ] 事件总线接入日志输出
- **验证**：技能可加载、会话可回放

### 阶段三：UI 桥接 + 权限 + 沙箱
**目标**：接入现有 Qt 界面，补足安全。
- [ ] `app/bridge.py`：DSH 事件 ↔ Qt 信号，QThread 内跑 asyncio
- [ ] 改造 `main_window.py`：瘦身为纯显示 + 桥接
- [ ] `harness/permission_gate`（人工确认走 UI 事件回调）
- [ ] `harness/sandbox`（目录隔离）
- **验证**：GUI 正常对话，权限弹窗、沙箱生效

### 阶段四：商用扩展
**目标**：MCP、多 Loop 替换、多会话。
- [ ] MCP Client 接入（外部服务注册为 Tool）
- [ ] 实现第二套 Loop（PlanSolve），证明主循环可插拔
- [ ] 多会话管理、设置面板、测试
- **验证**：可替换 Loop 不改其它代码；MCP 工具可用

---

## 五、风险评估与对策

| 风险 | 对策 |
|------|------|
| 一次性大重构易引入回归 | **分阶段**，每阶段独立验证、可回退 |
| 分层过深导致代码碎片化 | 阶段一只搭最小内核 + 必要插件，保持克制；不为模块化而模块化 |
| **异步模型不匹配**：DSH 是 asyncio，Qt 是事件循环 | bridge 在 `QThread` 内 `asyncio.run()` 驱动；用队列信号桥回 UI 线程（不混用两种循环） |
| **权限人工确认需要 UI**：GUI 下无法用 input() | `permission_gate` 发 `permission.request` 事件，UI 订阅后返回结果，**事件解耦不反向依赖** |
| **Windows 无 Landlock 内核沙箱** | 用目录隔离 + subprocess 隔离的简易沙箱；真沙箱留 Linux 部署 |
| Agent 与 UI 解耦后事件设计复杂 | 用 `event_bus` + bridge 统一定义/翻译事件 |
| 流式输出改动渲染层 | `chat_view` 预留增量渲染接口，阶段三再实现 |
| 依赖关系被打破（反向依赖） | 用分层规则 + import 检查约束 |

---

## 六、待决策事项

1. **存储后端**：`session_store` 的 trajectory 用 JSONL（阶段二先做）还是直接 SQLite？（建议 JSONL 起步，可回放，SQLite 商用化再上）
2. **模型 provider 范围**：首发支持哪些？（建议先 OpenAI 兼容 + 流式，再扩 DeepSeek/Ollama）
3. **thinking 块剥离策略**：剥离的思考内容存 session 但**不送入工具调用上下文**（DSH 规范）
4. **权限门控默认策略**：bash/写文件默认允许 / 默认拒绝 / 每步询问？（建议每步询问，GUI 下弹确认框）
5. **sandbox 边界**：Windows 上目录隔离范围（workspace 目录白名单）
6. **是否引入依赖注入/工厂**：目前工厂 + profile 装配足够，避免过度设计
7. **UI 是否保留 .ui 文件方案**：还是逐步改为代码构建控件（利于动态面板）

---

*本文档为架构规划稿（DSH 融合方案），待审阅后再进入阶段一实现。*
