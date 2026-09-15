# 开发日志（DEVELOPMENT LOG）

> 记录 **Raven**（原 Desktop Agent）从原型到 DSH 架构演进的完整开发过程。
> 每个阶段按「目标 → 实现 → 关键决策 → 踩坑与解决 → 验证」记录。
> 配套文档：架构规划见 [`ARCHITECTURE.md`](ARCHITECTURE.md)，项目说明见 [`../README.md`](../README.md)。

---

## 阶段 0 · 原型搭建（Initial commit）

**提交**：`f92c1f6` — Initial commit: Desktop Agent - 无边框桌面AI助手

### 目标
搭出第一版可运行的桌面聊天原型：无边框深色主窗口 + 基础 Agent 对话。

### 实现
- **PySide6 无边框主窗口**：`app/main_window.py`，含自定义标题栏、左侧导航栏、右侧聊天区、底部输入栏。
- **Agent 对话核心**：`app/agent/`（`agent.py` 对话管理、`llm.py` LLM 客户端、`tools.py` 工具注册表）。
- **配置管理**：`config/settings.py`，从 `.env` 读取 API key 与模型参数。
- **UI 加载**：`app/ui/loader.py` 用 QUiLoader 运行时加载 `ui/main_window.ui`。
- **日志工具**：`app/utils/logger.py`。

### 关键决策
- 采用 **`.ui` 文件 + QUiLoader 运行时加载**而非 `pyuic6` 预编译，便于迭代布局。
- LLM 调用放独立线程，避免阻塞 UI。

### 验证
- GUI 可启动并完成基础对话。

---
## 阶段 1 · 架构规划：DSH 融合方案

**提交**：`4801018` — docs: 新增架构规划方案（DSH 融合：Model + Harness = Agent 核心引擎）

### 目标
为商用级 Agent 演进做顶层架构设计，确立以 **DeepSeek-Harness（DSH）** 为演进方向。

### 实现
- 新增 `docs/ARCHITECTURE.md`，确立核心理念 **`Model + Harness = Agent`**：
  - 模型提供智能，Harness 提供执行框架（工具、循环、状态）。
  - **一切皆插件**：LLM 适配、工具注册、主循环都是插件。
  - **主循环可插拔**：可替换 ReAct / PlanSolve 等。
- 划分演进阶段（阶段一核心引擎 → 阶段二 Skill/会话 → 阶段三 UI 桥接/权限 → 阶段四 MCP）。

### 关键决策
- 坚持「**简洁优雅、可读可维护、性能高效、装饰器只做横切、并发谨慎**」的行业代码规范。
- 明确 UI 与 harness 解耦：harness 纯逻辑、零 UI 依赖。

---

## 阶段 2 · QSS 样式拆分（样式与结构分离）

**提交**：`5c97d75` — refactor(ui): 将 QSS 样式从 .ui 内嵌拆分为独立分文件

### 目标
让样式可维护、可换肤，摆脱 `.ui` 内嵌 13 处 styleSheet 的混乱。

### 实现
- 将 `ui/main_window.ui` 内嵌的 13 处 `styleSheet` 全部移除（526 → 468 行），样式外置。
- 新增 `ui/styles/` 目录，按界面区域拆分为 5 个 `.qss`：
  `base.qss`（全局）、`titlebar.qss`（标题栏）、`sidebar.qss`（导航栏）、`chat.qss`（聊天区）、`input.qss`（输入区）。
- `app/ui/loader.py` 增加 `_apply_style()`：按序拼接各 `.qss` 并 `setStyleSheet()`。

### 关键决策 / 踩坑
- **Qt `@import` 的路径坑**：Qt 的 `@import url("base.qss")` 相对路径按**工作目录**解析，而非样式文件所在目录，极易踩坑。
  → **放弃 `@import` 汇总方案**，改为在 loader 代码里**显式按序拼接**（`_STYLE_FILES` 元组），路径解析更可靠、顺序即优先级。因此删除了汇总入口 `main.qss`。

### 验证
- offscreen 模式加载窗口 + 应用样式，样式正确生效。

---
## 阶段 3 · 运行环境修复 + 闭源商用定位

**提交**：`1f6c717` — docs: 补充运行环境说明并移除开源许可证（闭源商用路线）

### 目标
解决运行环境问题，明确项目的商用闭源定位。

### 实现
- **README 补充运行环境说明**：明确指出**必须激活安装了 PySide6 的环境**（如 `Yolo_pyside`）才能运行 `python main.py`。
- **移除 `## 许可证` + MIT**：项目转向**闭源商用**路线，不再声明开源许可。

### 踩坑 / 关键发现
- **base 环境无 PySide6**：在 `base` conda 环境直接 `python main.py` 报
  `ModuleNotFoundError: No module named 'PySide6'`；`Yolo_pyside` 环境装有 PySide6 6.11.1。
- **编码坑**：用 PowerShell `Get-Content`/`Set-Content` 处理含中文/emoji 的文本会破坏 UTF-8（emoji 变 `鈽?` 乱码、XML 损坏）。
  → **必须用 Python `io.open(encoding='utf-8')` 读写**。

---

## 阶段 4 · DSH 核心引擎（阶段一）

**提交**：`2b76a25` — feat(harness): 搭建 DSH 阶段一核心引擎（micro_kernel + harness 插件）

### 目标
落地 DSH 阶段一：搭建核心引擎，实现 `Model + Harness = Agent`，并经 CLI 端到端验证。

### 实现
- **`micro_kernel/`（DSH 微内核，零业务逻辑）**
  - `event_bus.py`：发布/订阅总线（`on`/`off`/`emit`），解耦生产与消费。
  - `service_ctx.py`：轻量服务容器（`set`/`get`/`has`），插件间不直接 import。
  - `plugin.py`：`Plugin` 基类 + `PluginManager`（`setup`/`teardown` 生命周期）。
- **`harness/`（核心引擎，全部为插件、纯逻辑、零 UI）**
  - `llm_adapter.py`：LLM 适配插件，复用现有 LLMClient，**剥离 thinking**（思考不进工具上下文），返回规范 `LLMResponse`。
  - `tool_registry.py`：工具注册插件，加载 `tools/` 内置工具。
  - `agent_loop.py`：**ReAct 主循环插件**（DSH 精髓——主循环本身可插拔），通过事件发布 `agent.thinking` / `agent.tool_call` / `agent.message`。
- **`tools/builtins.py`**：内置工具 `read_file` / `write_file`，带**路径沙箱**（限制在 workspace 内，越界拦截）。
- **`cli_main.py`**：CLI 入口，装配 `Model + Harness = Agent`。
- **`.env` 写入真实 API**（火山方舟 Ark，OpenAI 兼容）：`ark.cn-beijing.volces.com/api/plan/v3` + `deepseek-v4-flash`。

### 关键决策 / 踩坑
- **API key 安全**：真实 key 只写入 `.env`，`.env` 已被 `.gitignore` 排除，**绝不提交**；只提交 `.env.example` 模板（并补上 `OPENAI_TIMEOUT`）。
- **装饰器克制**：仅用于事件订阅等横切逻辑，不滥用。
- **路径沙箱**：`_resolve_path()` 用 `path.is_relative_to()` 拦截越界访问（Windows 简化实现，正式沙箱待阶段三）。
- **thinking 剥离**：`LLMAdapter.chat()` 从响应剥离 `reasoning_content`，不进入对话历史，避免污染工具调用上下文。

### 验证（真实 API 端到端）
1. ✅ API 连通：真实模型正常回复。
2. ✅ **全链路 ReAct**：让 Agent「写一个 greeting.txt」→ 模型自主完成
   「思考 → 调 `write_file` → 再思考 → 最终回答」，且 **`greeting.txt` 真的写入了**。
3. ✅ 工具沙箱：越界路径被拦截。
4. ✅ 事件总线 / 插件装配：全部正确。

---
## 待决策事项（Blocked / 阶段二前拍板）

| # | 决策项 | 选项 |
|---|--------|------|
| 1 | 会话/轨迹存储后端 | JSONL vs SQLite |
| 2 | Provider 支持范围 | 仅火山方舟 vs 多 Provider |
| 3 | thinking 剥离策略 | 已默认剥离，是否开放保留配置 |
| 4 | 权限门控默认策略 | 全部放行 vs 逐项确认 |
| 5 | 沙箱边界 | workspace 内 vs 系统级（阶段三定） |
| 6 | 依赖注入取舍 | ServiceContext vs 构造注入 |
| 7 | UI 是否保留 `.ui` 方案 | `.ui`+loader vs 纯代码 |

---

## 阶段 5 · DSH 接入 GUI（桥接层，阶段三第一步）

**目标**：把已验证的 DSH 核心引擎（harness + micro_kernel）接入桌面 GUI，让主窗口
复用插件化引擎并获得文件读写等能力，完成架构规划 `app/bridge.py`（阶段三）的第一步。

### 实现
- **新增 `app/bridge.py`（`DSHBridge`）**：唯一"懂 UI 又懂 DSH"的适配层——
  - 内部装配 `LLMAdapter` + `ToolRegistryPlugin` + `ReActLoop`（与 `cli_main` 相同的插件组合）
  - 对外暴露与旧 `app/agent/Agent` **完全一致**的接口与信号
    （`message_ready` / `tool_called` / `finished` / `error`，及 `process` / `reset` /
    `tool_names` / `request_interrupt` / `shutdown`），使 main_window 无需感知底层是插件化引擎
  - 通过 `EventBus` 订阅 DSH 事件（`EVENT_MESSAGE` / `EVENT_TOOL_CALL`），转发为 Qt 信号
- **改造 `app/main_window.py`**（最小侵入，仅 4 处）：
  - import `Agent` → `DSHBridge`
  - `_AgentWorker` 类型注解 `Agent` → `DSHBridge`
  - `self.agent = Agent(self)` → `self.agent = DSHBridge(self)`
  - `closeEvent` 末尾新增 `self.agent.shutdown()` 清理插件资源

### 关键决策 / 踩坑
- **避免"线程套线程"**：架构设想 bridge 在 `QThread` 内跑 asyncio，但当前 `ReActLoop.run()`
  是**同步阻塞**（非 asyncio）。故 bridge 的 `process()` 采用**同步**实现，线程管理**复用**
  MainWindow 已有的 `_AgentWorker`（QThread），本类不额外开线程——更简洁、贴合"不过度设计"。
- **事件跨线程安全**：DSH 事件在 worker 线程内 emit 为 Qt 信号，MainWindow 的连接采用
  默认连接方式（跨线程自动转为队列连接），与旧 `Agent` 的线程模型一致，无需改动 UI 连接。
- **不访问私有属性**：`tool_names()` 通过 `ToolRegistryPlugin.names()` 获取，而非 `loop._tools`，
  保持可读可维护。
- **死代码**：替换后 `app/agent/agent.py` 的旧 `Agent` 类已无引用者（`llm.py`/`tools.py`
  仍被 DSH 复用），待后续决定是否删除。

### 验证（offscreen + 真实 API 端到端）
1. ✅ GUI + DSH 桥接装配：`MainWindow()` 成功创建，`tool_names()` 返回 `['read_file', 'write_file']`
2. ✅ **真实 API 闭环**：offscreen 下经 `DSHBridge.process()` 让 Agent「写 gui_test.txt」→
   收到 `tool_called(write_file, {...})` + `message_ready(成功)`，且文件**真实写入**
   （内容 `GUI-DSH-OK`）——证明 GUI 路径已跑通 DSH 引擎全链路
3. ✅ 依赖方向单向：`app(ui) → bridge → harness → micro_kernel`，harness 零 UI 依赖

### 对照架构的满足度（诚实评估）
- ✅ **满足**：依赖方向、分层解耦、bridge 定位、harness 零 UI 依赖、MainWindow 瘦身为纯显示+桥接
- ⚠️ **部分满足**：架构设想 bridge 内 `QThread + asyncio` 驱动，当前因引擎为同步故未引入 asyncio
- ❌ **未做**（阶段三其余项）：权限门控 `permission_gate`（文件写操作无弹窗确认）、正式 `sandbox`
  插件（仅保留 `tools/builtins.py` 的简易路径沙箱）、`agent.thinking` 事件桥接到 GUI

---
## 阶段 6 · UI 改进（窗口圆角 / 对话字体撞色 / 手型光标）

**目标**：三项桌面体验改进——① 窗口边缘小圆角过渡；② 修复白色/粉色主题对话字体
「深浅撞色」问题；③ 左侧栏项目与全部可选项目统一手型光标。

### 实现
- **① 窗口圆角**：
  - `app/main_window.py`：`WA_TranslucentBackground` 由 `False` → `True`
  - `ui/styles/base.qss`：`#MainWindow` 加 `border-radius`（后按反馈调为 **10px**）
  - **⚠️ 后修正（提交 `ace3465`）**：圆角最初只加在 `#MainWindow` 上，但被
    `titleBar` / `leftSideBar` / `rightMainFrame` 三个**不透明矩形面板**盖住而不可见。
    解决：给四面板分别补对应角圆角——`titleBar` 上左+上右、`leftSideBar` 左下、
    `rightMainFrame` 右下，并按用户反馈从 12px 调小到 **10px**。
- **② 对话字体撞色修复**（`ui/themes.py`，仅改对话文字键，不影响按钮等 UI）：

  | 主题 | 键 | 原值 | 新值 | 原因 |
  |------|----|------|------|------|
  | light | `user` | `#4a7df0` | `#2f5fd0` | 加深蓝，浅底对比更强 |
  | light | `tool` | `#7a828c` | `#5a6470` | 加深灰蓝，与背景/user 区分 |
  | pink  | `user` | `#ff6fa5` | `#d6336c` | 深玫红，浅粉底不再撞色 |
  | pink  | `tool` | `#b06a83` | `#9c4a63` | 沉稳深粉棕，与 user 区分 |

- **③ 手型光标全铺开**（`app/ui/loader.py`）：
  - `_apply_button_cursors` → `_apply_clickable_cursors`，覆盖 `QPushButton` / `QToolButton` /
    `QListWidget`（左侧导航 `list_nav` + 历史 `list_history`）/ `QComboBox` / `QCheckBox` / `QRadioButton`

### 关键决策 / 踩坑
- **无边框窗口圆角必须开透明背景**：仅 QSS 加 `border-radius` 而不开 `WA_TranslucentBackground`，
  圆角不会真正裁剪露出（背景仍是矩形色块）。改为 `True` 后四角露出桌面，圆角才可见。
- **PySide6 `findChildren((QWidget,))` 报错**：传单元素元组触发
  `Subscripted generics cannot be used with class and instance checks`，改为 `findChildren(QWidget)`。
- **QSS 不支持 `cursor`**：沿用既有方案，用 Qt 原生 `setCursor` 批量设置。
- **顺序安全**：`_apply_clickable_cursors`（设手型 → 置 `WA_SetCursor`）先于
  `_install_edge_filter`（把未显式设光标的控件置箭头）执行，故可点击控件的手型不被覆盖。

### 验证（offscreen）
1. ✅ 圆角：`WA_TranslucentBackground=True`，四面板补角方案生效，圆角为 **10px**
2. ✅ 字体：light/pink 的 `user`/`tool` 已加深，四主题渲染全部 OK
3. ✅ 光标：按钮手型 8/8、列表（导航+历史）手型 2/2

---
## 阶段 7 · 远程同步 + 流式输出真机验证

**提交（远程拉取）**：`f97820b`（feat(stream) 流式输出）、`781af58`（chore(build) Nuitka 打包 + 死代码清理）

### 目标
拉取 Gitee 远程最新代码，并把远程新增的「LLM 最终回答流式输出」在 GUI 真机链路上验证跑通，
确认无误后再决定 bridge 线程所有权重构。

### 远程新功能（来自 `f97820b` / `781af58`）
- **流式输出（`feat(stream)`）**：LLM 最终回答逐块实时显示。
  - `app/agent/llm.py`：`chat()` 支持 `stream=True`，返回逐块迭代器
  - `harness/llm_adapter.py`：新增 `chat_stream()`，逐块回调正文增量（思考/工具增量仅累积不回调）
  - `harness/agent_loop.py`：新增 `EVENT_CHUNK` 事件 + `_on_chunk` 回调，`run()` 改用 `chat_stream`
  - `app/bridge.py`：新增 `message_chunk` 信号并转发 `EVENT_CHUNK`
  - `app/main_window.py`：`add_agent_chunk` / `_begin_stream` / `_end_stream` 逐块填充同一气泡
- **Nuitka 打包支持（`chore(build)`）**：新增 `app/utils/paths.py`、`build_exe.ps1`，
  路径适配 + 死代码清理（`tools.py` 精简到 56 行，`Tool`/`ToolRegistry` 保留）。

### 关键决策
- **拉取方式**：远程是本地 HEAD 的直接后代，用 `git merge --ff-only` 快进到 `781af58`，
  无冲突；用户明确「以远程覆盖本地」。
- **验证策略**：不弹窗，分两层验证——① 直接驱动 harness 引擎订阅 `EVENT_CHUNK` 验证
  底层流式链路；② `QT_QPA_PLATFORM=offscreen` 启动 MainWindow 验证 Qt 信号 → 渲染全链路。

### 验证（真实火山方舟 API + offscreen）
1. ✅ **底层流式链路**：`EVENT_CHUNK` 触发 **31 次**（流式逐块到达），流式拼接与最终回答
   `EVENT_MESSAGE` **完全一致**（54 字符），thinking 1 次，全程无异常。
2. ✅ **GUI 流式渲染链路**（offscreen + 真实 API）：`message_chunk` 信号触发 **28 次**逐块
   转发，`message_ready` 收尾 1 次，`chatContentView` 文本 79 字符，`_stream_cursor` 正常收尾
   （None），状态栏回「就绪」，**PASS**。
3. ⚠️ **环境性警告（非功能问题）**：offscreen 下 PySide6 报 `Cannot find font directory`——
   仅离屏平台无自带字体目录；真实窗口由 `main.py` 显式 `setFont("Microsoft YaHei UI")` 不受影响。
   另 PowerShell 把 stderr 的 NativeCommandError 误判为退出码 1（`$LASTEXITCODE` 坑），非脚本失败。

### 结论
流式输出在 GUI 真机链路**验证跑通**（火山方舟 → `EVENT_CHUNK` → bridge `message_chunk`
→ `QTextBrowser` 逐块渲染 → 正常收尾）。GUI 可升级为「流式打字机」体验。
bridge 线程所有权重构（QThread + asyncio）留待下一步，因远程刚在现有同步模型上加了流式，
动线程归属需谨慎，待用户拍板。


---

## 后续规划

- **阶段二**：Skill 管理、会话持久化（JSONL trajectory）、事件日志。
- **阶段三（进行中）**：✅ UI 桥接（`app/bridge.py`，已完成第一步）→ ⬜ `agent.thinking`
  事件桥接、权限门控（`permission_gate`）、正式沙箱（`sandbox`）。
- **阶段四**：MCP 接入、多 Loop 替换、多会话。



