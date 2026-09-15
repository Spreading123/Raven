"""从 .ui 文件加载界面（方案 A：QUiLoader 运行时加载）。

加载后会把控件绑定为宿主对象的属性，便于直接访问。
同时加载独立的 QSS 样式文件（按主题渲染）并应用到宿主窗口（结构与样式分离）。
"""
from __future__ import annotations

import string

from PySide6.QtCore import QFile, QIODevice, Qt
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QFrame, QPushButton, QWidget

from ui.themes import THEMES, THEME_ORDER, validate_themes
from app.utils.paths import RESOURCE_ROOT

UI_DIR = RESOURCE_ROOT / "ui"
STYLE_DIR = UI_DIR / "styles"

# 样式加载顺序：先全局基础，再按界面区域叠加（顺序即优先级）。
_STYLE_FILES = (
    "base.qss",
    "titlebar.qss",
    "sidebar.qss",
    "chat.qss",
    "input.qss",
)

DEFAULT_THEME = "teal_yellow"

_loader = QUiLoader()

# 启动时校验主题完整性（缺键会在开发期立刻暴露）
validate_themes()


def load_ui(name: str, host: object) -> object:
    """加载 ui 目录下的 .ui 文件，并把控件绑定到宿主对象上。

    Args:
        name: .ui 文件名，如 "main_window.ui"。
        host: 承载界面的宿主对象（通常是 self）。

    Returns:
        加载的根控件。
    """
    path = UI_DIR / name
    file = QFile(str(path))
    if not file.open(QIODevice.ReadOnly):
        raise FileNotFoundError(f"无法打开 UI 文件: {path}")

    root = _loader.load(file)
    file.close()
    if root is None:
        raise RuntimeError(f"加载 UI 文件失败: {path}")

    if isinstance(host, QWidget) and isinstance(root, QWidget):
        # 把 .ui 根控件的窗口尺寸属性应用到宿主窗口（geometry/minimumSize）
        host.resize(root.width(), root.height())
        host.setMinimumSize(root.minimumWidth(), root.minimumHeight())
        # 关键：把界面的布局直接铺到宿主窗口上，去掉多余的中间壳子，
        # 让宿主窗口本身承载界面，从而能直接收到边缘鼠标事件（用于拖拽缩放）。
        layout = root.layout()
        root.setLayout(None)
        host.setLayout(layout)
        root.deleteLater()

    _bind_children(host, host)
    # 统一为所有可点击/可选控件设置手型光标（与标题栏按钮 btn_close 等一致）
    _apply_clickable_cursors(host)
    apply_theme(host, DEFAULT_THEME)
    return host


def apply_theme(host: QWidget, theme_name: str = DEFAULT_THEME) -> None:
    """应用指定主题到宿主窗口（可运行时切换）。

    Args:
        host: 目标窗口。
        theme_name: 主题名（见 ui.themes.THEMES 键）。
    """
    if theme_name not in THEMES:
        raise KeyError(f"未知主题: {theme_name!r}，可选: {list(THEMES)}")
    host.setProperty("theme", theme_name)
    host.setStyleSheet(_render_style(theme_name))
    # setStyleSheet 会让 Qt 重算样式，把 QComboBox 弹层容器（私有 QFrame）
    # 的 frame 重置回默认 StyledPanel（1px 描边）。这里在样式应用之后
    # 立即去掉这些容器的 frame，消除下拉列表周围那圈难看的细边缘。
    _strip_combo_frames(host)


def _render_style(theme_name: str) -> str:
    """按主题渲染全部 QSS 模板，返回拼接后的样式文本。"""
    palette = THEMES[theme_name]
    parts = []
    for file_name in _STYLE_FILES:
        path = STYLE_DIR / file_name
        if not path.exists():
            raise FileNotFoundError(f"样式文件缺失: {path}")
        parts.append(string.Template(path.read_text(encoding="utf-8")).substitute(palette))
    return "\n".join(parts)


def current_theme(host: QWidget) -> str:
    """返回宿主窗口当前使用的主题名。"""
    return str(host.property("theme") or DEFAULT_THEME)


def theme_names() -> tuple[str, ...]:
    """返回所有可用主题名（按菜单展示顺序）。"""
    return THEME_ORDER


def _strip_combo_frames(host: QWidget) -> None:
    """去掉所有 QComboBox 下拉弹层容器自带的 1px 描边边缘。

    QComboBox 的下拉弹层是一个私有容器 QComboBoxPrivateContainer
    （QFrame 子类）。它默认带一个 StyledPanel 边框（约 1px），且因是
    私有类，QSS 无法直接选中。而 setStyleSheet 应用样式时会让 Qt 把
    该容器重置回默认 StyledPanel，因此在 apply_theme 里、样式应用之后
    调用本函数，把容器 frame 去掉，让选项列表填满弹层、消除那圈边缘。
    """
    from PySide6.QtWidgets import QComboBox

    for combo in host.findChildren(QComboBox):
        view = combo.view()
        container = view.parent() if view is not None else None
        if container is not None and hasattr(container, "setFrameShape"):
            container.setFrameShape(QFrame.Shape.NoFrame)
            container.setFrameShadow(QFrame.Shadow.Plain)
            container.setLineWidth(0)
            container.setMidLineWidth(0)



def _bind_children(host: object, root: object) -> None:
    """把 root 及其具名子控件绑定为 host 的属性。"""
    widgets = [root, *root.findChildren(object)]
    for w in widgets:
        name = w.objectName()
        if name and not hasattr(host, name):
            setattr(host, name, w)


def _apply_clickable_cursors(host: QWidget) -> None:
    """统一为宿主窗口内所有可点击/可选控件设置手型光标。

    覆盖：
        - QPushButton（普通按钮）
        - QToolButton（图标按钮）
        - QListWidget（导航栏 / 历史记录列表项）
        - QComboBox / QCheckBox / QRadioButton（可选控件）

    说明：QSS 的 ``cursor`` 属性在当前 Qt/PySide6 版本不被支持
    （会报 ``Unknown property cursor``），因此这里改用 Qt 原生
    ``setCursor``，对所有可交互控件应用与标题栏按钮（btn_close 等）
    一致的手型光标，无需逐个写入 .ui 文件。
    """
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QFrame,
        QListWidget,
        QPushButton,
        QRadioButton,
        QToolButton,
    )

    clickable_types = (
        QPushButton,
        QToolButton,
        QListWidget,
        QComboBox,
        QCheckBox,
        QRadioButton,
    )
    pointing = Qt.CursorShape.PointingHandCursor
    for control in host.findChildren(QWidget):
        if isinstance(control, clickable_types):
            control.setCursor(pointing)
            # QComboBox 的下拉选项是独立的弹出 view（QComboBox::view()，
            # 一个 QListView）。若不处理，下拉列表里的选项仍是默认箭头光标，
            # 需要把 view 及其 viewport 也设为手型，选项悬停时才会显示手型。
            if isinstance(control, QComboBox):
                view = control.view()
                if view is not None:
                    view.setCursor(pointing)
                    vp = view.viewport()
                    if vp is not None:
                        vp.setCursor(pointing)

            # QListWidget 等基于 item 的视图（QAbstractScrollArea 子类）：
            # 鼠标悬停在列表项上时，使用的是 viewport() 的光标而非 widget 本身。
            # 因此需同时给 viewport 设置手型，否则列表项上仍是箭头。
            elif hasattr(control, "viewport"):
                vp = control.viewport()
                if vp is not None:
                    vp.setCursor(pointing)



