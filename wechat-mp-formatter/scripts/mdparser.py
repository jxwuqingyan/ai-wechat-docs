#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""极简 Markdown 解析器（纯标准库）。

只生成中间 AST（嵌套的 dict 结构），渲染交给 renderer.py。
这样 Markdown 与 Word 两条输入路径可以共用同一套渲染器，排版完全一致。

AST 节点：
  {"type":"heading","level":2,"text":"..."}                 heading 的 text 是行内 HTML
  {"type":"paragraph","inline":"..."}                       inline 已是行内 HTML
  {"type":"code","lang":"python","code":"..."}
  {"type":"quote","children":[blocks]}
  {"type":"list","ordered":False,"start":1,"items":[[blocks]]}
  {"type":"table","header":[inline...],"align":[...],"rows":[[inline...]]}
  {"type":"hr"}
  {"type":"html","raw":"..."}                               裸 HTML 块（会被安全清洗）
"""

import re

# ------------------------------------------------------------------ 行级识别

RE_FENCE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})\s*([\w+#.\-]*)\s*$")
RE_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
RE_HR = re.compile(r"^\s{0,3}([-*_])\s*(?:\1\s*){2,}$")
RE_UL = re.compile(r"^(\s*)([-*+])\s+(.*)$")
RE_OL = re.compile(r"^(\s*)(\d{1,9})[.)]\s+(.*)$")
RE_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
RE_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
RE_IMAGE_ONLY = re.compile(r'^\s*!\[([^\]]*)\]\(<?([^)\s]+)>?(?:\s+"([^"]*)")?\)\s*$')

MONO_HINT = re.compile(r"console|shell|terminal", re.I)


def _indent(line: str) -> int:
    """计算视觉缩进宽度（Tab 计为 4）。"""
    line = line.replace("\t", "    ")
    return len(line) - len(line.lstrip(" "))


def _split_cells(line: str):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells = []
    buf = ""
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            buf += s[i + 1]
            i += 2
            continue
        if s[i] == "|":
            cells.append(buf.strip())
            buf = ""
            i += 1
            continue
        buf += s[i]
        i += 1
    cells.append(buf.strip())
    return cells


def _is_table_sep(line: str) -> bool:
    s = line.strip()
    if "|" in s or s.startswith(":") or s.startswith("-"):
        return bool(RE_TABLE_SEP.match(s)) and "-" in s
    return False


def _parse_align(sep_line: str, ncols: int):
    cells = _split_cells(sep_line)
    aligns = []
    for c in cells[:ncols]:
        c = c.strip()
        if c.startswith(":") and c.endswith(":"):
            aligns.append("center")
        elif c.endswith(":"):
            aligns.append("right")
        elif c.startswith(":"):
            aligns.append("left")
        else:
            aligns.append("")
    while len(aligns) < ncols:
        aligns.append("")
    return aligns


class _Parser:
    def __init__(self, text: str):
        self.lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # ------------------------------------------------------------ 主循环
    def parse(self):
        blocks, _ = self._blocks(0)
        return blocks

    def _blocks(self, i: int, stop_indent: int = 0):
        blocks = []
        n = len(self.lines)
        while i < n:
            raw = self.lines[i]
            stripped = raw.strip()
            if stripped == "":
                i += 1
                continue
            ind = _indent(raw)
            if stop_indent and ind < stop_indent:
                break

            # 围栏代码块
            m = RE_FENCE.match(raw)
            if m:
                fence_ch = m.group(2)[0]
                lang = (m.group(3) or "").strip()
                body = []
                i += 1
                while i < n:
                    line = self.lines[i]
                    fm = RE_FENCE.match(line)
                    if fm and fm.group(2)[0] == fence_ch and not fm.group(3):
                        i += 1
                        break
                    body.append(line)
                    i += 1
                blocks.append({"type": "code", "lang": lang, "code": _dedent(body)})
                continue

            # 标题
            m = RE_HEADING.match(raw)
            if m:
                level = len(m.group(1))
                blocks.append({"type": "heading", "level": level,
                               "inline": inline_html(m.group(2))})
                i += 1
                continue

            # 分隔线
            if RE_HR.match(raw) and not RE_UL.match(raw):
                blocks.append({"type": "hr"})
                i += 1
                continue

            # 引用
            m = RE_QUOTE.match(raw)
            if m:
                buf = []
                while i < n:
                    qm = RE_QUOTE.match(self.lines[i])
                    if qm:
                        buf.append(qm.group(1))
                        i += 1
                    elif self.lines[i].strip() == "":
                        # 空行：若后面还有 > 则视为引用内换行
                        j = i + 1
                        while j < n and self.lines[j].strip() == "":
                            j += 1
                        if j < n and RE_QUOTE.match(self.lines[j]):
                            buf.append("")
                            i = j
                        else:
                            break
                    else:
                        break
                sub = _Parser("\n".join(buf)).parse()
                blocks.append({"type": "quote", "children": sub})
                continue

            # 列表
            m = RE_UL.match(raw) or RE_OL.match(raw)
            if m:
                block, i = self._list(i)
                blocks.append(block)
                continue

            # 表格
            if "|" in raw and i + 1 < n and _is_table_sep(self.lines[i + 1]):
                block, i = self._table(i)
                blocks.append(block)
                continue

            # 独立图片行 -> 单独成段（便于加图注样式）
            m = RE_IMAGE_ONLY.match(raw)
            if m:
                blocks.append({"type": "paragraph",
                               "inline": inline_html(stripped)})
                i += 1
                continue

            # 裸 HTML 块（整段以 < 开头）
            if stripped.startswith("<") and RE_BLOCK_TAG.match(stripped):
                blocks.append({"type": "html", "raw": raw.strip()})
                i += 1
                continue

            # 普通段落
            buf = [stripped]
            i += 1
            while i < n:
                line = self.lines[i]
                s = line.strip()
                if s == "":
                    break
                if RE_HEADING.match(line) or RE_HR.match(line) or RE_QUOTE.match(line) \
                        or RE_UL.match(line) or RE_OL.match(line) or RE_FENCE.match(line):
                    break
                if "|" in line and i + 1 < n and _is_table_sep(self.lines[i + 1]):
                    break
                buf.append(s)
                i += 1
            blocks.append({"type": "paragraph", "inline": inline_html("\n".join(buf))})
        return blocks, i

    # ------------------------------------------------------------ 列表
    def _list(self, i: int):
        n = len(self.lines)
        first = RE_UL.match(self.lines[i]) or RE_OL.match(self.lines[i])
        ordered = bool(RE_OL.match(self.lines[i]))
        # 显式起始序号（写成 "3." 开头）。只有 >1 才写进 AST：写成 "1." 时要留给
        # 渲染器去判断「它是不是上一串编号的续写」。
        start = 1
        if ordered:
            try:
                start = int(RE_OL.match(self.lines[i]).group(2))
            except (AttributeError, ValueError):
                start = 1
        base = len(first.group(1))
        items = []
        while i < n:
            raw = self.lines[i]
            if raw.strip() == "":
                j = i + 1
                while j < n and self.lines[j].strip() == "":
                    j += 1
                if j < n and _indent(self.lines[j]) >= base and (
                        RE_UL.match(self.lines[j]) or RE_OL.match(self.lines[j])
                        or RE_CONTINUATION.match(self.lines[j])):
                    i = j
                    continue
                break
            ind = _indent(raw)
            m = RE_UL.match(raw) or RE_OL.match(raw)
            if m and len(m.group(1)) == base:
                # 标记类型变了（有序 <-> 无序）就是另一串列表。以前这里只比对缩进，
                # 紧跟有序列表的无序列表会被吞成一个有序列表 —— 圆点全变成数字。
                if bool(RE_OL.match(raw)) != ordered:
                    break
                content_col = base + len(m.group(2)) + 1
                # 收集该项的所有行
                item_lines = [self._lstrip_cols(raw, content_col)]
                i += 1
                while i < n:
                    line = self.lines[i]
                    if line.strip() == "":
                        j = i + 1
                        while j < n and self.lines[j].strip() == "":
                            j += 1
                        if j < n and _indent(self.lines[j]) >= content_col \
                                and not (RE_UL.match(self.lines[j]) and len(RE_UL.match(self.lines[j]).group(1)) <= base):
                            item_lines.append("")
                            i = j
                            continue
                        break
                    cind = _indent(line)
                    if cind >= content_col:
                        item_lines.append(self._lstrip_cols(line, content_col))
                        i += 1
                        continue
                    if len(line) - len(line.lstrip()) >= base and RE_UL.match(line):
                        break
                    break
                sub = _Parser("\n".join(item_lines)).parse()
                items.append(sub)
                continue
            if ind < base:
                break
            # 缩进不一致的意外情况：当普通内容处理
            break
        node = {"type": "list", "ordered": ordered, "items": items}
        if ordered and start > 1:
            node["start"] = start
        return node, i

    @staticmethod
    def _lstrip_cols(line: str, cols: int) -> str:
        line = line.replace("\t", "    ")
        return line[cols:] if len(line) >= cols else line.lstrip()

    # ------------------------------------------------------------ 表格
    def _table(self, i: int):
        n = len(self.lines)
        header = _split_cells(self.lines[i])
        align = _parse_align(self.lines[i + 1], len(header))
        i += 2
        rows = []
        while i < n:
            line = self.lines[i]
            if line.strip() == "" or "|" not in line:
                break
            cells = _split_cells(line)
            if len(cells) < len(header):
                cells += [""] * (len(header) - len(cells))
            rows.append([inline_html(c) for c in cells[:len(header)]])
            i += 1
        return {"type": "table",
                "header": [inline_html(c) for c in header],
                "align": align,
                "rows": rows}, i


RE_BLOCK_TAG = re.compile(r"^<(?:p|div|section|blockquote|table|img|figure|iframe|br|hr)\b", re.I)
RE_CONTINUATION = re.compile(r"^\s{2,}\S")


def _dedent(body):
    if not body:
        return ""
    indents = [len(l) - len(l.lstrip(" ")) for l in body if l.strip()]
    cut = min(indents) if indents else 0
    return "\n".join((l[cut:] if len(l) >= cut else l.lstrip()) for l in body).strip("\n")


# ------------------------------------------------------------------ 行内解析

RE_CODE_SPAN = re.compile(r"(`+)(.+?)\1", re.S)
RE_ESC = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>~|])")
RE_STRIKE = re.compile(r"~~(.+?)~~", re.S)
RE_STRONG = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.S)
RE_EM = re.compile(r"(\*|_)(?=\S)(.+?)(?<=\S)\1", re.S)
RE_IMG = re.compile(r'!\[([^\]]*)\]\(<?([^)\s]+)>?(?:\s+"([^"]*)")?\)')
RE_LINK = re.compile(r"\[([^\]]*)\]\(<?([^)\s]*)>?(?:\s+\"([^\"]*)\")?\)")
RE_AUTOLINK = re.compile(r"<((?:https?|mailto):[^>]+)>")
RE_HTML_TAG = re.compile(r"<(/?)([a-zA-Z][\w-]*)([^>]*)>")

SAFE_INLINE_TAGS = {
    "strong", "b", "em", "i", "u", "del", "s", "sub", "sup", "span", "code",
    "br", "kbd", "mark", "small",
}

_ESC_CHARS = "\\`*_{}[]()#+-.!>~|"


def esc(text: str) -> str:
    """转义文本为 HTML 安全串（保留必要实体）。"""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _clean_html_tag(tag_html: str) -> str:
    """清洗裸 HTML 标签：只保留白名单标签，且把 class/id 转成内联 style 丢弃。"""
    def repl(m):
        closing, name, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if name not in SAFE_INLINE_TAGS:
            return ""
        if closing:
            return "</%s>" % name
        style = ""
        sm = re.search(r'style\s*=\s*"([^"]*)"', attrs, re.I)
        if sm:
            style = sm.group(1)
        return "<%s%s>" % (name, ' style="%s"' % style if style else "")
    return RE_HTML_TAG.sub(repl, tag_html)


def inline_html(text: str) -> str:
    """Markdown 行内语法 -> HTML（不含任何 class，样式由渲染器统一处理）。"""
    if text is None:
        return ""
    if "\n" not in text and not any(c in text for c in "`*_~[\\<&"):
        return esc(text)

    placeholders = []
    ph_id = 0

    def stash(html_str: str) -> str:
        nonlocal ph_id
        ph_id += 1
        token = "\x00PH%d\x00" % ph_id
        placeholders.append((token, html_str))
        return token

    def _protect_code(s: str) -> str:
        def repl(m):
            return stash('<code-span>%s</code-span>' % esc(m.group(2).strip()))
        return RE_CODE_SPAN.sub(repl, s)

    def _protect_esc(s: str) -> str:
        return RE_ESC.sub(lambda m: stash(esc(m.group(1))), s)

    def _protect_autolink(s: str) -> str:
        return RE_AUTOLINK.sub(lambda m: stash('<a href="%s">%s</a>' % (m.group(1), esc(m.group(1)))), s)

    def _protect_img(s: str) -> str:
        def repl(m):
            alt, src, title = m.group(1), m.group(2), m.group(3)
            t = ' title="%s"' % esc(title) if title else ""
            return stash('<img src="%s" alt="%s"%s>' % (src.replace('"', "%22"), esc(alt), t))
        return RE_IMG.sub(repl, s)

    def _protect_link(s: str) -> str:
        def repl(m):
            label, href, title = m.group(1), m.group(2), m.group(3)
            if not href:
                return m.group(0)
            t = ' title="%s"' % esc(title) if title else ""
            return stash('<a href="%s"%s>%s</a>' % (
                href.replace('"', "%22"), t, inline_html(label)))
        return RE_LINK.sub(repl, s)

    # 顺序：转义 \x -> 行内代码 -> 转义字符 -> 自动链接 -> 图片 -> 链接
    # 转义字符必须先处理，避免 URL 里的字符被当标记
    work = text
    work = _protect_code(work)
    work = _protect_esc(work)
    work = _protect_autolink(work)
    work = _protect_img(work)
    work = _protect_link(work)
    work = _clean_html_tag(work)

    work = RE_STRIKE.sub(lambda m: '<del>%s</del>' % _restore(m.group(1), placeholders), work)
    work = RE_STRONG.sub(lambda m: '<strong>%s</strong>' % m.group(2), work)
    work = RE_EM.sub(lambda m: '<em>%s</em>' % m.group(2), work)

    # 软换行 -> <br>
    work = work.replace("\n", "<br>")

    # 还原占位符
    for token, html_str in placeholders:
        work = work.replace(token, html_str)

    work = re.sub(r"\x00PH\d+\x00", "", work)
    return work


def _restore(s: str, placeholders) -> str:
    for token, html_str in placeholders:
        s = s.replace(token, html_str)
    return s


def parse_markdown(text: str):
    """对外入口：Markdown 文本 -> AST(list of dict)。"""
    return _Parser(text).parse()


if __name__ == "__main__":
    import json
    import sys
    src = sys.stdin.read()
    print(json.dumps(parse_markdown(src), ensure_ascii=False, indent=2))
