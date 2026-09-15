"""主窗口：加载 main_window.ui，承载 Agent 线程与界面交互。

采用无边框（frameless）设计，自带自定义标题栏，风格参考经典深色 agent 界面。
"""
from __future__ import annotations

import base64
import os

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLayoutItem,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.bridge import DSHBridge
from app.ui.bubbles import AssistantBubble
from app.ui.chat_view import ChatView
from app.ui.loader import apply_theme, current_theme, load_ui, theme_names
from app.utils.logger import get_logger
from app.utils import session_store
from config.provider_store import get_api_key, save_api_key
from config.settings import PROVIDERS, config
from ui.themes import THEME_LABELS, THEMES

logger = get_logger(__name__)

# 附件上传的软限制
_MAX_ATTACHMENTS = 20          # 最多附件数
_MAX_TEXT_BYTES = 200_000      # 单个文本文件大小上限（字节）
_MAX_IMAGE_BYTES = 10_000_000  # 单个图片文件大小上限（字节）
_ATTACH_BAR_MAX_HEIGHT = 96    # 附件容器最大高度

# 图片扩展名 -> MIME 类型（用于构造 data URL 多模态内容块）
_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


class _AgentWorker(QThread):
    """在独立线程中运行 Agent 处理，避免阻塞 UI。

    关闭窗口时会请求中断，Agent 在下一轮循环前响应并退出，
    从而避免“线程仍在运行却被销毁”导致的崩溃。
    """

    def __init__(self, agent: DSHBridge, text: str | list, parent=None) -> None:
        super().__init__(parent)
        self._agent = agent
        # text 可为纯文本字符串，也可为 OpenAI 内容块数组（多模态：文本 + 图片）
        self._text = text

    def run(self) -> None:
        if self.isInterruptionRequested():
            return
        # process 内部已处理异常并发出 error/finished 信号
        self._agent.process(self._text)


class _FlowLayout(QLayout):
    """简单的可换行流式布局（Qt 官方示例精简版）。

    用于附件 chip：一行放不下时自动换到下一行，天然支持多文件并列且不挤爆。
    """

    def __init__(self, spacing: int = 6, parent=None) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setSpacing(spacing)

    def addItem(self, item: "QLayoutItem") -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        """逐项摆放，超宽换行；test_only 时只计算高度不实际设置几何。"""
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x = effective.x()
        y = effective.y()
        line_height = 0
        spacing = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width()
            if next_x > effective.right() + 1 and line_height > 0:
                # 换行
                x = effective.x()
                y = y + line_height + spacing
                next_x = x + hint.width()
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x + spacing
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


class _FlowHost(QWidget):
    """承载 _FlowLayout 的宿主控件。

    把 hasHeightForWidth / heightForWidth / sizeHint / minimumSize 转发给内部的
    流式布局，使 QScrollArea(widgetResizable=True) 能随内容换行自动增高，
    并在超过上限高度时出现滚动条（否则普通 QWidget 不会把布局的
    heightForWidth 反馈给 QScrollArea，多文件会撑爆或无法滚动）。
    """

    def __init__(self, flow: _FlowLayout, parent=None) -> None:
        super().__init__(parent)
        self._flow = flow
        self.setLayout(flow)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._flow.heightForWidth(width)

    def sizeHint(self) -> QSize:
        return self._flow.sizeHint()

    def minimumSize(self) -> QSize:
        return self._flow.minimumSize()


class _HistoryItemWidget(QFrame):
    """历史会话列表项的自定义 widget：彩色圆形图标 + 省略号标题 + hover 更多按钮。

    用 QListWidget.setItemWidget 嵌入列表，比纯文本 item 更美观、交互更丰富：
      - 左侧彩色圆形图标（按会话索引循环取色），中间对话符号；
      - 标题过长时右侧省略号（QFontMetrics.elidedText）；
      - hover 时右侧浮现「⋯」更多按钮，点击弹出 重命名 / 删除 菜单；
      - 选中态通过 set_selected 手动维护（QSS :selected 对 itemWidget 不生效）。
    """

    more_clicked = Signal(int)  # 发送会话索引

    _COLORS = [
        "#6C5CE7", "#00B894", "#E17055", "#0984E3", "#FDCB6E",
        "#A29BFE", "#55EFC4", "#FF7675", "#74B9FF", "#FFEAA7",
        "#D63031", "#00CEC9", "#6C5CE7", "#E84393", "#00B894",
    ]

    def __init__(self, title: str, session_idx: int, parent=None) -> None:
        super().__init__(parent)
        self._session_idx = session_idx
        self.setObjectName("historyItemWidget")
        self.setProperty("selected", False)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 8, 6)
        layout.setSpacing(8)

        # 图标：彩色圆形 + 对话符号
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(22, 22)
        self.icon_label.setPixmap(self._make_icon(session_idx))
        layout.addWidget(self.icon_label)

        # 标题（过长右侧省略号，通过 resizeEvent + QFontMetrics 实现）
        self._full_title = title
        self.title_label = QLabel(title)
        self.title_label.setObjectName("historyItemTitle")
        self.title_label.setWordWrap(False)
        self.title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self.title_label, 1)

        # 更多按钮（hover 时显示，默认隐藏）
        # 外观样式（颜色/背景）定义在 sidebar.qss 的
        # #historyItemWidget QPushButton 规则里，跟随主题变量（$text_muted/$text/$bg_hover2）。
        self.more_btn = QPushButton("\u22ef")
        self.more_btn.setFixedSize(22, 22)
        self.more_btn.setCursor(Qt.PointingHandCursor)
        self.more_btn.setToolTip("更多操作")
        self.more_btn.hide()
        self.more_btn.clicked.connect(self._on_more)
        layout.addWidget(self.more_btn)

        self.setMouseTracking(True)
        self.more_btn.setMouseTracking(True)

    def _make_icon(self, idx: int) -> "QPixmap":
        """生成彩色圆形会话图标。"""
        color = QColor(self._COLORS[idx % len(self._COLORS)])
        pix = QPixmap(22, 22)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 22, 22)
        painter.setPen(QColor("#FFFFFF"))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "\U0001f4ac")
        painter.end()
        return pix

    def enterEvent(self, event) -> None:  # noqa: N802
        """鼠标进入 widget：显示更多按钮。"""
        self.more_btn.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        """鼠标离开 widget：延迟隐藏更多按钮。

        不能直接 hide()：鼠标从主区域移到「⋯」按钮的瞬间，widget 会先收到
        leaveEvent，而按钮的 underMouse() 状态更新往往滞后，若立即判断会导致
        按钮刚显示就被隐藏（点击不到）。改为延时后重新检查鼠标位置，避免时序竞争。
        """
        QTimer.singleShot(80, self._maybe_hide_more)
        super().leaveEvent(event)

    def _maybe_hide_more(self) -> None:
        """延时后确认鼠标确实不在 widget/按钮上再隐藏更多按钮。"""
        if not self.underMouse() and not self.more_btn.underMouse():
            self.more_btn.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        """大小变化时重新计算标题省略号。"""
        super().resizeEvent(event)
        self._elide_title()

    def showEvent(self, event) -> None:  # noqa: N802
        """显示时计算一次省略号（初始宽度可能为 0）。"""
        super().showEvent(event)
        self._elide_title()

    def _on_more(self) -> None:
        self.more_clicked.emit(self._session_idx)

    def update_title(self, title: str) -> None:
        self._full_title = title
        self._elide_title()

    def _elide_title(self) -> None:
        """根据当前宽度用 QFontMetrics 计算省略号文本。"""
        if not hasattr(self, "_full_title"):
            return
        fm = QFontMetrics(self.title_label.font())
        available = self.title_label.width() - 4
        if available <= 0:
            return
        elided = fm.elidedText(self._full_title, Qt.TextElideMode.ElideRight, available)
        self.title_label.setText(elided)

    def set_selected(self, selected: bool) -> None:
        """设置选中态：更新 QSS property + 标题加粗。"""
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        font = self.title_label.font()
        font.setBold(selected)
        self.title_label.setFont(font)

    def update_index(self, idx: int) -> None:
        """会话索引变化时更新（删除会话后索引会变）。"""
        self._session_idx = idx
        self.icon_label.setPixmap(self._make_icon(idx))



class MainWindow(QWidget):
    """应用主窗口（无边框，支持边缘拖拽缩放）。"""

    # 缩放方向位掩码
    _EDGE_NONE = 0
    _EDGE_LEFT = 1
    _EDGE_RIGHT = 2
    _EDGE_TOP = 4
    _EDGE_BOTTOM = 8
    _RESIZE_MARGIN = 6  # 触发缩放的边缘像素宽度（越大越灵敏）

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        load_ui("main_window.ui", self)

        # 聊天区：ChatView（QListWidget + 自定义气泡 widget），放进 chatContainer
        self.chat_view = ChatView(self._palette(), current_theme(self), self)
        self.chat_view.copy_requested.connect(self._on_copy_message)
        self.chat_view.redo_requested.connect(self._on_redo_message)
        self.chat_view.share_requested.connect(self._on_share_message)
        self.chat_view.suggestion_clicked.connect(self._on_suggestion_clicked)
        container_layout = QVBoxLayout(self.chatContainer)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(self.chat_view)
        # chatContainer 明确背景色，避免透明视口边缘线
        self.chatContainer.setStyleSheet(f"background-color:{self._palette()['bg']};")
        # 流式期间的助手气泡引用
        self._stream_bubble: AssistantBubble | None = None

        self.agent = DSHBridge(self)
        self._worker: _AgentWorker | None = None
        # 待上传附件及其对应的 UI chip
        self._pending_attachments: list[dict[str, str]] = []
        self._attach_chips: list[tuple[dict, object, object, object]] = []
        self._drag_pos = None
        self._resize_dir = self._EDGE_NONE
        self._resize_start_geo = None
        # 会话数据：消息、标题、id、当前索引
        self._sessions: list[list[tuple[str, str]]] = []
        self._session_titles: list[str] = []
        self._session_ids: list[str] = []
        self._current_idx: int | None = None
        # 流式期间累积的助手文本
        self._stream_text: str = ""

        self.list_nav.setCurrentRow(0)  # 默认选中第一项"对话任务"
        # 导航栏：关闭滚动条，高度随内容自适应，全部项完整并列显示
        self.list_nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_nav.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents
        )
        self._init_provider_ui()
        self._build_attach_bar()
        self._connect_signals()
        self._set_tool_names()
        self._install_edge_filter()
        self._align_sidebar_width()
        # 历史列表隐藏滚动条（内容不多，不需要滚动）
        self.list_history.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 从磁盘恢复历史会话（会话持久化：启动加载）
        self._load_persisted_sessions()

        # Agent 信号 -> UI（跨线程自动转为队列连接）
        self.agent.message_ready.connect(self.add_agent_message)
        self.agent.message_chunk.connect(self.add_agent_chunk)
        self.agent.tool_called.connect(self.add_tool_message)
        self.agent.error.connect(self._on_error)
        # 不连接 agent.finished，避免与 worker.finished 重复触发
        # 初始显示欢迎界面
        self.chat_view.show_welcome()

    def _connect_signals(self) -> None:
        # 标题栏
        self.btn_min.clicked.connect(self.showMinimized)
        self.btn_max.clicked.connect(self._toggle_maximize)
        self.btn_close.clicked.connect(self.close)
        self.btn_toggle_sidebar.clicked.connect(self._toggle_sidebar)
        self.btn_theme.clicked.connect(self._on_theme_menu)
        # 输入与发送
        self.btn_send.clicked.connect(self._on_send)
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_new.clicked.connect(self._on_new)
        self.list_nav.itemClicked.connect(self._on_nav_clicked)
        # 历史会话列表：点击切换会话 + 选中态联动
        self.list_history.itemClicked.connect(self._on_history_clicked)
        self.list_history.currentRowChanged.connect(self._on_history_selection_changed)
        # 供应商 / 模型 / API Key 选择
        self.combo_provider.currentIndexChanged.connect(self._on_provider_changed)
        self.combo_model.currentIndexChanged.connect(self._on_model_changed)
        self.edit_api_key.editingFinished.connect(self._on_api_key_edited)
        self.edit_base_url.editingFinished.connect(self._on_base_url_edited)
        self.btn_save_key.clicked.connect(self._on_save_key)
        self.btn_upload.clicked.connect(self._on_upload_file)
        # 输入框：回车发送、Shift+Enter 换行
        self.edit_input.installEventFilter(self)

    # ---- 附件待上传卡片（输入框上方的大图标附件）----

    def _build_attach_bar(self) -> None:
        """在输入框上方构建「待上传附件」容器（初始隐藏）。

        用可换行的流式布局容纳多个紧凑 chip，多个文件自然并列、超出宽度自动换行；
        容器限定最大高度，文件过多时出现滚动条，绝不挤压输入框。
        """
        bar = QFrame(self.inputFrame)
        bar.setObjectName("attachBar")
        self.attach_bar = bar
        # 关键：垂直方向设为 Minimum，确保布局给 attach_bar 至少 sizeHint 的高度，不被压缩
        bar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        bar_layout = QVBoxLayout(bar)
        bar_layout.setContentsMargins(4, 2, 4, 2)
        bar_layout.setSpacing(4)

        # 可换行的流式布局，放进宿主后装入滚动区：内容超限时滚动而非撑高输入区
        self._attach_flow = _FlowLayout(spacing=6)
        host = _FlowHost(self._attach_flow)
        self._attach_scroll = QScrollArea(bar)
        self._attach_scroll.setObjectName("attachScroll")
        self._attach_scroll.setWidget(host)
        self._attach_scroll.setWidgetResizable(True)
        self._attach_scroll.setFrameShape(QFrame.NoFrame)
        self._attach_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._attach_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._attach_scroll.setMaximumHeight(_ATTACH_BAR_MAX_HEIGHT)
        # 滚动区也设 Minimum，确保内容高度不被压缩到 0
        self._attach_scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._attach_scroll.setStyleSheet(
            "QScrollArea#attachScroll { background: transparent; border: none; }"
            "QScrollArea#attachScroll QWidget { background: transparent; border: none; }"
        )
        # 视口也设透明，避免默认白色背景
        self._attach_scroll.viewport().setAutoFillBackground(False)
        self._attach_scroll.viewport().setStyleSheet("background: transparent; border: none;")
        bar_layout.addWidget(self._attach_scroll)

        # 插入到输入框上方（input_layout 索引 0）
        self.inputFrame.layout().insertWidget(0, bar)
        self._style_attach_bar()
        bar.setVisible(False)

    def _style_attach_bar(self) -> None:
        """附件容器透明融入输入区（chip 直接浮在输入框上方）。

        不再给容器画独立底色/边框：浅色主题下 bg_input 是纯白，若给 attachBar
        也上 bg_input 底 + 边框，会形成一块突兀的白色“细长条”。改为透明后，
        chip 用自带 bg_title 浅色圆角背景浮在输入区上，干净统一、不抢眼。
        """
        self.attach_bar.setStyleSheet(
            "#attachBar { background: transparent; border: none; }"
        )

    def _chip_qss(self, p: dict) -> str:
        """根据配色表生成单个 chip 的 QSS（供创建与主题刷新共用）。"""
        return (
            f"#attachChip {{ background-color: {p['bg_title']};"
            f" border: 1px solid {p['border']}; border-radius: 6px; }}"
        )

    def _add_attachment_chip(self, att: dict) -> None:
        """为一个待上传附件在输入区添加一个紧凑 chip。"""
        is_image = att["kind"] == "image"
        p = self._palette()

        chip = QFrame(self.attach_bar)
        chip.setObjectName("attachChip")
        chip.setStyleSheet(self._chip_qss(p))
        chip_layout = QHBoxLayout(chip)
        chip_layout.setContentsMargins(6, 3, 4, 3)
        chip_layout.setSpacing(5)

        icon = QLabel("🖼" if is_image else "📄")
        icon.setFixedSize(18, 18)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 12pt; background: transparent;")
        chip_layout.addWidget(icon)

        name = QLabel()
        # 文件名超长时以省略号截断，避免单个 chip 被拉爆到整行宽
        fm = name.fontMetrics()
        name.setText(fm.elidedText(att["name"], Qt.TextElideMode.ElideMiddle, 200))
        name.setMaximumWidth(200)
        name.setStyleSheet(
            f"color: {p['text']}; font-size: 10pt; background: transparent;"
        )
        name.setToolTip(att["name"])
        chip_layout.addWidget(name)

        remove = QPushButton("✕")
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.setFlat(True)
        remove.setFixedSize(16, 16)
        remove.setStyleSheet(
            f"color: {p['text_dim']}; font-size: 11pt; border: none;"
            f" background: transparent;"
        )
        remove.setToolTip("移除附件")
        # 用 lambda 绑定当前附件，点击时仅移除该 chip
        remove.clicked.connect(lambda _=False, a=att: self._remove_attachment(a))
        chip_layout.addWidget(remove, 0, Qt.AlignmentFlag.AlignTop)

        self._attach_flow.addWidget(chip)
        # 记录子控件引用，供移除与主题刷新使用
        self._attach_chips.append((att, chip, name, remove))

    def _style_attach_chips(self) -> None:
        """主题切换后刷新所有已存在 chip 的配色。"""
        p = self._palette()
        for _, chip, name, remove in self._attach_chips:
            chip.setStyleSheet(self._chip_qss(p))
            name.setStyleSheet(
                f"color: {p['text']}; font-size: 10pt; background: transparent;"
            )
            remove.setStyleSheet(
                f"color: {p['text_dim']}; font-size: 11pt; border: none;"
                f" background: transparent;"
            )

    def _remove_attachment(self, att: dict) -> None:
        """移除指定的待上传附件及其 chip。"""
        idx = next(
            (i for i, (a, *_rest) in enumerate(self._attach_chips) if a is att), None
        )
        if idx is None:
            return
        _, chip, *_rest = self._attach_chips.pop(idx)
        self._attach_flow.removeWidget(chip)
        chip.deleteLater()
        # 从待上传列表中同步移除
        self._pending_attachments = [
            a for a in self._pending_attachments if a is not att
        ]
        if not self._pending_attachments:
            self.attach_bar.setVisible(False)

    def _clear_attachment(self) -> None:
        """清空全部待上传附件并隐藏附件容器。"""
        for _att, chip, *_rest in self._attach_chips:
            self._attach_flow.removeWidget(chip)
            chip.deleteLater()
        self._attach_chips.clear()
        self._pending_attachments.clear()
        if hasattr(self, "attach_bar"):
            self.attach_bar.setVisible(False)


    # ---- 供应商 / 模型切换（参考 Cline：供应商 + 模型 + 独立 API Key）----

    def _init_provider_ui(self) -> None:
        """填充供应商与模型下拉框，并恢复上次选择与 API Key。"""
        # 填充供应商列表（阻塞信号，避免填充时触发切换逻辑）
        self.combo_provider.blockSignals(True)
        self.combo_provider.clear()
        for name in PROVIDERS:
            self.combo_provider.addItem(name)
        current = self._match_current_provider()
        self.combo_provider.setCurrentText(current)
        self.combo_provider.blockSignals(False)
        # 填充模型与 API Key（启动时不应用，避免重复重建客户端）
        self._sync_provider_controls(apply=False)

    def _match_current_provider(self) -> str:
        """根据当前 base_url / model 推断应选中的供应商名。"""
        prof = config.llm.match_provider()
        return prof.name if prof else list(PROVIDERS)[0]

    def _current_provider(self) -> str:
        return self.combo_provider.currentText()

    def _sync_provider_controls(self, apply: bool = True) -> None:
        """根据当前供应商刷新模型下拉与 API Key 输入框。

        apply=True 时同步把配置应用到运行时（重建 LLM 客户端）。
        """
        name = self._current_provider()
        prof = PROVIDERS.get(name)
        if prof is None:
            return
        # 刷新模型列表（尽量保留当前选中的模型）
        self.combo_model.blockSignals(True)
        prev = self.combo_model.currentText()
        self.combo_model.clear()
        for m in prof.models:
            self.combo_model.addItem(m)
        if prev in prof.models:
            self.combo_model.setCurrentText(prev)
        self.combo_model.blockSignals(False)
        # 恢复该供应商已保存的 API Key（优先持久化，其次 .env 环境变量）
        env_key = os.getenv(prof.api_key_env, "") if prof.api_key_env else ""
        self.edit_api_key.blockSignals(True)
        self.edit_api_key.setText(get_api_key(name, env_key))
        self.edit_api_key.blockSignals(False)
        # 保存按钮默认显示“保存”（可点击），便于随时保存/覆盖当前 Key；
        # “已保存 ✓”反馈由点击保存后短暂展示，再自动恢复为“保存”。
        self._mark_key_saved(False)
        # 是否显示 base_url 输入框：仅 OpenAI 兼容协议（需自定义端点）才显示，
        # 官方 API（如 DeepSeek）隐藏，界面更简洁。
        show_base_url = prof.needs_base_url
        self.label_base_url.setVisible(show_base_url)
        self.edit_base_url.setVisible(show_base_url)
        # 无论是否显示，都同步为该供应商的 base_url（避免残留上一个供应商的值，
        # 否则 _apply_current_provider 会用错端点发请求而 401）。
        self.edit_base_url.blockSignals(True)
        self.edit_base_url.setText(prof.base_url)
        self.edit_base_url.blockSignals(False)
        if apply:
            self._apply_current_provider()

    def _on_provider_changed(self) -> None:
        """供应商下拉变化：联动模型列表 + 应用新配置。"""
        self._sync_provider_controls(apply=True)

    def _on_model_changed(self) -> None:
        """模型下拉变化：应用新模型。"""
        self._apply_current_provider()

    def _on_api_key_edited(self) -> None:
        """API Key 输入完成：立即应用到当前会话（不持久化、不灰显）。

        持久化与“保存后变灰”由保存按钮 btn_save_key 负责。
        """
        self._apply_current_provider()

    def _on_base_url_edited(self) -> None:
        """Base URL 输入完成：立即应用到当前会话（OpenAI 兼容端点可自定义）。"""
        self._apply_current_provider()

    def _on_save_key(self) -> None:
        """保存 API Key 并立即生效。"""
        name = self._current_provider()
        key = self.edit_api_key.text().strip()
        save_api_key(name, key)
        self._apply_current_provider()
        self._mark_key_saved(True)
        QTimer.singleShot(3000, lambda: self._mark_key_saved(False))

    def _mark_key_saved(self, saved: bool) -> None:
        """标记 API Key 的“已保存”状态：仅改变颜色（输入框/按钮变灰），不禁用编辑。"""
        self.btn_save_key.setText("已保存 ✓" if saved else "保存")
        for w in (self.edit_api_key, self.btn_save_key):
            w.setProperty("saved", saved)
            w.style().unpolish(w)
            w.style().polish(w)

    def _on_upload_file(self) -> None:
        """选择并附加一个或多个文件（仅文本与图片）。"""
        TEXT_EXTS = {".txt", ".md", ".json", ".py", ".csv", ".log"}
        IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"}
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择要上传的文件", "",
            "文本与图片 (*.txt *.md *.json *.py *.csv *.log *.jpg *.jpeg *.png *.gif *.bmp *.webp *.svg);;所有文件 (*.*)"
        )
        if not paths:
            return

        # 超过数量上限则拦截
        if len(self._pending_attachments) >= _MAX_ATTACHMENTS:
            self.label_status.setText(f"最多附加 {_MAX_ATTACHMENTS} 个文件，已达上限")
            return

        added, rejected, rejected_reason = 0, [], []
        for path in paths:
            if len(self._pending_attachments) + added >= _MAX_ATTACHMENTS:
                rejected.append(os.path.basename(path))
                rejected_reason.append("数量超限")
                continue
            name = os.path.basename(path)
            ext = os.path.splitext(path)[1].lower()
            if ext in TEXT_EXTS:
                # 超大的文本文件直接拒绝
                try:
                    size = os.path.getsize(path)
                except OSError:
                    rejected.append(name)
                    rejected_reason.append("无法访问")
                    continue
                if size > _MAX_TEXT_BYTES:
                    rejected.append(name)
                    rejected_reason.append("超过大小限制")
                    continue
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except OSError:
                    rejected.append(name)
                    rejected_reason.append("读取失败")
                    continue
                att = {"name": name, "content": content, "kind": "text", "path": path}
            elif ext in IMAGE_EXTS:
                # 图片：读取并 base64 编码为 data URL 暂存（发送时以 image_url 内容块提交，
                # 模型才能真正“看图”）；超大图片直接拒绝，避免塞爆请求/内存。
                try:
                    size = os.path.getsize(path)
                except OSError:
                    rejected.append(name)
                    rejected_reason.append("无法访问")
                    continue
                if size > _MAX_IMAGE_BYTES:
                    rejected.append(name)
                    rejected_reason.append("超过大小限制")
                    continue
                try:
                    with open(path, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("ascii")
                except OSError:
                    rejected.append(name)
                    rejected_reason.append("读取失败")
                    continue
                mime = _IMAGE_MIME.get(ext, "image/png")
                att = {
                    "name": name,
                    "content": "",
                    "kind": "image",
                    "path": path,
                    "data_url": f"data:{mime};base64,{b64}",
                }
            else:
                rejected.append(name)
                rejected_reason.append("类型不支持")
                continue
            self._pending_attachments.append(att)
            self._add_attachment_chip(att)
            added += 1

        if added:
            self.attach_bar.setVisible(True)
            self.label_status.setText(f"已附加 {added} 个文件（发送时提交给大模型）")
        if rejected:
            detail = ", ".join(
                f"{n}({r})" for n, r in zip(rejected, rejected_reason)
            )
            self.label_status.setText(
                f"已附加 {added} 个文件；已跳过: {detail}"
            )

    def _apply_current_provider(self) -> None:
        """把当前下拉框配置应用到运行时 LLM（重建客户端，立即生效）。"""
        name = self._current_provider()
        prof = PROVIDERS.get(name)
        if prof is None:
            return
        model = self.combo_model.currentText() or (prof.models[0] if prof.models else "")
        env_key = os.getenv(prof.api_key_env, "") if prof.api_key_env else ""
        key = self.edit_api_key.text().strip() or get_api_key(name, env_key)
        # base_url 优先取输入框手动值（OpenAI 兼容端点可自定义），空则用供应商预设
        base_url = self.edit_base_url.text().strip() or prof.base_url
        self.agent.set_provider(base_url, model, key)
        # 状态栏提示当前模型
        self.label_status.setText(f"模型：{model}")

    def _on_theme_menu(self) -> None:
        """点击主题按钮：弹出主题菜单，选中后运行时切换主题。"""
        menu = QMenu(self)
        # QMenu 是独立顶级弹窗，不继承主窗口 QSS，需显式套用相同字体与配色
        menu.setFont(self.font())
        menu.setStyleSheet(self._dialog_qss())
        names = list(theme_names())
        current = self.property("theme") or "teal_yellow"
        actions = []
        for name in names:
            act = menu.addAction(THEME_LABELS.get(name, name))
            act.setCheckable(True)
            act.setChecked(name == current)
            actions.append((name, act))
        # 所有菜单项使用手型光标（与按钮一致）
        # 注：PySide6 未暴露 QAction.setCursor，改为给 QMenu 整体设置手型光标
        menu.setCursor(Qt.CursorShape.PointingHandCursor)
        chosen = menu.exec(self.btn_theme.mapToGlobal(self.btn_theme.rect().bottomLeft()))
        if chosen is not None:
            name = next((n for n, a in actions if a is chosen), None)
            if name and name != current:
                apply_theme(self, name)
                # 切换主题后刷新对话区已有消息的颜色，使其跟随新主题
                self._refresh_message_colors()
                logger.info("主题切换为: %s", name)

    def _toggle_sidebar(self) -> None:
        """折叠/展开左侧栏，右栏自动弹性填满剩余空间。"""
        hidden = self.leftSideBar.isVisible()
        self.leftSideBar.setVisible(not hidden)
        self.btn_toggle_sidebar.setToolTip(
            "显示侧栏" if hidden else "隐藏侧栏"
        )

    def _set_tool_names(self) -> None:
        self.label_tool_names.setText(" · ".join(self.agent.tool_names()))

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _hit_test(self, pos) -> int:
        """根据鼠标在窗口内的位置，返回命中的缩放方向（位掩码）。"""
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        m = self._RESIZE_MARGIN
        left = x <= m
        right = x >= w - m
        top = y <= m
        bottom = y >= h - m
        if self._resize_dir != self._EDGE_NONE:
            # 缩放过程中：沿用起始方向，避免鼠标滑到内部就丢失方向
            return self._resize_dir
        return (
            (self._EDGE_LEFT if left else 0)
            | (self._EDGE_RIGHT if right else 0)
            | (self._EDGE_TOP if top else 0)
            | (self._EDGE_BOTTOM if bottom else 0)
        )

    @staticmethod
    def _resize_cursor(dir: int) -> Qt.CursorShape:
        """返回对应缩放方向的光标形状。"""
        if dir in (MainWindow._EDGE_LEFT, MainWindow._EDGE_RIGHT):
            return Qt.SizeHorCursor
        if dir in (MainWindow._EDGE_TOP, MainWindow._EDGE_BOTTOM):
            return Qt.SizeVerCursor
        # 四角：左上/右下 为斜向，左下/右上 为另一斜向
        diag = (
            (dir & MainWindow._EDGE_TOP and dir & MainWindow._EDGE_LEFT)
            or (dir & MainWindow._EDGE_BOTTOM and dir & MainWindow._EDGE_RIGHT)
        )
        return Qt.SizeFDiagCursor if diag else Qt.SizeBDiagCursor

    def _align_sidebar_width(self) -> None:
        """DPI 像素对齐：把 leftSideBar 宽度微调为非整数缩放下物理宽为整数的值。

        非 100% DPI 缩放下，leftSideBar 固定逻辑宽度 × dpr 可能是半像素
        （如 210 × 1.25 = 262.5 物理px），右边缘落在物理像素中间，Qt 对该
        半像素边缘做抗锯齿，形成一条贯穿的半透明缝隙。此处枚举目标宽度附近，
        选物理宽（width × dpr）为整数的宽度并应用，使右边缘落在整数物理
        像素上，缝隙即消失。100% 缩放（dpr<=1）时无此问题，直接跳过。
        """
        bar = self.leftSideBar
        if bar is None:
            return
        dpr = self.devicePixelRatioF()
        if dpr <= 1.0:
            return
        target = bar.width()  # .ui 中设定的固定宽度（如 210）
        best = target
        best_dist = float("inf")
        for w in range(target - 20, target + 21):
            if w <= 0:
                continue
            phys = w * dpr
            if abs(phys - round(phys)) < 1e-6:  # 物理宽为整数
                dist = abs(w - target)
                if dist < best_dist:
                    best = w
                    best_dist = dist
        if best != target:
            # setFixedWidth 同时会设定 minimum/maximumSize，确保布局不再回弹
            bar.setFixedWidth(best)
            bar.setMinimumWidth(best)
            bar.setMaximumWidth(best)

    def _install_edge_filter(self) -> None:
        """为边缘缩放安装鼠标事件过滤与光标处理。"""
        edge_names = ("titleBar", "leftSideBar", "rightMainFrame")
        for name in edge_names:
            child = getattr(self, name)
            child.installEventFilter(self)
            child.setMouseTracking(True)
        self.setMouseTracking(True)

        edge = {getattr(self, name) for name in edge_names}
        for child in self.findChildren(QWidget):
            if child in edge:
                continue  # 外围容器保留继承，让边缘显示缩放光标
            if not child.testAttribute(Qt.WA_SetCursor):
                child.setCursor(Qt.ArrowCursor)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """外围容器的鼠标事件转交给 MainWindow 原生处理。

        另：输入框 edit_input 的回车发送、Shift+Enter 换行在此统一处理
        （QTextEdit 聚焦时按键事件不会到达 MainWindow.keyPressEvent）。
        """
        t = event.type()
        if obj is self.edit_input and t == QEvent.Type.KeyPress:
            if (
                event.key() == Qt.Key_Return
                and not event.modifiers() & Qt.ShiftModifier
            ):
                self._on_send()
                return True
        if t in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonRelease,
        ):
            return self._process_mouse_event(event)
        return super().eventFilter(obj, event)

    def _process_mouse_event(self, event) -> bool:
        """统一的鼠标事件入口：边缘缩放 / 标题栏拖动 / 光标更新。

        返回 True 表示事件已被消费（不再传给子控件）。
        鼠标在窗口内部时返回 False，放行给子控件。
        """
        t = event.type()
        pos = self.mapFromGlobal(event.globalPosition().toPoint())
        x, y = pos.x(), pos.y()
        m = self._RESIZE_MARGIN
        in_edge = (
            x <= m or x >= self.width() - m or y <= m or y >= self.height() - m
        )

        # ---- 按下 ----
        if t == QEvent.Type.MouseButtonPress:
            if event.button() != Qt.LeftButton or self.isMaximized():
                return False
            # 只在边缘 / 标题栏处理；窗口内部一律放行给子控件
            if not in_edge and not (0 <= y <= 42):
                return False
            self._resize_dir = self._hit_test(pos)
            if self._resize_dir:
                self._resize_start_geo = self.geometry()
                return True
            if y <= 42:
                # 标题栏：拖动移动窗口
                self._drag_pos = (
                    event.globalPosition().toPoint()
                    - self.frameGeometry().topLeft()
                )
                return True
            return False

        # ---- 移动 ----
        if t == QEvent.Type.MouseMove:
            if self._resize_dir and event.buttons() & Qt.LeftButton:
                self._apply_resize(event.globalPosition().toPoint())
                return True
            if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
                self.move(event.globalPosition().toPoint() - self._drag_pos)
                return True
            if not event.buttons():
                if in_edge:
                    self.setCursor(self._resize_cursor(self._hit_test(pos)))
                else:
                    self.unsetCursor()
            return False

        # ---- 松开 ----
        if t == QEvent.Type.MouseButtonRelease:
            self._drag_pos = None
            self._resize_dir = self._EDGE_NONE
            self._resize_start_geo = None
            return False

        return False

    # MainWindow 本体（或外围容器经过滤器转交）收到的鼠标事件统一入口
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if not self._process_mouse_event(event):
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._process_mouse_event(event):
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._process_mouse_event(event)
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.unsetCursor()
        super().leaveEvent(event)

    def _apply_resize(self, global_pos) -> None:
        """根据缩放方向和鼠标位移更新窗口几何。"""
        d = self._resize_dir
        gx, gy = global_pos.x(), global_pos.y()
        sx, sy, sw, sh = self._resize_start_geo.getRect()
        # 禁止缩小：最小尺寸固定为拖动开始时的尺寸（小于该值则保持，只能放大）
        min_w, min_h = sw, sh

        # 先按鼠标位置算出左右/上下边界
        left = gx if d & self._EDGE_LEFT else sx
        right = gx if d & self._EDGE_RIGHT else sx + sw
        top = gy if d & self._EDGE_TOP else sy
        bottom = gy if d & self._EDGE_BOTTOM else sy + sh

        # 应用最小尺寸（若同时拖两边导致倒置，则取最小尺寸）
        if d & self._EDGE_LEFT and d & self._EDGE_RIGHT:
            if right - left < min_w:
                if gx < sx + sw / 2:
                    left = right - min_w
                else:
                    right = left + min_w
        elif right - left < min_w:
            right = left + min_w
        if d & self._EDGE_TOP and d & self._EDGE_BOTTOM:
            if bottom - top < min_h:
                if gy < sy + sh / 2:
                    top = bottom - min_h
                else:
                    bottom = top + min_h
        elif bottom - top < min_h:
            bottom = top + min_h

        self.setGeometry(left, top, right - left, bottom - top)


    def keyPressEvent(self, event) -> None:  # noqa: N802
        # Enter 发送、Shift+Enter 换行（仅输入框聚焦时）
        if (
            event.key() == Qt.Key_Return
            and not event.modifiers() & Qt.ShiftModifier
            and self.edit_input.hasFocus()
        ):
            self._on_send()
            event.accept()
        else:
            super().keyPressEvent(event)

    # ---- 交互逻辑 ----

    def _on_send(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        text = self.edit_input.toPlainText().strip()
        if not text and not self._pending_attachments:
            return
        self.edit_input.clear()
        # 首次发送时清空欢迎界面
        if self._current_idx is None or not self._sessions[self._current_idx]:
            self.chat_view.clear_all()

        # 应用当前供应商配置，并组装发送载荷
        self._apply_current_provider()
        result = self._build_user_payload(text)
        if result is None:
            # 模型不支持视觉：保留附件并恢复问题文本
            self.edit_input.setPlainText(text)
            self.edit_input.setFocus()
            self.label_status.setText(
                "当前模型不支持看图，请切换到支持视觉的模型（如 gpt-4o / doubao）后重试"
            )
            return

        payload, full, display = result
        if self._pending_attachments:
            self._clear_attachment()
        self.add_user_message(full, display)
        self.label_status.setText("Agent 思考中……")
        self._run_worker(payload)

    def _build_user_payload(self, text: str) -> tuple | None:
        """把用户问题与附件拼成发送载荷，返回 (payload, full, display)。

        模型不支持视觉时返回 None 以阻止发送。
        """
        display = text
        full = text
        payload = text
        if self._pending_attachments:
            content_blocks: list[dict] = []  # OpenAI 多模态内容块
            full_parts: list[str] = []
            display_parts: list[str] = []
            has_image = False

            for att in self._pending_attachments:
                if att["kind"] == "image":
                    has_image = True
                    data_url = att.get("data_url")
                    if data_url:
                        content_blocks.append(
                            {"type": "image_url", "image_url": {"url": data_url}}
                        )
                    full_parts.append(f"📎 图片: {att['path']}")
                else:
                    block_text = (
                        f"📎 附件: {att['name']}\n```\n{att['content']}\n```"
                    )
                    content_blocks.append({"type": "text", "text": block_text})
                    full_parts.append(block_text)
                display_parts.append(
                    f"📎 {'图片' if att['kind'] == 'image' else '附件'}：{att['name']}"
                )

            # 纯文本版与气泡显示版都包含附件信息
            if full_parts:
                full = "\n\n".join(full_parts) + ("\n\n" + text if text else "")
            if display_parts:
                display = "\n".join(display_parts) + ("\n" + text if text else "")

            if has_image:
                if not config.llm.supports_vision():
                    return None
                # 用户问题作为文本块拼到内容块数组头部
                if text:
                    content_blocks.insert(0, {"type": "text", "text": text})
                payload = content_blocks
            else:
                payload = full
        return payload, full, display

    def _on_clear(self) -> None:
        self.agent.reset()
        self.chat_view.clear_all()
        self.chat_view.show_welcome()
        self._clear_attachment()
        # 同步清空当前会话记录
        if self._current_idx is not None:
            self._sessions[self._current_idx].clear()
            self._session_titles[self._current_idx] = "新对话"
            widget = self._get_history_widget(self._current_idx)
            if widget is not None:
                widget.update_title("新对话")
        self.label_status.setText("新对话")
        self._save_current()


    def _on_nav_clicked(self, item) -> None:
        """侧边栏导航点击：更新状态栏提示。"""
        self.label_status.setText(item.text())


    # ---- 会话管理（历史对话列表 = 会话列表，点击切换）----

    def _load_persisted_sessions(self) -> None:
        """启动时从磁盘恢复历史会话到内存与列表（会话持久化）。"""
        for i, sess in enumerate(session_store.list_sessions()):
            self._session_ids.append(sess["id"])
            self._session_titles.append(sess["title"])
            # 磁盘存 [[role, text], ...]，内部会话用元组 [(role, text), ...]
            self._sessions.append([tuple(msg) for msg in sess["messages"]])
            self._add_history_item(sess["title"], i)

    def _save_current(self) -> None:
        """把当前会话写入磁盘（消息/标题变更后调用）。"""
        if self._current_idx is None:
            return
        sid = self._session_ids[self._current_idx]
        session_store.save_session(
            sid,
            self._session_titles[self._current_idx],
            self._sessions[self._current_idx],
        )

    def _save_all_sessions(self) -> None:
        """退出兜底：把全部会话写入磁盘，空会话不落盘。"""
        for i, sid in enumerate(self._session_ids):
            if not self._sessions[i]:
                session_store.delete_session(sid)
                continue
            session_store.save_session(sid, self._session_titles[i], self._sessions[i])

    def _ensure_session(self) -> None:
        """确保存在当前会话；没有则新建一个空会话。"""
        if self._current_idx is None:
            self._sessions.append([])
            self._session_titles.append("新对话")
            self._session_ids.append(session_store.new_id())
            self._current_idx = len(self._sessions) - 1
            self._add_history_item("新对话", self._current_idx)

    def _record(self, role: str, text: str) -> None:
        """把一条消息写入当前会话；首条用户消息作为会话标题。"""
        self._ensure_session()
        self._sessions[self._current_idx].append((role, text))
        if role == "user" and self._session_titles[self._current_idx] in ("", "新对话"):
            # 用首条用户消息的前 14 字符作标题
            clean = text.strip().replace("\n", " ").replace("\r", "")
            title = clean if len(clean) <= 14 else clean[:14] + "…"
            self._session_titles[self._current_idx] = title
            widget = self._get_history_widget(self._current_idx)
            if widget is not None:
                widget.update_title(title)
        self._save_current()

    def _render_session(self, idx: int) -> None:
        """清空对话区并重新渲染指定会话的全部消息（气泡式）。"""
        self.chat_view.clear_all()
        if not self._sessions[idx]:
            self.chat_view.show_welcome()
            return
        for msg_idx, (role, text) in enumerate(self._sessions[idx]):
            if role == "user":
                self.chat_view.add_user_message(text, msg_idx)
            elif role == "assistant":
                self.chat_view.add_assistant_message(text, msg_idx)
            elif role == "error":
                self.chat_view.add_error_message(text)
        self.chat_view.scroll_to_bottom()

    def _on_new(self) -> None:
        """新建对话：清空对话区、建立新会话（标题"新对话"）、重置 Agent 上下文。"""
        self.agent.reset()
        self._clear_attachment()
        self._sessions.append([])
        self._session_titles.append("新对话")
        self._session_ids.append(session_store.new_id())
        self._current_idx = len(self._sessions) - 1
        self._add_history_item("新对话", self._current_idx)
        self.list_history.setCurrentRow(self._current_idx)
        self.chat_view.clear_all()
        self.chat_view.show_welcome()
        self.label_status.setText("新对话")

    def _on_history_clicked(self, item: QListWidgetItem) -> None:
        """点击历史会话条目：切换到该会话并恢复其消息。"""
        row = self.list_history.row(item)
        if row < 0 or row >= len(self._sessions):
            return
        self._current_idx = row
        # 同步 Agent 上下文到该会话历史（未配置 Key 时仅告警）
        try:
            self.agent.load_history(self._sessions[row])
        except ValueError as e:
            logger.warning("同步历史上下文失败（可能未配置 API Key）: %s", e)
        self._render_session(row)
        self.label_status.setText(self._session_titles[row] or "对话")

    def _add_history_item(self, title: str, session_idx: int) -> None:
        """向历史列表追加一个自定义 item widget（图标 + 标题 + hover 更多按钮）。"""
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 40))
        widget = _HistoryItemWidget(title, session_idx)
        widget.more_clicked.connect(self._on_item_more)
        self.list_history.addItem(item)
        self.list_history.setItemWidget(item, widget)

    def _get_history_widget(self, row: int):
        """返回指定行历史 item 的自定义 widget；无则返回 None。"""
        item = self.list_history.item(row)
        if item is None:
            return None
        return self.list_history.itemWidget(item)

    def _on_history_selection_changed(self, row: int) -> None:
        """当前行变化时刷新所有历史 item 的选中态。"""
        for i in range(self.list_history.count()):
            widget = self._get_history_widget(i)
            if widget is not None:
                widget.set_selected(i == row)

    def _on_item_more(self, row: int) -> None:
        """点击历史项的「⋯」按钮：弹出 重命名 / 删除 菜单。"""
        if row < 0 or row >= len(self._sessions):
            return
        widget = self._get_history_widget(row)
        menu = QMenu(self)
        # QMenu 是独立顶级弹窗，需显式套用主题配色，避免深色主题下显示纯白
        menu.setFont(self.font())
        menu.setStyleSheet(self._dialog_qss())
        menu.addAction("重命名", lambda: self._rename_session(row))
        menu.addAction("删除", lambda: self._delete_session(row))
        if widget is not None:
            menu.exec(widget.more_btn.mapToGlobal(QPoint(0, widget.more_btn.height())))

    def _rename_session(self, row: int) -> None:
        """重命名会话：更新标题、列表显示与磁盘。"""
        if row < 0 or row >= len(self._sessions):
            return
        old = self._session_titles[row]
        # 实例化 QInputDialog 以套用主题样式
        dialog = QInputDialog(self)
        dialog.setFont(self.font())
        dialog.setStyleSheet(self._dialog_qss())
        dialog.setWindowTitle("重命名会话")
        dialog.setLabelText("新的会话标题：")
        dialog.setTextValue(old)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new = dialog.textValue().strip()
        if not new:
            return
        self._session_titles[row] = new
        widget = self._get_history_widget(row)
        if widget is not None:
            widget.update_title(new)
        session_store.save_session(self._session_ids[row], new, self._sessions[row])
        if row == self._current_idx:
            self.label_status.setText(new)

    def _delete_session(self, row: int) -> None:
        """删除会话：确认后同步移除内存、列表与磁盘。"""
        if row < 0 or row >= len(self._sessions):
            return
        title = self._session_titles[row]
        # 实例化 QMessageBox 以套用主题样式
        box = QMessageBox(self)
        box.setFont(self.font())
        box.setStyleSheet(self._dialog_qss())
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("删除会话")
        box.setText(f"确定删除会话「{title}」吗？")
        btn_yes = box.addButton("删除", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_yes)
        box.exec()
        if box.clickedButton() is not btn_yes:
            return
        sid = self._session_ids[row]
        is_current = (row == self._current_idx)

        del self._sessions[row]
        del self._session_titles[row]
        del self._session_ids[row]
        self.list_history.takeItem(row)
        session_store.delete_session(sid)
        logger.info("已删除会话: %s (%s)", title, sid)

        if is_current:
            # 删除当前会话 -> 回到主欢迎界面，其余会话保留
            self._current_idx = None
            self.agent.reset()
            self.chat_view.clear_all()
            self.chat_view.show_welcome()
            self.label_status.setText("对话")
            self.list_history.clearSelection()
        else:
            # 删除的是当前会话之前的项：当前索引前移
            if self._current_idx is not None and row < self._current_idx:
                self._current_idx -= 1
        # 删除后剩余项的索引变化，刷新图标颜色
        self._refresh_history_indices()

    def _refresh_history_indices(self) -> None:
        """删除会话后刷新所有剩余历史项的索引（图标颜色跟随）。"""
        for i in range(self.list_history.count()):
            widget = self._get_history_widget(i)
            if widget is not None:
                widget.update_index(i)

    # ---- 消息渲染 ----

    def _dialog_qss(self) -> str:
        """返回随当前主题的弹层（菜单/对话框）主题化 QSS。

        QMenu / QMessageBox / QInputDialog 都是独立顶级弹窗，不继承主窗口
        的 QSS，在深色主题下会显示系统默认的纯白配色。此方法生成一套覆盖
        这些弹层的主题样式，统一调用即可保证弹层跟随主题。
        """
        p = self._palette()
        return (
            f"QMenu {{ background-color: {p['bg_input']}; color: {p['text']};"
            f" border: 1px solid {p['border']}; padding: 4px; }}"
            f"QMenu::item {{ padding: 6px 20px; border-radius: 4px; }}"
            f"QMenu::item:selected {{ background-color: {p['bg_hover']};"
            f" color: {p['text']}; }}"
            f"QMessageBox {{ background-color: {p['bg_input']}; color: {p['text']}; }}"
            f"QMessageBox QLabel {{ color: {p['text']}; }}"
            f"QMessageBox QPushButton {{ background: {p['btn']}; color: {p['text']};"
            f" border: 1px solid {p['border']}; border-radius: 6px;"
            f" padding: 6px 16px; min-width: 64px; }}"
            f"QMessageBox QPushButton:hover {{ background: {p['btn_hover']}; }}"
            f"QInputDialog {{ background-color: {p['bg_input']}; color: {p['text']}; }}"
            f"QInputDialog QLabel {{ color: {p['text']}; }}"
            f"QInputDialog QLineEdit {{ background: {p['bg']}; color: {p['text']};"
            f" border: 1px solid {p['border']}; border-radius: 6px;"
            f" padding: 6px 8px; selection-background-color: {p['sel_bg']}; }}"
            f"QInputDialog QPushButton {{ background: {p['btn']}; color: {p['text']};"
            f" border: 1px solid {p['border']}; border-radius: 6px;"
            f" padding: 6px 16px; min-width: 64px; }}"
            f"QInputDialog QPushButton:hover {{ background: {p['btn_hover']}; }}"
        )

    def _palette(self) -> dict:
        """返回当前主题的配色表。"""
        return THEMES[current_theme(self)]

    def _refresh_message_colors(self) -> None:
        """主题切换后：更新 ChatView 配色并重渲染当前会话（含欢迎界面）。"""
        p = self._palette()
        self.chat_view.update_theme(p, current_theme(self))
        self._style_attach_bar()
        self._style_attach_chips()
        # 背景色由 QSS 统一管理，主题切换时自动生效
        self.chatContainer.setStyleSheet(f"background-color:{p['bg']};")
        if self._current_idx is not None and self._sessions[self._current_idx]:
            self._render_session(self._current_idx)
        else:
            # 无会话或空会话时，重建欢迎界面以应用新主题配色
            self.chat_view.show_welcome()


    def add_user_message(self, text: str, display_text: str | None = None) -> None:
        self._record("user", text)
        idx = len(self._sessions[self._current_idx]) - 1
        self.chat_view.add_user_message(display_text if display_text is not None else text, idx)

    def add_agent_message(self, text: str) -> None:
        # 若正处于流式渲染，最终正文已逐块显示，此处只需收尾，避免重复渲染。
        if self._stream_bubble is not None:
            self._end_stream()
            return
        self._record("assistant", text)
        idx = len(self._sessions[self._current_idx]) - 1
        self.chat_view.add_assistant_message(text, idx)

    def add_agent_chunk(self, chunk: str) -> None:
        """流式追加助手消息正文增量（最终回答逐块显示）。"""
        if self._stream_bubble is None:
            self._begin_stream()
        self._stream_text += chunk
        self._stream_bubble.stream_append(chunk)
        self.chat_view.scroll_to_bottom()

    def _begin_stream(self) -> None:
        """开始一条流式助手消息：创建空气泡并进入流式状态。"""
        self._stream_text = ""
        idx = len(self._sessions[self._current_idx]) if self._current_idx is not None else -1
        self._stream_bubble = self.chat_view.add_assistant_message("", idx)
        self._stream_bubble.stream_begin()

    def _end_stream(self) -> None:
        """结束当前流式消息，把累积文本写入会话，气泡重渲染 Markdown。"""
        if self._stream_text:
            self._record("assistant", self._stream_text)
            self._stream_text = ""
        if self._stream_bubble is not None:
            self._stream_bubble.stream_finish()
            self._stream_bubble = None

    def add_tool_message(self, name: str, arguments: str) -> None:
        # 工具消息不调 _record：工具调用是中间过程，不进入会话历史，
        # 避免插入 tool 消息导致后续助手气泡的 msg_idx 与会话索引错位。
        # （重放会话时也不需要工具调用，ReAct 会根据上下文重新决定是否调工具）
        self.chat_view.add_tool_message(name, arguments)

    def add_error_message(self, text: str) -> None:
        self._record("error", text)
        self.chat_view.add_error_message(text)


    @staticmethod
    def _escape(text: str) -> str:
        """HTML 转义，防止消息内容破坏布局。"""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )

    # ---- Agent 线程管理 ----

    def _set_busy(self, busy: bool) -> None:
        """流式生成期间禁用发送与上传，结束后恢复，避免并发操作附件/重复发送。"""
        for w in (self.btn_send, self.btn_upload):
            w.setEnabled(not busy)
            w.setProperty("busy", busy)
            w.style().unpolish(w)
            w.style().polish(w)

    def _run_worker(self, text: str | list) -> None:
        worker = _AgentWorker(self.agent, text, parent=self)
        # Qt 内建 QThread.finished：run() 返回后自动发出，用于线程结束后的清理
        worker.finished.connect(self._on_agent_finished)
        self._worker = worker
        worker.start()
        self._set_busy(True)

    def _on_error(self, message: str) -> None:
        self.add_error_message(message)
        logger.error("Agent 出错: %s", message)

    # ---- 消息操作按钮（复制/重做/分享）----

    def _on_copy_message(self, msg_idx: int) -> None:
        """复制指定助手消息到剪贴板。"""
        if self._current_idx is not None and 0 <= msg_idx < len(self._sessions[self._current_idx]):
            _, text = self._sessions[self._current_idx][msg_idx]
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
            self.label_status.setText("已复制到剪贴板")
            QTimer.singleShot(2000, lambda: self.label_status.setText("就绪"))

    def _on_redo_message(self, msg_idx: int) -> None:
        """重做：移除当前这条问答，再重新生成。"""
        if self._current_idx is None or (self._worker and self._worker.isRunning()):
            return
        session = self._sessions[self._current_idx]
        if msg_idx < 0 or msg_idx >= len(session):
            return

        # 定位触发重做的助手消息对应的用户消息
        user_pos = None
        for i in range(msg_idx, -1, -1):
            if session[i][0] == "user":
                user_pos = i
                break
        if user_pos is None:
            return
        user_text = session[user_pos][1]

        # 删除从用户消息到助手回复结束这一整段
        end = msg_idx
        while end + 1 < len(session) and session[end + 1][0] in ("assistant", "tool", "error"):
            end += 1
        del session[user_pos : end + 1]

        # 同步 Agent 上下文并重新渲染（未配置 Key 时仅告警）
        try:
            self.agent.load_history(session)
        except ValueError as e:
            logger.warning("同步历史上下文失败（可能未配置 API Key）: %s", e)
        self._render_session(self._current_idx)
        if not session:
            self.chat_view.show_welcome()

        # 重新发送该用户消息
        self._apply_current_provider()
        self.add_user_message(user_text)
        self.label_status.setText("Agent 思考中……")
        self._run_worker(user_text)

    def _on_share_message(self, msg_idx: int) -> None:
        """分享：复制带前缀的助手消息到剪贴板。"""
        if self._current_idx is not None and 0 <= msg_idx < len(self._sessions[self._current_idx]):
            _, text = self._sessions[self._current_idx][msg_idx]
            share_text = f"【Raven Agent 分享】\n\n{text}"
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(share_text)
            self.label_status.setText("已复制分享内容到剪贴板")
            QTimer.singleShot(2000, lambda: self.label_status.setText("就绪"))

    def _on_suggestion_clicked(self, text: str) -> None:
        """欢迎界面的建议卡片被点击：填入输入框。"""
        self.edit_input.setPlainText(text)
        self.edit_input.setFocus()

    def _on_agent_finished(self) -> None:
        # 线程已结束，释放引用以允许对象被回收
        self._worker = None
        # 兜底：若流式消息未正常收尾（异常/中断），强制关闭流式状态
        if self._stream_bubble is not None:
            self._end_stream()
        self._set_busy(False)
        self.label_status.setText("就绪")

    def closeEvent(self, event) -> None:  # noqa: N802
        """关闭窗口时优雅结束 Agent 线程，避免线程崩溃。"""
        if self._worker and self._worker.isRunning():
            # 请求中断：Agent 在下一轮循环前响应并退出
            self._worker.requestInterruption()
            self.agent.request_interrupt()
            # 等待线程结束，最多 5 秒（LLM 请求本身无法取消，超时后强制继续关闭）
            if not self._worker.wait(5000):
                logger.warning("Agent 线程 5 秒内未结束，强制关闭")
        # 退出兜底：把内存中的全部会话写回磁盘
        self._save_all_sessions()
        self.agent.shutdown()
        super().closeEvent(event)

