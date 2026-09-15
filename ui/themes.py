"""主题系统：定义多套界面主题调色板。

每套主题是一份颜色变量表，由 loader 渲染进 QSS 模板实现换肤。
新增主题只需在此追加一项。
"""
from __future__ import annotations

# 所有主题必须提供的颜色变量键
THEME_KEYS = (
    "bg",           # 窗口 / 聊天主背景
    "bg_side",      # 侧栏背景
    "bg_title",     # 标题栏背景
    "bg_input",     # 输入框背景
    "bg_hover",     # 悬停 / 选中 / 滚动条滑块
    "bg_hover2",    # 更强悬停
    "border",       # 边框
    "sel_bg",       # 下拉框选中/悬停项底色
    "sel_fg",       # 下拉框选中/悬停项文字色
    "text",         # 主文字
    "text_dim",     # 次要文字
    "text_muted",   # 更弱文字
    "accent",       # 强调色（发送按钮 / 工具名）
    "accent_hover", # 强调色悬停
    "btn",          # 普通按钮背景
    "btn_hover",    # 按钮悬停
    "icon",         # 图标色
    "user",         # 用户消息色
    "tool",         # 工具消息色
    "error",        # 错误消息色
)

# 主题顺序（即弹出菜单展示顺序）
THEME_ORDER = ("teal_yellow", "pink", "light", "dark")

THEME_LABELS = {
    "dark": "🌑 默认黑灰",
    "light": "🌕 白色",
    "teal_yellow": "🌀 深青蓝 + 黄",
    "pink": "🌸 可爱粉色",
}

# 每套主题的调色板
THEMES: dict[str, dict[str, str]] = {
    # ① 默认黑灰（纯黑灰色系，无色相偏移）
    "dark": {
        "bg": "#1a1a1a",
        "bg_side": "#212121",
        "bg_title": "#1d1d1d",
        "bg_input": "#262626",
        "bg_hover": "#333333",
        "bg_hover2": "#404040",
        "border": "#3a3a3a",
        "sel_bg": "#3d4b5c",
        "sel_fg": "#e6e6e6",
        "text": "#e6e6e6",
        "text_dim": "#9a9a9a",
        "text_muted": "#6b6b6b",
        "accent": "#e6e6e6",
        "accent_hover": "#ffffff",
        "btn": "#3a3a3a",
        "btn_hover": "#4a4a4a",
        "icon": "#b3b3b3",
        "user": "#e6e6e6",
        "tool": "#9a9a9a",
        "error": "#cf6679",
    },
    # ② 白色
    "light": {
        "bg": "#f4f5f7",
        "bg_side": "#eef0f3",
        "bg_title": "#ffffff",
        "bg_input": "#ffffff",
        "bg_hover": "#dfe3ea",
        "bg_hover2": "#c9d0da",
        "border": "#d6dae0",
        "sel_bg": "#e3ecff",
        "sel_fg": "#2a2e34",
        "text": "#2a2e34",
        "text_dim": "#7a828c",
        "text_muted": "#a6adb6",
        "accent": "#4a7df0",
        "accent_hover": "#3a6de0",
        "btn": "#e3e7ee",
        "btn_hover": "#d2d8e2",
        "icon": "#6b7280",
        "user": "#2f5fd0",
        "tool": "#5a6470",
        "error": "#d64550",
    },
    # ③ 深青蓝 + 黄（流行对比色）
    "teal_yellow": {
        "bg": "#0d1b2a",
        "bg_side": "#0f2438",
        "bg_title": "#0e2031",
        "bg_input": "#122a3d",
        "bg_hover": "#1d3a52",
        "bg_hover2": "#2a4a66",
        "border": "#1f3a50",
        "sel_bg": "#24425c",
        "sel_fg": "#e8f0f8",
        "text": "#e8f0f8",
        "text_dim": "#7fa0b8",
        "text_muted": "#54708a",
        "accent": "#ffd23f",
        "accent_hover": "#ffdf66",
        "btn": "#1e3a52",
        "btn_hover": "#2a4a66",
        "icon": "#7fa0b8",
        "user": "#ffd23f",
        "tool": "#7fa0b8",
        "error": "#e07a5f",
    },
    # ④ 可爱粉色
    "pink": {
        "bg": "#fff0f5",
        "bg_side": "#ffe3ec",
        "bg_title": "#ffd9e6",
        "bg_input": "#ffffff",
        "bg_hover": "#ffc4d6",
        "bg_hover2": "#f7a8c0",
        "border": "#f0b8cc",
        "sel_bg": "#f7b3c9",
        "sel_fg": "#5a2a3d",
        "text": "#5a2a3d",
        "text_dim": "#b06a83",
        "text_muted": "#cc8ba0",
        "accent": "#ff6fa5",
        "accent_hover": "#ff85b5",
        "btn": "#ffd3e0",
        "btn_hover": "#ffb8cc",
        "icon": "#e06a92",
        "user": "#d6336c",
        "tool": "#9c4a63",
        "error": "#e0566b",
    },
}


def validate_themes() -> None:
    """校验每个主题都提供了全部颜色键，缺失则报错（开发期防御）。"""
    for name, palette in THEMES.items():
        missing = [k for k in THEME_KEYS if k not in palette]
        if missing:
            raise KeyError(f"主题 {name!r} 缺少颜色键: {missing}")
