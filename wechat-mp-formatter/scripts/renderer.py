#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AST -> 微信公众号可用 HTML（全部内联样式）。

微信编辑器会剥离 <style>、class、id、script，所以这里生成的每一个可见元素
都必须自带 style 属性。详见 references/wechat-editor-rules.md。
"""

import re

from highlighter import highlight, CODE_THEMES, DEFAULT_CODE_THEME, normalize_lang, LANG_LABEL

# ---------------------------------------------------------------------------
# 文章主题
#
# 每个主题 12 个色位，职责划分（改配色时请守住这个分工，否则整体会「不成套」）：
#   accent       主色：装饰元素（竖条、圆点、分隔线、渐变条）与链接
#   accent_deep  主色的深色版：**所有标题文字**与行内代码文字。必须保证在白底上
#                有足够对比度（≥ 4.5:1），所以不能直接用 accent 当标题色
#                ——暖橙、亮绿这类主色直接当文字会「糊」
#   accent_soft  主色的浅色版：引用底、行内代码底、表格表头底、片尾底
#   title        标题色（= accent_deep，保留该键是为了兼容旧调用方）
#   text         正文色（略偏主题的深灰，不要用纯黑）
#   muted        次要文字（署名、图注、语言标签）
#   link         链接色
#   quote_bg     引用块底色     border  边框/分割线底色
#   zebra        表格斑马纹底色（很浅的主题色）
#   code_theme   该主题默认搭配的代码配色
#
# 顺序即界面下拉框顺序，**第一项是默认主题**（青竹绿，与工作台界面的微信绿呼应）。
# ---------------------------------------------------------------------------

ARTICLE_THEMES = {
    "green": {
        "label": "青竹绿",
        "accent": "#0a9a5c",
        "accent_deep": "#07663e",
        "accent_soft": "#e8f6ef",
        "title": "#07663e",
        "text": "#3b4a43",
        "muted": "#8ba398",
        "link": "#0a8f57",
        "quote_bg": "#f1f9f5",
        "border": "#d5eadf",
        "zebra": "#f7fcf9",
        "code_theme": "github-light",
    },
    "blue": {
        "label": "科技蓝",
        "accent": "#1f6feb",
        "accent_deep": "#17469e",
        "accent_soft": "#eaf1fe",
        "title": "#17469e",
        "text": "#3b4757",
        "muted": "#8b95a5",
        "link": "#1f6feb",
        "quote_bg": "#f2f6fe",
        "border": "#d8e4fa",
        "zebra": "#f8fafe",
        "code_theme": "one-dark",
    },
    "purple": {
        "label": "紫霞",
        "accent": "#7b52d9",
        "accent_deep": "#5630a8",
        "accent_soft": "#f3eefc",
        "title": "#5630a8",
        "text": "#453e56",
        "muted": "#9a92ac",
        "link": "#7b52d9",
        "quote_bg": "#f8f5fd",
        "border": "#e4daf7",
        "zebra": "#fbf9fe",
        "code_theme": "dracula",
    },
    "red": {
        "label": "中国红",
        "accent": "#d0342c",
        "accent_deep": "#9c1f19",
        "accent_soft": "#fdeceb",
        "title": "#9c1f19",
        "text": "#4a3e3c",
        "muted": "#a89593",
        "link": "#c8362f",
        "quote_bg": "#fdf4f3",
        "border": "#f4dcd9",
        "zebra": "#fefaf9",
        "code_theme": "monokai",
    },
    "orange": {
        "label": "暖阳橙",
        "accent": "#ee7a1e",
        "accent_deep": "#9c4a06",
        "accent_soft": "#fdf2e6",
        "title": "#9c4a06",
        "text": "#4a4238",
        "muted": "#a89787",
        "link": "#c2610a",
        "quote_bg": "#fdf7f0",
        "border": "#f4e3cf",
        "zebra": "#fefbf7",
        "code_theme": "github-light",
    },
    "classic": {
        "label": "经典墨黑",
        "accent": "#4b5563",
        "accent_deep": "#1f2937",
        "accent_soft": "#f2f4f7",
        "title": "#1f2937",
        "text": "#3f454e",
        "muted": "#8d939c",
        "link": "#576b95",
        "quote_bg": "#f6f7f9",
        "border": "#e4e7eb",
        "zebra": "#fafbfc",
        "code_theme": "one-dark",
    },
}

DEFAULT_THEME = "green"

# 正文字号：16px 为默认（移动端最佳阅读字号，也是公众号编辑器默认值）
DEFAULT_FONT_SIZE = 16
MIN_FONT_SIZE = 12
MAX_FONT_SIZE = 20
# 派生字号的兜底下限：正文调到 12px 时，「字号 − 3」会把代码块/图注压到 9px，
# 那已经不可读了，所以所有派生字号都不低于这个值
MIN_DERIVED_FONT_SIZE = 11

MONO_FONT = "Menlo,Monaco,Consolas,'Courier New',monospace"

RE_CODE_SPAN = re.compile(r'<code-span(?:\s+style="([^"]*)")?>(.*?)</code-span>', re.S)
RE_IMG = re.compile(r'<img\s+([^>]*?)/?>', re.S)
RE_A = re.compile(r'<a\s+href="([^"]*)"(?:\s+title="[^"]*")?\s*>(.*?)</a>', re.S)
RE_TAG_STRIP = re.compile(r"</?(?:code-span)[\s>]*")


def _attr_val(attrs: str, name: str):
    m = re.search(r'%s\s*=\s*"([^"]*)"' % name, attrs)
    return m.group(1) if m else None


def _drop_style(attrs: str) -> str:
    return re.sub(r'\s*style\s*=\s*"[^"]*"', "", attrs).strip()


# ---------------------------------------------------------------------------
# 列表序号
#
# 序号一律**写成文本**（`1.` / `a.` / `•`），不依赖 list-style。
# 原因和代码块一模一样：序号本来就该是内容的一部分，交给 CSS 就多了一层会被微信
# 洗掉的依赖。实测把编号交给 <ol> + list-style-type 时，微信重排后整篇的有序项
# 会全部显示成 "1."（尤其是同一个列表中间夹了段落或代码块、被拆成多个 <ol> 时，
# 每个 <ol> 都从 1 重新开始）。
# ---------------------------------------------------------------------------

BULLET_MARKERS = ("•", "◦", "▪")


def _alpha_marker(n: int) -> str:
    """1 -> a, 26 -> z, 27 -> aa"""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(97 + r) + s
    return s or "a"


def _roman_marker(n: int) -> str:
    """小写罗马数字，超出常见范围就退回阿拉伯数字（1 -> i, 4 -> iv）"""
    if not 1 <= n <= 3999:
        return str(n)
    table = ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
             (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"))
    out = []
    for v, sym in table:
        while n >= v:
            out.append(sym)
            n -= v
    return "".join(out)


def ordinal_marker(n: int, depth: int = 0) -> str:
    """有序项的文字序号：一层 1. / 二层 a. / 三层 i.（对应原来的 decimal/lower-alpha/lower-roman）"""
    depth = max(0, depth)
    if depth == 0:
        return "%d." % n
    if depth == 1:
        return "%s." % _alpha_marker(n)
    return "%s." % _roman_marker(n)


def bullet_marker(depth: int = 0) -> str:
    """无序项的文字圆点：一层 • / 二层 ◦ / 三层 ▪（对应原来的 disc/circle/square）"""
    return BULLET_MARKERS[min(max(0, depth), len(BULLET_MARKERS) - 1)]


# ---------------------------------------------------------------------------
# 渲染器
# ---------------------------------------------------------------------------

class Renderer:
    def __init__(self, theme="classic", code_theme=None, opts=None):
        self.theme = ARTICLE_THEMES.get(theme, ARTICLE_THEMES[DEFAULT_THEME])
        self.theme_name = theme
        self.code_theme = code_theme or self.theme.get("code_theme", DEFAULT_CODE_THEME)
        if self.code_theme not in CODE_THEMES:
            self.code_theme = DEFAULT_CODE_THEME
        self.ct = CODE_THEMES[self.code_theme]
        o = opts or {}
        self.line_numbers = bool(o.get("line_numbers"))
        self.code_chrome = bool(o.get("code_chrome", True))
        # block：长行折行（默认，移动端不溢出）；scroll：长行不折、横向滚动
        mode = o.get("code_mode", "block")
        if mode == "pre":          # 旧版参数兼容：语义等同"不折行"
            mode = "scroll"
        self.code_mode = mode
        self.code_wrap = (mode != "scroll")
        self.heading_style = o.get("heading_style", "modern")
        self.divider = o.get("divider", "dots")
        self.link_mode = o.get("link_mode", "keep")
        self.flat_tags = bool(o.get("flat_tags"))
        self.show_lang_label = bool(o.get("lang_label", True))
        # 正文字号基准：16px 是移动端（含 iPhone 18 Pro 的 402pt 视口）公认的最佳阅读字号，
        # 也是公众号编辑器自身的默认值。其余元素的字号都按相对偏移从它推导，见 _fs()。
        try:
            fs = int(o.get("font_size", DEFAULT_FONT_SIZE) or DEFAULT_FONT_SIZE)
        except (TypeError, ValueError):
            fs = DEFAULT_FONT_SIZE
        self.font_size = min(MAX_FONT_SIZE, max(MIN_FONT_SIZE, fs))
        self.stats = {"words": 0, "code_blocks": 0, "code_lines": 0, "images": 0, "tables": 0}
        # 有序列表的当前计数（按嵌套层分桶）。见 _list() 的说明：同一个标题下、
        # 中间夹了正文/代码块的连续有序列表要接着往下编号，而不是各自从 1 开始。
        self._ol_counters = {}

    def _reset_ol_counters(self):
        """遇到标题 / 分隔线：编号重新从 1 开始（新的一节就是新的一轮编号）。"""
        self._ol_counters = {}

    def _fs(self, delta=0):
        """按正文基准字号推导其他元素的字号（px，保持整数）。

        带下限：正文选 12px 时，代码块（−3）会被压到 9px，已不可读，
        所以派生字号一律不低于 MIN_DERIVED_FONT_SIZE。
        """
        return max(MIN_DERIVED_FONT_SIZE, self.font_size + delta)

    # ------------------------------------------------------------- 对外
    def render(self, blocks, meta=None):
        meta = meta or {}
        self._reset_ol_counters()
        parts = []
        if meta.get("title") or meta.get("author") or meta.get("date"):
            parts.append(self._render_header(meta))
        for b in blocks:
            parts.append(self._block(b))
        if meta.get("footer"):
            parts.append(self._render_footer(meta["footer"]))
        body = "\n".join(p for p in parts if p)
        wrapper = (
            '<section style="font-size:{fs}px;color:{text};line-height:1.75;letter-spacing:.5px;'
            'padding:0 2px;word-break:break-word;-webkit-text-size-adjust:100%">'
        ).format(fs=self.font_size, text=self.theme["text"])
        return wrapper + "\n" + body + "\n</section>"

    # ------------------------------------------------------------- 片头/片尾
    def _render_header(self, meta):
        t = self.theme
        out = ['<section style="margin:0 0 30px;padding:22px 0 20px;border-bottom:1px solid {b};'
               'text-align:center">'.format(b=t["border"])]
        # 标题上方的小渐变条：给片头一个「设计过」的锚点，而不是干巴巴一行大字
        out.append('<p style="margin:0 0 14px;text-align:center;line-height:0;font-size:0">'
                   '<span style="display:inline-block;width:32px;height:3px;border-radius:2px;'
                   'background-image:linear-gradient(90deg,{a} 0%,{s} 100%)"></span></p>'.format(
                       a=t["accent"], s=t["accent_soft"]))
        if meta.get("title"):
            out.append('<p style="margin:0 0 10px;font-size:{fs}px;font-weight:bold;color:{c};'
                       'line-height:1.35;letter-spacing:1px">{v}</p>'.format(
                           fs=self._fs(8), c=t["title"], v=self._esc(meta["title"])))
        sub = []
        if meta.get("author"):
            sub.append(self._esc(meta["author"]))
        if meta.get("date"):
            sub.append(self._esc(meta["date"]))
        if sub:
            out.append('<p style="margin:0;font-size:{fs}px;color:{c};letter-spacing:1px">{v}</p>'.format(
                fs=self._fs(-3), c=t["muted"], v="  ·  ".join(sub)))
        out.append("</section>")
        return "\n".join(out)

    def _render_footer(self, text):
        t = self.theme
        return ('<section style="margin:34px 0 8px;padding:16px 14px;background:{bg};'
                'border-radius:6px;text-align:center;font-size:{fs}px;color:{c};line-height:1.7">'
                '{v}</section>').format(bg=t["accent_soft"], fs=self._fs(-3),
                                        c=t["muted"], v=self._esc(text))

    # ------------------------------------------------------------- 块级
    def _block(self, b):
        t = b.get("type")
        if t == "heading":
            return self._heading(b)
        if t == "paragraph":
            return self._paragraph(b)
        if t == "code":
            return self._code(b)
        if t == "quote":
            return self._quote(b)
        if t == "list":
            return self._list(b)
        if t == "table":
            return self._table(b)
        if t == "hr":
            return self._hr()
        if t == "html":
            return self._raw_html(b.get("raw", ""))
        return ""

    @staticmethod
    def _esc(s):
        return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    def _count_words(self, html_str):
        plain = re.sub(r"<[^>]+>", "", html_str or "")
        plain = plain.replace("&nbsp;", " ")
        cjk = len(re.findall(r"[\u4e00-\u9fff]", plain))
        words = len(re.findall(r"[A-Za-z]+", plain))
        self.stats["words"] += cjk + words

    # ------------------------------------------------------------- 标题
    def _heading(self, b):
        level = max(1, min(int(b.get("level", 2)), 6))
        t = self.theme
        inline = self._inline(b.get("inline", ""))
        self._count_words(inline)
        # 新标题 = 新的一节：有序列表从这里重新从 1 开始编号
        self._reset_ol_counters()
        tag = "h%d" % min(level, 6)
        if self.flat_tags:
            tag = "p"

        if self.heading_style == "simple":
            sizes = {1: self._fs(5), 2: self._fs(3), 3: self._fs(1),
                     4: self._fs(-1), 5: self._fs(-2), 6: self._fs(-2)}
            style = (f"margin:{30 if level<=2 else 24}px 0 {14 if level<=2 else 10}px;"
                     f"font-size:{sizes.get(level, self._fs(-1))}px;font-weight:bold;"
                     f"color:{t['accent_deep']};"
                     f"line-height:1.4;letter-spacing:.5px")
            return f'<{tag} style="{style}">{inline}</{tag}>'

        # modern：标题一律用 accent_deep（主题色的深色版），装饰元素用 accent。
        # 不要再把标题设成近黑色 —— 那样整篇的「主题感」就只剩几条细线了。
        if level == 1:
            tag = "p" if self.flat_tags else "h1"
            head = (f'<{tag} style="margin:38px 0 12px;text-align:center;'
                    f'font-size:{self._fs(8)}px;'
                    f'font-weight:bold;color:{t["accent_deep"]};line-height:1.4;'
                    f'letter-spacing:.5px">'
                    f'{inline}</{tag}>')
            # 标题下方渐变色条：比纯色短横更有质感，也更能带出主题色
            line = (f'<p style="margin:0 0 26px;text-align:center;line-height:0;font-size:0">'
                    f'<span style="display:inline-block;width:58px;height:4px;border-radius:2px;'
                    f'background-image:linear-gradient(90deg,{t["accent"]} 0%,'
                    f'{t["accent_soft"]} 100%)"></span></p>')
            return head + "\n" + line
        if level == 2:
            tag = "p" if self.flat_tags else "h2"
            bar = (f'<span style="display:inline-block;width:4px;height:17px;'
                   f'background-image:linear-gradient(180deg,{t["accent"]} 0%,'
                   f'{t["accent_deep"]} 100%);'
                   f'border-radius:2px;margin-right:9px;vertical-align:-3px"></span>')
            return (f'<{tag} style="margin:32px 0 16px;font-size:{self._fs(3)}px;font-weight:bold;'
                    f'color:{t["accent_deep"]};line-height:1.45;letter-spacing:.5px">'
                    f'{bar}{inline}</{tag}>')
        if level == 3:
            tag = "p" if self.flat_tags else "h3"
            dot = (f'<span style="display:inline-block;width:6px;height:6px;border-radius:50%;'
                   f'background-color:{t["accent"]};margin-right:7px;vertical-align:2px"></span>')
            return (f'<{tag} style="margin:26px 0 12px;font-size:{self._fs(1)}px;font-weight:bold;'
                    f'color:{t["accent_deep"]};line-height:1.5">{dot}{inline}</{tag}>')
        size = {4: self._fs(-1), 5: self._fs(-2), 6: self._fs(-2)}.get(level, self._fs(-1))
        tag = "p" if self.flat_tags else "h%d" % level
        return (f'<{tag} style="margin:22px 0 10px;font-size:{size}px;font-weight:bold;'
                f'color:{t["accent_deep"]};line-height:1.6">{inline}</{tag}>')

    # ------------------------------------------------------------- 段落
    def _paragraph(self, b, compact=False):
        inline = self._inline(b.get("inline", ""))
        self._count_words(inline)
        if not inline.strip():
            return ""
        t = self.theme
        # 独占一行的图片 -> 居中 figure 效果
        img_match = RE_IMG.search(inline)
        rest = RE_IMG.sub("", inline).replace("<br>", "").strip()
        if img_match and not rest:
            return self._figure(inline)
        if compact:
            style = (f"margin:0 0 .9em;font-size:{self._fs(-1)}px;color:{t['text']};line-height:1.75;"
                     f"letter-spacing:.5px")
        else:
            style = (f"margin:0 0 1.4em;font-size:{self._fs(-1)}px;color:{t['text']};line-height:1.75;"
                     f"letter-spacing:.5px;text-align:justify")
        align = b.get("_align")
        if align == "center":
            style += ";text-align:center"
        elif align == "right":
            style += ";text-align:right"
        return f'<p style="{style}">{inline}</p>'

    def _figure(self, inline):
        # 图片计数已在 _inline 里做过，这里不重复统计
        out = []

        def repl(m):
            attrs = m.group(1)
            src = _attr_val(attrs, "src") or ""
            alt = _attr_val(attrs, "alt") or ""
            out.append((src, alt))
            return (f'<img src="{src}" alt="{alt}" style="max-width:100%;width:100%;'
                    f'display:block;margin:0 auto;border-radius:4px;vertical-align:middle">')
        body = RE_IMG.sub(repl, inline)
        html = f'<p style="margin:22px 0 0;text-align:center;line-height:1.2;font-size:0">{body}</p>'
        if out and out[0][1]:
            html += (f'<p style="margin:8px 0 22px;text-align:center;'
                     f'font-size:{self._fs(-3)}px;'
                     f'color:{self.theme["muted"]};line-height:1.6">{self._esc(out[0][1])}</p>')
        return html

    # ------------------------------------------------------------- 引用
    def _quote(self, b):
        t = self.theme
        inner = "\n".join(
            (self._block({"type": "paragraph", "inline": c["inline"], "_align": c.get("_align")})
             if c.get("type") == "paragraph" else self._block(c))
            for c in b.get("children", [])
        )
        # 引用内部段落去尾距
        inner = inner.replace("margin:0 0 1.4em;", "margin:0 0 .9em;")
        return (f'<blockquote style="margin:22px 0;padding:14px 16px;background-color:{t["quote_bg"]};'
                f'border-left:4px solid {t["accent"]};border-radius:0 4px 4px 0;'
                f'font-size:{self._fs(-1)}px;color:{t["text"]};line-height:1.75;'
                f'letter-spacing:.5px">{inner}</blockquote>')

    # ------------------------------------------------------------- 列表
    # 列表项的悬挂缩进（em）：marker 用这个宽度占位，正文首行再由 text-indent 拉回来，
    # 于是换行后的第二行起会和首行正文对齐。
    LI_INDENT = 1.9

    def _list_start(self, depth, explicit_start=None, restart=False):
        """这个有序列表从几开始编号。

        规则（现实写作里，一个列表常常被说明段落和代码块「打断」，那本来还是一串编号）：
          · 显式 start（Markdown 写了 "3." / Word 的起始值）优先；
          · 否则，顶层列表接着同一标题下的上一个有序列表往下数；
          · 遇到标题、分隔线，或解析器明确标了 restart（Word 里是另一个 numId）→ 重新从 1 开始。
        """
        if isinstance(explicit_start, int) and explicit_start > 0:
            return explicit_start
        if depth == 0 and not restart:
            return self._ol_counters.get(0, 0) + 1
        return 1

    @staticmethod
    def _fits_inline(sub):
        """这个段落能否直接内联到 marker 后面（能就别用 <p> 另起一行）。"""
        if sub.get("_align"):
            return False
        inline = sub.get("inline", "") or ""
        if not inline.strip():
            return False
        if RE_IMG.search(inline) and not RE_IMG.sub("", inline).replace("<br>", "").strip():
            return False    # 纯图片段落交给 _figure 处理
        return True

    def _list(self, b, depth=0):
        """渲染列表。

        刻意【不使用】<ol>/<ul>/<li>：
          · li 的序号/圆点来自 CSS 的 list-style，微信重排时一洗，整篇有序项会全变成 "1."
            或干脆没有编号；
          · 列表中间夹了段落或代码块时（写教程时非常常见），列表会被拆成多个 <ol>，
            每个 <ol> 都从 1 重新开始 —— 也就是「同一级标题下面的有序项全是 1」。
        所以序号直接写成文本（见 ordinal_marker / bullet_marker），由渲染器统一计数，
        每一层一个 <section>。这样无论微信怎么洗样式，编号都还是 1. 2. 3.。
        """
        t = self.theme
        ordered = bool(b.get("ordered"))
        items = b.get("items", []) or []
        if not items:
            return ""
        start = 1
        if ordered:
            start = self._list_start(depth, b.get("start"), bool(b.get("restart")))
            self._ol_counters[depth] = start + len(items) - 1

        pad = self.LI_INDENT
        rows = []
        for k, item_blocks in enumerate(items):
            text = ordinal_marker(start + k, depth) if ordered else bullet_marker(depth)
            mark = (f'<span style="display:inline-block;width:{pad}em;text-indent:0;'
                    f'color:{t["accent_deep"]};font-weight:bold">{text}&nbsp;</span>')
            head, rest = "", []
            for sub in item_blocks:
                if not head and sub.get("type") == "paragraph" and self._fits_inline(sub):
                    head = self._inline(sub.get("inline", ""))
                    self._count_words(head)
                    continue
                rest.append(self._render_item_block(sub, depth))
            body = ""
            if rest:
                # text-indent 是继承属性：这里必须显式清零，否则块级子内容（代码块、
                # 后续段落）的首行会被外层的悬挂缩进往左拽出去。
                body = '<section style="text-indent:0">%s</section>' % "".join(rest)
            rows.append(
                f'<section style="margin:6px 0;padding-left:{pad}em;text-indent:-{pad}em;'
                f'font-size:{self._fs(-1)}px;color:{t["text"]};line-height:1.75;'
                f'letter-spacing:.5px">{mark}{head}{body}</section>')
        return f'<section style="margin:14px 0">{"".join(rows)}</section>'

    def _render_item_block(self, sub, depth):
        if sub.get("type") == "list":
            return self._list(sub, depth + 1)
        if sub.get("type") == "code":
            return self._code(sub)
        if sub.get("type") == "paragraph":
            return self._paragraph(sub, compact=True)
        return self._block(sub)

    # ------------------------------------------------------------- 表格
    def _table(self, b):
        self.stats["tables"] += 1
        t = self.theme
        header = b.get("header", [])
        rows = b.get("rows", [])
        align = b.get("align", [""] * len(header))
        if not header and not rows:
            return ""

        def cell(c, is_head, i, stripe=False):
            ta = align[i] if i < len(align) else ""
            hal = {"center": "center", "right": "right", "left": "left"}.get(ta, "left" if is_head else "")
            tg = "th" if is_head else "td"
            base = ("border:1px solid %s;padding:8px 10px;font-size:%dpx;line-height:1.6;"
                    "text-align:%s" % (t["border"], self._fs(-2), hal))
            if is_head:
                # 表头：主题浅底 + 主题深色字，并在下沿压一条主题色实线分组
                # 注意别拼出 `;;`（空声明）——自检脚本会判定「style 写法异常」
                base += (";background-color:%s;color:%s;font-weight:bold"
                         ";border-bottom:1px solid %s"
                         % (t["accent_soft"], t["accent_deep"], t["accent"]))
            else:
                base += ";color:%s" % t["text"]
                if stripe:
                    base += ";background-color:%s" % t["zebra"]
            return "<%s style=\"%s\">%s</%s>" % (tg, base, self._inline(c), tg)

        thead = ""
        if header:
            thead = "<thead><tr>%s</tr></thead>" % "".join(
                cell(c, True, i) for i, c in enumerate(header))
        # 斑马纹只用于 tbody 的偶数行，避免长表格看串行
        tbody = "".join(
            "<tr>%s</tr>" % "".join(cell(c, False, i, stripe=(ri % 2 == 1))
                                    for i, c in enumerate(row))
            for ri, row in enumerate(rows))
        if tbody:
            tbody = "<tbody>%s</tbody>" % tbody
        table = ('<table style="border-collapse:collapse;width:100%;font-size:{fs}px;'
                 'border-spacing:0;margin:0">{h}{b}</table>').format(
                     fs=self._fs(-2), h=thead, b=tbody)
        return ('<section style="margin:22px 0;overflow-x:auto;-webkit-overflow-scrolling:touch;'
                'font-size:0">{t}</section>').format(t=table)

    # ------------------------------------------------------------- 分隔线
    def _hr(self):
        t = self.theme
        # 分隔线也是「这一组分完了」的信号，编号重新开始
        self._reset_ol_counters()
        if self.divider == "line":
            return f'<hr style="border:none;border-top:1px solid {t["border"]};margin:30px 0">'
        if self.divider == "gradient":
            return (f'<p style="margin:30px 0;text-align:center;line-height:0;font-size:0">'
                    f'<span style="display:inline-block;width:60px;height:3px;border-radius:2px;'
                    f'background-image:linear-gradient(90deg,{t["accent"]} 0%,{t["accent_soft"]} 100%)">'
                    f'</span></p>')
        # dots
        dot = (f'<span style="display:inline-block;width:5px;height:5px;border-radius:50%;'
               f'background-color:{t["accent"]};opacity:.45;margin:0 5px"></span>')
        return f'<p style="margin:30px 0;text-align:center;line-height:0;font-size:0">{dot*3}</p>'

    # ------------------------------------------------------------- 代码块
    def _code(self, b):
        """渲染代码块。

        刻意【不使用】<pre>/<code> 标签：
        公众号后台的「内容结构检测」会对 pre 报「内容不会自动换行，移动端可能出现水平溢出」，
        而 <pre> 赖以换行的 white-space 也正是溢出的根因。

        分行靠**每行一个 <section>**（块级来自标签语义，不依赖 CSS），
        缩靠把空格全部写成 &nbsp;，上色靠 token 级 <span style="color:#xxx">。
        三层里没有任何一层依赖 display / white-space —— 微信重排时把这些属性洗掉也不会串行。
        （曾用 <span style="display:block"> 分行，实测微信会丢掉 span 上的 display，
         几行代码会无缝挤成一行，详见 highlighter.highlight() 的说明。）
        """
        lang_raw = (b.get("lang") or "text").strip()
        lang = normalize_lang(lang_raw)
        code = b.get("code", "") or ""
        ct = self.ct

        self.stats["code_blocks"] += 1
        self.stats["code_lines"] += len(code.split("\n"))

        inner = highlight(code, lang, self.code_theme, mode="block",
                          line_numbers=self.line_numbers)
        label = LANG_LABEL.get(lang, lang_raw.upper() or "CODE")

        if self.code_wrap:
            # 默认：超长行在容器内折行，移动端不会水平溢出。
            # 只留 word-break：空格已全部写成 &nbsp;，不需要 white-space 参与，
            # 少一个属性就少一处被微信清洗的不确定性（实测 break-all 足以折行，无横向溢出）。
            layout = "word-break:break-all"
        else:
            # 可选：保持单行靠横向滚动，代码结构更"原样"，但超宽部分可能被裁掉
            layout = ("white-space:pre;word-break:normal;"
                      "overflow-x:auto;-webkit-overflow-scrolling:touch")

        body_style = (
            f"margin:0;padding:14px 14px 15px;background-color:{ct['bg']};"
            f"font-family:{MONO_FONT};font-size:{self._fs(-3)}px;line-height:1.65;color:{ct['fg']};"
            f"{layout};"
            f"border-radius:{'0 0 6px 6px' if self.code_chrome else '6px'}"
        )
        body = f'<section style="{body_style}">{inner}</section>'

        if not self.code_chrome:
            return f'<section style="margin:24px 0">{body}</section>'

        dots = "".join(
            f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;'
            f'background-color:{c};margin-right:6px;vertical-align:1px"></span>'
            for c in ("#ff5f56", "#ffbd2e", "#27c93f")
        )
        bar_label = ""
        if self.show_lang_label:
            bar_label = (f'<span style="font-size:12px;color:{ct["bar_fg"]};letter-spacing:1px;'
                         f'vertical-align:1px">{label}</span>')
        bar = (f'<section style="margin:0;padding:9px 14px;background-color:{ct["bar_bg"]};'
               f'border-radius:6px 6px 0 0;line-height:1;font-size:0">{dots}{bar_label}</section>')
        return (f'<section style="margin:24px 0;border-radius:6px;overflow:hidden;'
                f'background-color:{ct["bg"]}">{bar}{body}</section>')

    # ------------------------------------------------------------- 行内后处理
    def _inline(self, html_str):
        s = html_str or ""
        t = self.theme

        # 1. 行内代码 <code-span> -> <span>
        # 同样避开 <code> 标签：样式本来就全靠内联 style，换成 span 视觉一致、结构更干净
        # 颜色用主题深色而非固定的 #c7254e —— 否则整篇只有代码这一处「跳出主题」
        code_style = (f"background-color:{t['accent_soft']};color:{t['accent_deep']};"
                      f"padding:2px 5px;"
                      f"margin:0 2px;border-radius:3px;font-size:{self._fs(-2)}px;"
                      f"font-family:{MONO_FONT};line-height:1.5;word-break:break-all")

        def repl_code(m):
            extra = m.group(1) or ""
            body_inner = m.group(2)
            style = extra if (extra and ("background" in extra or "color:" in extra)) else code_style
            return f'<span style="{style}">{body_inner}</span>'
        s = RE_CODE_SPAN.sub(repl_code, s)
        s = RE_TAG_STRIP.sub("", s)

        # 2. 图片 -> 内联安全样式
        def repl_img(m):
            attrs = _attr_val(m.group(1), "src") or ""
            alt = _attr_val(m.group(1), "alt") or ""
            self.stats["images"] += 1
            return (f'<img src="{attrs}" alt="{alt}" style="max-width:100%;display:inline-block;'
                    f'border-radius:4px;vertical-align:middle">')
        s = RE_IMG.sub(repl_img, s)

        # 3. 链接 -> 微信友好
        if self.link_mode == "strip":
            s = RE_A.sub(lambda m: m.group(2), s)
        elif self.link_mode == "text":
            def repl_a_text(m):
                url, label = m.group(1), m.group(2)
                return (f'{label}<span style="color:{t["muted"]};font-size:13px">'
                        f'（{self._esc(url)}）</span>')
            s = RE_A.sub(repl_a_text, s)
        else:
            def repl_a(m):
                url, label = m.group(1), m.group(2)
                return (f'<a href="{url}" style="color:{t["link"]};text-decoration:none;'
                        f'border-bottom:1px solid {t["link"]}80;font-weight:500">{label}</a>')
            s = RE_A.sub(repl_a, s)

        return s

    def _raw_html(self, raw):
        """裸 HTML：剥离微信不友好的属性后原样输出（尽量保守）。"""
        s = re.sub(r"\s+class\s*=\s*\"[^\"]*\"", "", raw)
        s = re.sub(r"\s+id\s*=\s*\"[^\"]*\"", "", s)
        s = re.sub(r"<(script|iframe|style|link)\b[^>]*>.*?</\1>", "", s, flags=re.S | re.I)
        return s


def available_themes():
    return {k: v["label"] for k, v in ARTICLE_THEMES.items()}
