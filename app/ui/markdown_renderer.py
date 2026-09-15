"""Markdown 渲染器：把 Markdown 文本转为 QTextBrowser 可用的内联样式 HTML。

支持：代码块（pygments 语法高亮）、行内代码、标题、加粗/斜体、
无序/有序列表、链接。其余按普通段落处理。

从 main_window.py 抽离，供气泡 widget 和主窗口共享，避免循环导入。
"""
from __future__ import annotations

import html
import re


def inline_md(s: str) -> str:
    """处理一段文本中的行内 Markdown：行内代码、加粗、斜体、链接。"""
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def highlight_code(code: str, lang: str, theme: str) -> str:
    """用 pygments 对代码做语法高亮，返回内联样式 HTML。

    QTextDocument 不支持 CSS class，逐 token 生成内联 <span style="color:...">。
    暗色主题用 monokai，亮色主题用 default。pygments 不可用时回退等宽纯文本。
    """
    style_name = "monokai" if theme in ("dark", "teal_yellow") else "default"
    try:
        from pygments import lex
        from pygments.lexers import TextLexer, get_lexer_by_name, guess_lexer
        from pygments.styles import get_style_by_name
    except Exception:
        body = html.escape(code)
        bg = "#152238" if theme in ("dark", "teal_yellow") else "#f5f5f5"
        return (
            f'<pre style="margin:6px 0 10px 0;background-color:{bg};padding:10px 12px;'
            f'border-radius:6px;font-size:10pt;line-height:1.5;">{body}</pre>'
        )

    try:
        lexer = get_lexer_by_name(lang) if lang else guess_lexer(code)
    except Exception:
        try:
            lexer = guess_lexer(code)
        except Exception:
            lexer = TextLexer()
    style = get_style_by_name(style_name)
    # 自定义代码块背景色：暗色主题用深蓝灰（和整体 #0d1b2a 协调），亮色用浅灰
    if theme in ("dark", "teal_yellow"):
        bg = "#152238"
        border = "#1e3a5f"
    else:
        bg = "#f5f5f5"
        border = "#e0e0e0"
    parts: list[str] = []
    for ttype, value in lex(code, lexer):
        if not value:
            continue
        color = style.style_for_token(ttype).get("color")
        esc = html.escape(value).replace("\n", "<br>")
        if color:
            parts.append(f'<span style="color:#{color};">{esc}</span>')
        else:
            parts.append(esc)
    return (
        '<pre style="margin:6px 0 10px 0;background-color:'
        f"{bg};padding:10px 12px;border-radius:6px;border:1px solid {border};"
        f'font-size:10pt;line-height:1.5;">'
        f"{''.join(parts)}</pre>"
    )


def render_md(text: str, theme: str = "dark") -> str:
    """把 Markdown 文本渲染为富文本 HTML，供 QTextBrowser 显示。

    流式输出结束时整段重渲染，因此一次性转换即可。
    """
    lines = text.split("\n")
    out: list[str] = []
    in_code = False
    code_buf: list[str] = []
    list_buf: list[tuple[str, str]] = []

    def flush_list() -> None:
        if not list_buf:
            return
        tag = "ul" if list_buf[0][0] == "ul" else "ol"
        out.append(
            f'<{tag} style="margin:4px 0 8px 0;">'
            + "".join(f"<li>{inline_md(c)}</li>" for _, c in list_buf)
            + f"</{tag}>"
        )
        list_buf.clear()

    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("```"):
            if not in_code:
                in_code = True
                code_buf = [s[3:].strip()]
            else:
                in_code = False
                flush_list()
                out.append(highlight_code("\n".join(code_buf[1:]), code_buf[0], theme))
                code_buf = []
            i += 1
            continue
        if in_code:
            code_buf.append(lines[i])
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if m:
            flush_list()
            lvl = len(m.group(1))
            out.append(f'<h{lvl} style="margin:8px 0 4px 0;">{inline_md(m.group(2))}</h{lvl}>')
            i += 1
            continue
        m = re.match(r"^[-*+]\s+(.*)", s)
        if m:
            list_buf.append(("ul", m.group(1)))
            i += 1
            continue
        m = re.match(r"^\d+\.\s+(.*)", s)
        if m:
            list_buf.append(("ol", m.group(1)))
            i += 1
            continue
        flush_list()
        if not s:
            i += 1
            continue
        para = [lines[i]]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt or nxt.startswith(("```", "#", "-", "*", "+")):
                break
            if re.match(r"^\d+\.\s+", nxt):
                break
            para.append(lines[i])
            i += 1
        out.append(f'<p style="margin:0 0 6px 0;">{"<br>".join(inline_md(line) for line in para)}</p>')

    flush_list()
    if in_code:
        out.append(highlight_code("\n".join(code_buf[1:]), code_buf[0], theme))
    return "".join(out)
