"""ChatView 聊天区组件：基于 QListWidget + 自定义气泡 widget。

每条消息是一个独立的 QListWidgetItem，其内部 widget 是自定义气泡
（UserBubble / AssistantBubble / ToolBubble / ErrorBubble）。QSS 完全
生效，不再依赖 QTextBrowser 的 HTML 渲染。

对外提供简洁的 add_* 方法，转发操作按钮信号，供 MainWindow 连接。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget

from app.ui.bubbles import (
    AssistantBubble,
    ErrorBubble,
    ToolBubble,
    UserBubble,
    WelcomeWidget,
)


class ChatView(QListWidget):
    """聊天区：QListWidget 承载自定义气泡 widget。"""

    # 转发助手气泡的操作信号
    copy_requested = Signal(int)
    redo_requested = Signal(int)
    share_requested = Signal(int)
    suggestion_clicked = Signal(str)

    def __init__(self, palette: dict, theme: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.p = palette
        self.theme = theme
        self._assistant_bubbles: dict[int, AssistantBubble] = {}
        self._bubble_items: dict[QWidget, QListWidgetItem] = {}  # widget -> item，用于高度同步
        self._setup_style()

    def _setup_style(self) -> None:
        from PySide6.QtWidgets import QFrame
        self.setFrameShape(QListWidget.NoFrame)
        self.setFrameShadow(QListWidget.Plain)
        self.setLineWidth(0)
        self.setMidLineWidth(0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        # 降低滚动条灵敏度：默认 singleStep 太大，滚轮一下跳太多
        self.verticalScrollBar().setSingleStep(15)
        self.verticalScrollBar().setPageStep(120)
        self.setSpacing(0)
        self.setContentsMargins(0, 0, 0, 0)
        self.setViewportMargins(0, 0, 0, 0)
        self.setStyleSheet(
            f"background-color:{self.p['bg']};color:{self.p['text']};"
            f"font-size:11.5pt;border:0px none;outline:none;padding:0;margin:0;"
            "QListWidget::item{border:0px none;padding:0;margin:0;}"
            f"QListWidget QWidget{{background-color:{self.p['bg']};border:0px none;}}"
            "QListWidget QFrame{border:0px none;}"
            "QListWidget QAbstractScrollArea{border:0px none;}"
        )
        # 视口也彻底清除边框（viewport 是 QWidget，没有 setFrameShape）
        self.viewport().setAutoFillBackground(True)
        self.viewport().setContentsMargins(0, 0, 0, 0)
        self.viewport().setStyleSheet(f"background-color:{self.p['bg']};border:0px none;padding:0;margin:0;")
        self.setSelectionMode(QListWidget.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)

    def update_theme(self, palette: dict, theme: str) -> None:
        """主题切换时更新配色（现有气泡需要重建，调用方先 clear 再重渲染）。"""
        self.p = palette
        self.theme = theme
        self._setup_style()

    def _add_item(self, widget: QWidget) -> QListWidgetItem:
        """添加一个 item 并设置内部 widget，返回 item。"""
        item = QListWidgetItem(self)
        item.setSizeHint(widget.sizeHint())
        self.addItem(item)
        self.setItemWidget(item, widget)
        self._bubble_items[widget] = item
        return item

    def _on_bubble_size_changed(self) -> None:
        """气泡高度变化时，同步更新对应 QListWidgetItem 的 sizeHint。"""
        bubble = self.sender()
        item = self._bubble_items.get(bubble)
        if item is not None:
            item.setSizeHint(bubble.sizeHint())
            self.scheduleDelayedItemsLayout()
            # 高度更新后再滚一次，确保最新消息可见
            QTimer.singleShot(50, self.scroll_to_bottom)

    def add_user_message(self, text: str, msg_idx: int = -1) -> UserBubble:
        bubble = UserBubble(text, self.p, self)
        bubble.size_changed.connect(self._on_bubble_size_changed)
        self._add_item(bubble)
        QTimer.singleShot(50, self.scroll_to_bottom)
        return bubble

    def add_assistant_message(self, text: str, msg_idx: int = -1) -> AssistantBubble:
        bubble = AssistantBubble(text, self.p, self.theme, msg_idx, self)
        bubble.copy_requested.connect(self.copy_requested)
        bubble.redo_requested.connect(self.redo_requested)
        bubble.share_requested.connect(self.share_requested)
        bubble.size_changed.connect(self._on_bubble_size_changed)
        if msg_idx >= 0:
            self._assistant_bubbles[msg_idx] = bubble
        self._add_item(bubble)
        QTimer.singleShot(50, self.scroll_to_bottom)
        return bubble

    def add_tool_message(self, name: str, arguments: str) -> ToolBubble:
        bubble = ToolBubble(name, arguments, self.p, self)
        self._add_item(bubble)
        self.scroll_to_bottom()
        return bubble

    def add_error_message(self, text: str) -> ErrorBubble:
        bubble = ErrorBubble(text, self.p, self)
        self._add_item(bubble)
        self.scroll_to_bottom()
        return bubble

    def show_welcome(self) -> None:
        """显示空状态欢迎界面。"""
        self.clear()
        welcome = WelcomeWidget(self.p, self)
        welcome.suggestion_clicked.connect(self.suggestion_clicked)
        item = QListWidgetItem(self)
        item.setSizeHint(welcome.sizeHint())
        self.addItem(item)
        self.setItemWidget(item, welcome)

    def get_assistant_bubble(self, msg_idx: int) -> AssistantBubble | None:
        """获取指定索引的助手气泡（用于流式更新）。"""
        return self._assistant_bubbles.get(msg_idx)

    def clear_all(self) -> None:
        """清空所有消息与气泡缓存。"""
        self._assistant_bubbles.clear()
        self._bubble_items.clear()
        self.clear()

    def scroll_to_bottom(self) -> None:
        """滚动到底部。"""
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())
