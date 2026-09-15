"""自定义消息气泡 widget：用户/助手/工具/错误四种气泡。

每个气泡是独立的 QWidget，QSS 完全生效（圆角、阴影、hover、边框），
不再依赖 QTextBrowser 的 HTML 渲染。助手气泡内嵌只读 QTextBrowser
渲染 Markdown 内容，外层 QFrame 提供气泡背景与圆角。
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.ui.markdown_renderer import render_md


def _now_str() -> str:
    return datetime.now().strftime("%H:%M")


class BubbleBase(QWidget):
    """所有气泡的基类：提供主题配色与通用布局辅助。"""

    def __init__(self, palette: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.p = palette
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_StyledBackground, True)

    def _avatar_label(self, emoji: str, bg_key: str = "bg_input") -> QLabel:
        """生成圆形头像标签。"""
        label = QLabel(emoji)
        label.setFixedSize(28, 28)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            f"background-color:{self.p[bg_key]};"
            f"border:1px solid {self.p['border']};"
            "border-radius:14px;font-size:16px;"
        )
        return label

    def _meta_label(self, text: str, color_key: str = "text_dim") -> QLabel:
        """生成元信息标签（名称/时间等）。"""
        label = QLabel(text)
        label.setStyleSheet(f"color:{self.p[color_key]};font-size:10pt;font-weight:600;")
        return label


class UserBubble(BubbleBase):
    """用户消息气泡：右对齐，头像在右侧，时间戳在气泡上方。

    内容用只读 QTextBrowser 承载（与助手气泡一致），宽度随聊天区自适应，
    高度随内容/宽度变化自动同步到 ChatView 的 item。
    """

    size_changed = Signal()

    def __init__(self, text: str, palette: dict, parent: QWidget | None = None) -> None:
        super().__init__(palette, parent)
        self._adjusting = False
        self._total_h = 0
        self._last_width = 0
        self.content: QTextBrowser | None = None
        self._build(text)

    def sizeHint(self) -> QSize:
        """重写 sizeHint：返回 _adjust_height 计算的精确高度，避免 QTextBrowser 默认 sizeHint 干扰。"""
        if self._total_h > 0:
            return QSize(super().sizeHint().width(), self._total_h)
        return super().sizeHint()

    def _build(self, text: str) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(8)
        outer.addStretch(1)

        # 右侧列：时间 + 气泡
        right_col = QVBoxLayout()
        right_col.setSpacing(2)
        right_col.setAlignment(Qt.AlignRight)

        time_label = QLabel(_now_str())
        time_label.setAlignment(Qt.AlignRight)
        time_label.setStyleSheet(f"color:{self.p['text_muted']};font-size:9.5pt;")
        right_col.addWidget(time_label)

        bubble = QFrame()
        bubble.setStyleSheet(
            f"background-color:{self.p['sel_bg']};"
            f"border:1px solid {self.p['border']};"
            "border-radius:14px;"
        )
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)

        # 只读 QTextBrowser 承载内容：宽度自适应、高度自动同步
        self.content = QTextBrowser()
        self.content.setReadOnly(True)
        self.content.setFrameShape(QFrame.NoFrame)
        self.content.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content.setStyleSheet(
            f"background-color:transparent;color:{self.p['text']};"
            f"font-size:10.5pt;border:none;"
        )
        self.content.setPlainText(text)
        # 初始最大宽度（resizeEvent 中会根据可用宽度动态调整）
        self.content.setMaximumWidth(520)
        self.content.document().contentsChanged.connect(self._adjust_height)
        bubble_layout.addWidget(self.content)
        right_col.addWidget(bubble, alignment=Qt.AlignRight)

        outer.addLayout(right_col)
        outer.addWidget(self._avatar_label("🪶"), alignment=Qt.AlignTop)
        self._adjust_height()

    def resizeEvent(self, event) -> None:
        """窗口/聊天区宽度变化时，让用户气泡宽度跟随可用宽度自适应。"""
        super().resizeEvent(event)
        if self.content is None:
            return
        # 只在宽度真正变化时重算，避免 setFixedHeight/updateGeometry 触发的无限递归
        if self.width() == self._last_width:
            return
        self._last_width = self.width()
        # 可用宽度 = 气泡总宽 - 头像(28) - 左右外边距(8+8) - 头像间距(8) - 右侧留白
        avail = self.width() - 28 - 8 - 8 - 8 - 8
        self.content.setMaximumWidth(max(240, int(avail * 0.92)))
        self._adjust_height()

    def _adjust_height(self) -> None:
        """内容/宽度变化时，重算气泡高度并同步给 ChatView 更新 item。"""
        if self.content is None or self._adjusting:
            return
        self._adjusting = True
        doc = self.content.document()
        view_w = self.content.viewport().width()
        if view_w <= 0:
            view_w = 520
        doc.setTextWidth(view_w)
        content_h = int(doc.size().height())
        self.content.setMinimumHeight(content_h)
        self.content.setMaximumHeight(content_h)
        # 直接计算总高：content + 时间行(~16) + 气泡padding(16) + 外边距(8) + spacing(2)
        total_h = content_h + 48
        self._total_h = total_h
        self.updateGeometry()  # 通知布局 sizeHint 变化（不设 setFixedHeight，避免递归）
        self.size_changed.emit()
        self._adjusting = False


class AssistantBubble(BubbleBase):
    """助手消息气泡：左对齐，头像在左侧，名称+时间，Markdown 内容，操作按钮。

    支持流式更新：stream_append() 逐块追加内容，stream_finish() 收尾重渲染。
    操作按钮发出 copy_requested / redo_requested / share_requested 信号。
    """

    copy_requested = Signal(int)
    redo_requested = Signal(int)
    share_requested = Signal(int)
    size_changed = Signal()  # 气泡高度变化时发出，供 ChatView 更新 item 高度

    def __init__(
        self,
        text: str,
        palette: dict,
        theme: str,
        msg_idx: int = -1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(palette, parent)
        self.msg_idx = msg_idx
        self.theme = theme
        self._adjusting = False
        self._total_h = 0
        self._last_width = 0
        self._stream_buf = ""
        self._streaming = False
        self._build(text)

    def sizeHint(self) -> QSize:
        """重写 sizeHint：返回 _adjust_height 计算的精确高度，避免 QTextBrowser 默认 sizeHint 干扰。"""
        if self._total_h > 0:
            return QSize(super().sizeHint().width(), self._total_h)
        return super().sizeHint()

    def _build(self, text: str) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(8)
        outer.setAlignment(Qt.AlignTop)

        outer.addWidget(self._avatar_label("🐦‍⬛"), alignment=Qt.AlignTop)

        # 右侧列：名称时间 + 气泡 + 操作栏
        right_col = QVBoxLayout()
        right_col.setSpacing(3)

        meta = QHBoxLayout()
        meta.setSpacing(6)
        name = QLabel("Raven")
        name.setStyleSheet(f"color:{self.p['text_dim']};font-size:10pt;font-weight:600;")
        time_label = QLabel(f"· {_now_str()}")
        time_label.setStyleSheet(f"color:{self.p['text_muted']};font-size:10pt;")
        meta.addWidget(name)
        meta.addWidget(time_label)
        meta.addStretch(1)
        right_col.addLayout(meta)

        # 气泡 frame
        self.bubble = QFrame()
        self.bubble.setStyleSheet(
            f"background-color:{self.p['bg_input']};"
            f"border:1px solid {self.p['border']};"
            "border-radius:14px;"
        )
        bubble_layout = QVBoxLayout(self.bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)

        # Markdown 内容区（只读 QTextBrowser，透明背景）
        self.content = QTextBrowser()
        self.content.setReadOnly(True)
        self.content.setOpenExternalLinks(True)
        self.content.setFrameShape(QFrame.NoFrame)
        self.content.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content.setStyleSheet(
            f"background-color:transparent;color:{self.p['text']};"
            f"font-size:10.5pt;border:none;"
        )
        self.content.setHtml(render_md(text, self.theme))
        self.content.setMinimumWidth(400)
        self.content.setMaximumWidth(640)
        # 高度随内容自适应
        self.content.document().contentsChanged.connect(self._adjust_height)
        bubble_layout.addWidget(self.content)
        right_col.addWidget(self.bubble)

        # 操作栏
        actions = QHBoxLayout()
        actions.setSpacing(14)
        actions.setContentsMargins(4, 0, 0, 0)
        self.btn_copy = self._action_button("📋 复制", self.copy_requested)
        self.btn_redo = self._action_button("🔄️ 重做", self.redo_requested)
        self.btn_share = self._action_button("↗️ 分享", self.share_requested)
        actions.addWidget(self.btn_copy)
        actions.addWidget(self.btn_redo)
        actions.addWidget(self.btn_share)
        actions.addStretch(1)
        right_col.addLayout(actions)

        outer.addLayout(right_col, 1)
        self._adjust_height()

    def _action_button(self, text: str, signal: Signal) -> QPushButton:
        btn = QPushButton(text)
        btn.setFlat(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"color:{self.p['text_dim']};font-size:11pt;border:none;"
            "padding:2px 4px;background-color:transparent;"
        )
        btn.clicked.connect(lambda: signal.emit(self.msg_idx))
        return btn

    def resizeEvent(self, event) -> None:
        """宽度变化时重算高度（widget 被添加到布局后宽度从 0 变为实际值，必须重算）。"""
        super().resizeEvent(event)
        # 只在宽度真正变化时重算，避免 updateGeometry 触发的无限递归
        if self.width() == self._last_width:
            return
        self._last_width = self.width()
        self._adjust_height()

    def _adjust_height(self) -> None:
        """内容变化时自适应整个气泡高度，并发出 size_changed 信号。

        QListWidgetItem 的高度是添加时固定的，气泡内部内容高度变化后
        必须通过信号通知 ChatView 更新 item.sizeHint，否则气泡会被截断。
        """
        if self._adjusting:
            return
        self._adjusting = True
        doc = self.content.document()
        # viewport 宽度可能为 0（widget 尚未布局），用默认宽度兜底
        view_w = self.content.viewport().width()
        if view_w <= 0:
            view_w = 560
        doc.setTextWidth(view_w)
        content_h = int(doc.size().height())
        self.content.setMinimumHeight(content_h)
        self.content.setMaximumHeight(content_h)
        # 直接计算总高：content + 名称行(~20) + 气泡padding(16) + 操作栏(~28) + 各spacing(9) + 外边距(8)
        total_h = content_h + 84
        self._total_h = total_h
        self.updateGeometry()  # 通知布局 sizeHint 变化（不设 setFixedHeight，避免递归）
        self.size_changed.emit()
        self._adjusting = False

    def set_content(self, text: str) -> None:
        """设置完整内容并重渲染。"""
        self.content.setHtml(render_md(text, self.theme))
        self._adjust_height()

    def stream_begin(self) -> None:
        """开始流式输出：清空内容，进入流式状态。"""
        self._stream_buf = ""
        self._streaming = True
        self.content.clear()

    def stream_append(self, chunk: str) -> None:
        """流式追加一块文本（直接显示纯文本，不做 Markdown 解析）。"""
        self._stream_buf += chunk
        # 流式阶段直接显示纯文本，避免逐块解析 Markdown 闪烁
        cursor = self.content.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(chunk)
        self.content.setTextCursor(cursor)
        self.content.ensureCursorVisible()
        self._adjust_height()

    def stream_finish(self) -> None:
        """流式结束：用完整文本重渲染 Markdown，退出流式状态。"""
        self._streaming = False
        full = self._stream_buf
        self._stream_buf = ""
        self.set_content(full)


class ToolBubble(BubbleBase):
    """工具调用卡片：左对齐，工具图标，工具名 + 参数。"""

    def __init__(self, name: str, arguments: str, palette: dict, parent: QWidget | None = None) -> None:
        super().__init__(palette, parent)
        self._build(name, arguments)

    def _build(self, name: str, arguments: str) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 3, 8, 3)
        outer.setSpacing(8)
        outer.setAlignment(Qt.AlignTop)

        arrow = QLabel("›")
        arrow.setFixedWidth(28)
        arrow.setAlignment(Qt.AlignCenter)
        arrow.setStyleSheet(f"color:{self.p['tool']};font-size:14px;font-weight:bold;")
        outer.addWidget(arrow, alignment=Qt.AlignTop)

        card = QFrame()
        card.setStyleSheet(
            f"background-color:{self.p['bg_input']};"
            f"border:1px solid {self.p['border']};"
            "border-radius:10px;"
        )
        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        name_label = QLabel(f"🔧 {name}")
        name_label.setStyleSheet(f"color:{self.p['accent']};font-size:10pt;font-weight:600;")
        args_label = QLabel(arguments)
        args_label.setWordWrap(True)
        args_label.setStyleSheet(f"color:{self.p['text_dim']};font-size:10pt;")
        args_label.setMaximumWidth(560)

        layout.addWidget(name_label)
        layout.addWidget(args_label, 1)
        outer.addWidget(card, 1)


class ErrorBubble(BubbleBase):
    """错误消息卡片：左对齐，红色边框。"""

    def __init__(self, text: str, palette: dict, parent: QWidget | None = None) -> None:
        super().__init__(palette, parent)
        self._build(text)

    def _build(self, text: str) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 3, 8, 3)
        outer.setSpacing(8)
        outer.setAlignment(Qt.AlignTop)

        icon = QLabel("!")
        icon.setFixedWidth(28)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"color:{self.p['error']};font-size:14px;font-weight:bold;")
        outer.addWidget(icon, alignment=Qt.AlignTop)

        card = QFrame()
        card.setStyleSheet(
            f"background-color:{self.p['bg_input']};"
            f"border:1px solid {self.p['error']};"
            "border-radius:10px;"
        )
        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        label = QLabel(f"⚠ 错误: {text}")
        label.setWordWrap(True)
        label.setStyleSheet(f"color:{self.p['error']};font-size:10pt;")
        layout.addWidget(label)
        outer.addWidget(card, 1)


class WelcomeWidget(BubbleBase):
    """空状态欢迎界面：大图标 + 标题 + 建议卡片。"""

    suggestion_clicked = Signal(str)

    def __init__(self, palette: dict, parent: QWidget | None = None) -> None:
        super().__init__(palette, parent)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(12)
        layout.setContentsMargins(40, 60, 40, 40)

        icon = QLabel("🐦‍⬛")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size:52pt;")
        layout.addWidget(icon)

        title = QLabel("有什么可以帮你的？")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"color:{self.p['text']};font-size:17pt;font-weight:600;")
        layout.addWidget(title)

        subtitle = QLabel("选择下方建议，或直接在输入框输入问题")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(f"color:{self.p['text_dim']};font-size:11pt;")
        layout.addWidget(subtitle)

        # 建议卡片（2x2 网格）：大尺寸、无硬边框、柔和圆角 + 悬停高亮
        suggestions = [
            ("🚀 帮我写代码", "用 Python 实现一个快速排序"),
            ("💡 解释概念", "什么是分治算法？"),
            ("📄 文件操作", "读取并分析一个 JSON 文件"),
            ("🐞 调试助手", "这段代码为什么报错？"),
        ]
        from PySide6.QtWidgets import QGridLayout

        grid = QGridLayout()
        grid.setSpacing(14)
        for i, (title_text, desc) in enumerate(suggestions):
            card = QFrame()
            card.setCursor(Qt.PointingHandCursor)
            card.setStyleSheet(
                f"background-color:{self.p['bg_input']};"
                "border:none;"
                "border-radius:14px;"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(20, 16, 20, 16)
            card_layout.setSpacing(6)
            t = QLabel(title_text)
            t.setStyleSheet(f"color:{self.p['accent']};font-size:12pt;")
            d = QLabel(desc)
            d.setStyleSheet(f"color:{self.p['text_dim']};font-size:10.5pt;")
            d.setWordWrap(True)
            card_layout.addWidget(t)
            card_layout.addWidget(d)
            # 点击与悬停交互（无边框、悬停时背景加深）
            card.mousePressEvent = lambda e, txt=desc: self.suggestion_clicked.emit(txt)
            card.enterEvent = lambda e, c=card: c.setStyleSheet(
                f"background-color:{self.p['bg_hover']};border:none;border-radius:14px;"
            )
            card.leaveEvent = lambda e, c=card: c.setStyleSheet(
                f"background-color:{self.p['bg_input']};border:none;border-radius:14px;"
            )
            grid.addWidget(card, i // 2, i % 2)

        layout.addLayout(grid)
        layout.addStretch(1)
