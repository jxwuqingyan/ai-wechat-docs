#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Word(.docx) 读取器（纯标准库 zipfile + ElementTree，无需 python-docx）。

输出与 mdparser 相同的 AST 结构，从而复用同一套渲染器。

Word 中的代码块识别（Word 没有代码块概念，只能靠约定/格式推断）：
  1. run 字体为等宽字体（Consolas / Monaco / Menlo / Courier New / Source Code Pro 等）
  2. 或段落样式名含 code / codeblock / 代码
  3. 或段落有灰色底纹(shd fill) 且字体等宽
连续的这类段落会合并成一个代码块；空的 code 段落保留为空行。
代码语言可从紧邻其上一段的纯文本推断（形如 ```python 或 python）。
"""

import base64
import mimetypes
import os
import re
import zipfile
import xml.etree.ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

RE_MONO = re.compile(
    r"consolas|monaco|menlo|courier|source\s*code|jetbrains|fira\s*code|cascadia"
    r"|droid\s*sans\s*mono|sfmono|ubuntu\s*mono|robotomono|simhei|等宽|代码",
    re.I,
)
RE_CODE_STYLE = re.compile(r"^(?:code|codeblock|code\s*block|html\s*pre|宏|puretext).*|.*代码.*$", re.I)
RE_HEADING_STYLE = re.compile(r"^(?:heading|标题|title|subtitle)\s*(\d)?$", re.I)

HIGHLIGHT_COLORS = {
    "yellow": "#fff9c4", "green": "#c8e6c9", "cyan": "#b2ebf2",
    "magenta": "#f8bbd0", "blue": "#bbdefb", "red": "#ffcdd2",
    "darkBlue": "#90caf9", "darkCyan": "#80deea", "darkGreen": "#a5d6a7",
    "darkMagenta": "#ce93d8", "darkRed": "#ef9a9a", "darkYellow": "#ffe082",
    "darkGray": "#cfcfcf", "lightGray": "#e8e8e8", "black": "#333333",
    "white": "#ffffff",
}

# 代码块语言标记段：形如 ```python / python / code:python
RE_LANG_MARKER = re.compile(
    r"^[`~]{0,3}\s*(?:code[:：]\s*)?(python|py|javascript|js|jsx|typescript|ts|tsx|java|go|golang"
    r"|rust|rs|c\b|cpp|c\+\+|c#|csharp|php|ruby|rb|sql|swift|kotlin|bash|sh|shell|zsh|yaml|yml"
    r"|json|html|xml|css|scss|nginx|dockerfile|docker|diff|text)\s*[`~]{0,3}$",
    re.I,
)


class DocxDoc:
    def __init__(self):
        self.images = {}      # rel_id -> (internal_path, bytes, mime)
        self.hyperlinks = {}  # rel_id -> url
        self.numbering = {}   # numId -> {"ordered":bool}


# ------------------------------------------------------------------ 工具

def _attr(el, name, ns=W):
    return el.get(ns + name) if el is not None else None


def _load_part(zf, path, required=False):
    """读取并解析一个 XML 部件。

    注意：解析失败与「部件不存在」是两回事，必须分开报错——
    早先这里把两者都吞成 None，调用方于是统一报「缺少 word/document.xml」，
    文件明明在里面（只是 XML 有问题）时用户会完全找不到方向。
    """
    try:
        data = zf.read(path)
    except KeyError:
        if required:
            raise ValueError("不是有效的 .docx 文件（压缩包里没有 %s）" % path)
        return None
    try:
        return ET.fromstring(data)
    except ET.ParseError as e:
        if required:
            raise ValueError(
                "无法解析 %s（XML 格式错误，文件可能已损坏或不是标准的 .docx）：%s" % (path, e))
        return None


def _read_rels(zf, part_path):
    """返回 {rId: target} 与 external 标记的简化表。"""
    base = os.path.dirname(part_path)
    rel_path = "%s/_rels/%s.rels" % (base, os.path.basename(part_path)) if base else "_rels/%s.rels" % os.path.basename(part_path)
    root = _load_part(zf, rel_path)
    out = {}
    if root is None:
        return out
    for rel in root.findall(PKG_REL + "Relationship"):
        rid = rel.get("Id")
        target = rel.get("Target")
        mode = rel.get("TargetMode")
        if mode == "External":
            out[rid] = (target, True)
        else:
            if target.startswith("/"):
                target = target.lstrip("/")
            else:
                target = os.path.normpath(os.path.join(base, target)).replace("\\", "/")
            out[rid] = (target, False)
    return out


# ------------------------------------------------------------------ 行内

def _drawing_html(node, doc):
    """在任意节点子树里找图片，转成 <img src="data:...;base64,...">。

    支持两种写法：
      · DrawingML：<w:drawing> / <a:blip r:embed>
      · VML（老文档、部分截图工具）：<v:imagedata r:id>
    必须能在 run **内部**找到 —— Word 一定把 <w:drawing> 放在 <w:r> 里，
    只在段落层级找会永远找不到（这正是「Word 内嵌图片全部丢失」的原因）。
    """
    out = []
    for blip in node.iter(A + "blip"):
        rid = blip.get(R + "embed") or blip.get(R + "link")
        if rid and rid in doc.images:
            _path, data, mime = doc.images[rid]
            b64 = base64.b64encode(data).decode("ascii")
            out.append('<img src="data:%s;base64,%s" alt="">' % (mime, b64))
    for im in node.iter("{urn:schemas-microsoft-com:vml}imagedata"):
        rid = im.get(R + "id")
        if rid and rid in doc.images:
            _path, data, mime = doc.images[rid]
            b64 = base64.b64encode(data).decode("ascii")
            out.append('<img src="data:%s;base64,%s" alt="">' % (mime, b64))
    return "".join(out)


def _run_inline(el, doc):
    """把一段 run / hyperlink 节点列表转成行内 HTML（不含 class）。"""
    out = []
    for node in el:
        tag = node.tag
        if tag == W + "r":
            text = ""
            for child in node:
                if child.tag == W + "t":
                    text += child.text or ""
                elif child.tag == W + "tab":
                    text += "    "
                elif child.tag == W + "br":
                    text += "\n"
                elif child.tag == W + "sym":
                    text += child.get(W + "char") or ""
            # 图片：run 内部的 <w:drawing>/<w:pict> 也要取，否则内嵌图会整段丢掉
            run_imgs = _drawing_html(node, doc)
            if not text and not run_imgs:
                continue
            escaped = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            escaped = escaped.replace("\n", "<br>")

            rpr = node.find(W + "rPr")
            styles = {}
            is_code = False
            wrap_open = []
            wrap_close = []
            if rpr is not None:
                fonts = rpr.find(W + "rFonts")
                fname = " ".join(filter(None, [
                    fonts.get(W + "ascii") if fonts is not None else None,
                    fonts.get(W + "hAnsi") if fonts is not None else None,
                    fonts.get(W + "cs") if fonts is not None else None,
                ]))
                is_code = bool(RE_MONO.search(fname or ""))
                if rpr.find(W + "b") is not None and rpr.find(W + "b").get(W + "val", "true") not in ("false", "0"):
                    wrap_open.append("<strong>")
                    wrap_close.insert(0, "</strong>")
                if rpr.find(W + "i") is not None:
                    wrap_open.append("<em>")
                    wrap_close.insert(0, "</em>")
                u = rpr.find(W + "u")
                if u is not None and u.get(W + "val", "single") not in ("none", "false"):
                    wrap_open.append("<u>")
                    wrap_close.insert(0, "</u>")
                if rpr.find(W + "strike") is not None or rpr.find(W + "dstrike") is not None:
                    wrap_open.append("<del>")
                    wrap_close.insert(0, "</del>")
                col = rpr.find(W + "color")
                if col is not None:
                    val = col.get(W + "val", "")
                    if val and val not in ("auto", "000000", "auto "):
                        styles["color"] = "#" + val[-6:].lower()
                hl = rpr.find(W + "highlight")
                if hl is not None:
                    hv = hl.get(W + "val", "")
                    if hv in HIGHLIGHT_COLORS:
                        styles["background-color"] = HIGHLIGHT_COLORS[hv]
                shd = rpr.find(W + "shd")
                if shd is not None and shd.get(W + "fill") not in (None, "", "auto"):
                    styles["background-color"] = "#" + shd.get(W + "fill")[-6:]
                sz = rpr.find(W + "sz")
                if sz is not None:
                    try:
                        half = int(sz.get(W + "val"))
                        if 12 <= half <= 80:
                            styles["font-size"] = "%dpx" % (half // 2)
                    except (TypeError, ValueError):
                        pass

            style_attr = ";".join("%s:%s" % (k, v) for k, v in styles.items())
            body = escaped
            if is_code:
                if style_attr:
                    style_attr += ";background-color:#f5f6f8;color:#c7254e"
                else:
                    style_attr = "background-color:#f5f6f8;color:#c7254e"
                out.append('<code-span style="%s">%s</code-span>' % (style_attr, body))
                continue
            if style_attr:
                out.append('<span style="%s">%s</span>' % (style_attr, body))
            else:
                out.append(body)
            if run_imgs:
                out.append(run_imgs)
        elif tag == W + "hyperlink":
            rid = node.get(R + "id")
            url = doc.hyperlinks.get(rid, "")
            inner = _run_inline(list(node), doc)
            if url:
                out.append('<a href="%s">%s</a>' % (url.replace('"', "%22"), inner))
            else:
                out.append(inner)
        elif tag == W + "bookmarkStart":
            continue
        elif tag == W + "drawing" or tag == W + "object" or tag == W + "pict":
            # 少数情况图片会直接挂在段落层级（非标准，但历史文档里出现过）
            out.append(_drawing_html(node, doc))
    return "".join(out)


# ------------------------------------------------------------------ 段落

def _para_info(p):
    ppr = p.find(W + "pPr")
    info = {"style": None, "list_id": None, "level": 0, "align": None, "shd": None}
    if ppr is None:
        return info
    ps = ppr.find(W + "pStyle")
    if ps is not None:
        info["style"] = ps.get(W + "val")
    numpr = ppr.find(W + "numPr")
    if numpr is not None:
        ilvl = numpr.find(W + "ilvl")
        numid = numpr.find(W + "numId")
        info["list_id"] = numid.get(W + "val") if numid is not None else "0"
        info["level"] = int(ilvl.get(W + "val", "0")) if ilvl is not None else 0
    jc = ppr.find(W + "jc")
    if jc is not None:
        info["align"] = jc.get(W + "val")
    shd = ppr.find(W + "shd")
    if shd is not None and shd.get(W + "fill") not in (None, "", "auto"):
        info["shd"] = shd.get(W + "fill")
    return info


def _is_mono_paragraph(p):
    """段落是否整体为等宽字体（用于判定代码块）。"""
    runs = list(p.findall(W + "r")) + [hl for hl in p.findall(W + "hyperlink")]
    if not runs:
        return False
    total = 0
    mono = 0
    for node in runs:
        targets = [node] if node.tag == W + "r" else list(node.findall(W + "r"))
        for r in targets:
            text = "".join(t.text or "" for t in r.findall(W + "t"))
            total += len(text)
            rpr = r.find(W + "rPr")
            if rpr is not None:
                fonts = rpr.find(W + "rFonts")
                fname = " ".join(filter(None, [
                    fonts.get(W + "ascii") if fonts is not None else None,
                    fonts.get(W + "hAnsi") if fonts is not None else None,
                ]))
                if RE_MONO.search(fname or ""):
                    mono += len(text)
    return total > 0 and mono / float(total) >= 0.8


def _para_text(p):
    return "".join(t.text or "" for t in p.iter(W + "t")).strip()


def _code_paragraph(p):
    """返回 True 表示该段落应当作为代码块的一行。"""
    info = _para_info(p)
    style = (info["style"] or "")
    if RE_CODE_STYLE.search(style):
        return True
    if _is_mono_paragraph(p):
        return True
    return False


def _load_numbering(zf, doc):
    root = _load_part(zf, "word/numbering.xml")
    if root is None:
        return
    # abstractNumId -> bullet flag
    abstracts = {}
    for ab in root.findall(W + "abstractNum"):
        aid = ab.get(W + "abstractNumId")
        bullet = True
        for lvl in ab.findall(W + "lvl"):
            fmt = lvl.find(W + "numFmt")
            if fmt is not None and fmt.get(W + "val", "bullet") != "bullet":
                bullet = False
                break
        abstracts[aid] = bullet
    for num in root.findall(W + "num"):
        nid = num.get(W + "numId")
        aid_el = num.find(W + "abstractNumId")
        if aid_el is not None:
            doc.numbering[nid] = {"ordered": not abstracts.get(aid_el.get(W + "val"), True)}


# ------------------------------------------------------------------ 主流程

def read_docx(path: str, image_dir=None):
    """读取 docx -> (AST blocks, images_meta)。images_meta: [{name,path,mime}]"""
    doc = DocxDoc()
    images_meta = []
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ValueError(
            "这不是有效的 .docx 文件（不是 zip 容器）。"
            "常见两种情况：上传了旧版 .doc/.rtf，或者文件被加密/损坏——请在 Word 里另存为 .docx")
    with zf:
        rels = _read_rels(zf, "word/document.xml")
        for rid, (target, external) in rels.items():
            if external:
                doc.hyperlinks[rid] = target
            elif target.startswith("word/media/") or target.startswith("media/"):
                try:
                    data = zf.read(target)
                except KeyError:
                    continue
                mime = mimetypes.guess_type(target)[0] or "image/png"
                doc.images[rid] = (target, data, mime)
                if image_dir:
                    os.makedirs(image_dir, exist_ok=True)
                    name = os.path.basename(target)
                    fp = os.path.join(image_dir, name)
                    with open(fp, "wb") as f:
                        f.write(data)
                    images_meta.append({"name": name, "path": fp, "mime": mime})
        _load_numbering(zf, doc)
        root = _load_part(zf, "word/document.xml", required=True)
        body = root.find(W + "body")
        if body is None:
            raise ValueError("不是有效的 .docx 文件（word/document.xml 里没有 body）")
        raw_items = _collect_items(body, doc)

    blocks = _assemble(raw_items, doc)
    return blocks, images_meta


def _collect_items(body, doc):
    """把 body 转成平坦的节点列表（保留列表元信息与代码块候选）。"""
    items = []
    for node in body:
        if node.tag == W + "p":
            info = _para_info(node)
            if any(True for _ in node.iter(W + "drawing")) or any(True for _ in node.iter(W + "pict")):
                inline = _run_inline(list(node), doc)
                text = _para_text(node)
                if inline.strip():
                    items.append({"kind": "p", "inline": inline, "meta": info, "text": text})
                continue
            if _code_paragraph(node):
                items.append({"kind": "code", "text": _code_text(node), "meta": info})
                continue
            inline = _run_inline(list(node), doc)
            text = _para_text(node)
            items.append({"kind": "p", "inline": inline, "meta": info, "text": text})
        elif node.tag == W + "tbl":
            items.append({"kind": "table", "node": node, "doc": doc})
        elif node.tag == W + "sectPr":
            continue
    return items


def _code_text(p):
    """提取代码段落原文（保留前导缩进）。

    注意 <w:br/>（Word 里的**软换行**，Shift+Enter）必须还原成 \\n：
    很多人在 Word 里写代码是「整段 + 软换行」，早先这里只取 <w:t>，
    于是整段代码会被压成一行 —— 粘到公众号里就是一坨。
    """
    parts = []
    for node in p:
        if node.tag == W + "r":
            for child in node:
                if child.tag == W + "t":
                    parts.append(child.text or "")
                elif child.tag == W + "tab":
                    parts.append("    ")
                elif child.tag == W + "br":
                    parts.append("\n")
        elif node.tag == W + "hyperlink":
            for child in node.iter():
                if child.tag == W + "t":
                    parts.append(child.text or "")
                elif child.tag == W + "br":
                    parts.append("\n")
    line = "".join(parts)
    # 保留前导空格（Word 常用空格模拟缩进），去掉每行行尾空白
    return "\n".join(l.rstrip() for l in line.split("\n"))


def _normalize_code_lines(lines):
    """统一缩进：把公共的最小前导空格去掉。"""
    if not lines:
        return []
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return [""] * len(lines)
    cut = min((len(l) - len(l.lstrip(" "))) for l in non_empty)
    out = []
    for l in lines:
        if l.strip():
            out.append(l[cut:] if len(l) >= cut else l.lstrip())
        else:
            out.append("")
    while out and out[-1].strip() == "":
        out.pop()
    return out


def _assemble(items, doc):
    """平坦列表 -> AST（合并代码块、组装列表）。"""
    blocks = []
    i = 0
    pending_img_only = None
    while i < len(items):
        it = items[i]
        if it["kind"] == "code":
            # 向前检查语言标记
            lang = ""
            if blocks and blocks[-1].get("type") == "paragraph":
                prev_text = blocks[-1].get("_plain", "")
                m = RE_LANG_MARKER.match(prev_text.strip())
                if m:
                    lang = m.group(1).lower()
                    blocks.pop()
            # 一个段落里可能有软换行（<w:br/>），按行拆开再合并，
            # 否则整段会被当成"一行"参与缩进归一化
            lines = []
            j = i
            while j < len(items) and items[j]["kind"] == "code":
                lines.extend(items[j]["text"].split("\n"))
                j += 1
            code = "\n".join(_normalize_code_lines(lines))
            blocks.append({"type": "code", "lang": lang or "text", "code": code})
            i = j
            continue
        if it["kind"] == "table":
            blocks.append(_parse_table(it["node"], it["doc"]))
            i += 1
            continue

        # 普通段落
        meta = it["meta"]
        inline = it["inline"]
        text = it["text"]
        style = (meta["style"] or "")

        hm = RE_HEADING_STYLE.match(style)
        level = None
        if hm:
            level = int(hm.group(1) or (1 if style.lower().startswith(("heading", "标题")) else 0))
            if style.lower().startswith(("title", "副标题")):
                level = 1
        elif meta["style"] in (None, "", "BodyText", "Normal", "a", "a0", "ListParagraph"):
            level = None

        node = {
            "type": "paragraph",
            "inline": inline,
            "_plain": text,
            "_list": {"id": meta["list_id"], "level": meta["level"]} if meta["list_id"] else None,
            "_align": meta["align"],
        }
        if level:
            node["type"] = "heading"
            node["level"] = max(1, min(level, 4))
            node["inline"] = inline
        elif style and RE_QUOTE_STYLE.search(style):
            node["type"] = "quote"
            node["children"] = [{"type": "paragraph", "inline": inline}]
        blocks.append(node)
        i += 1

    blocks = _assemble_lists(blocks, doc)
    for b in blocks:
        b.pop("_plain", None)
    return blocks


RE_QUOTE_STYLE = re.compile(r"quote|引用|blockquote", re.I)


def _assemble_lists(blocks, doc):
    """把带有 _list 元信息的连续段落组装成嵌套 list 节点。

    顺带标出「这是不是一个新列表」：Word 里同一个 numId 表示**同一串编号**，
    所以两个被正文/代码块隔开的列表组，numId 相同就该接着往下数（渲染器据此续号），
    numId 不同才是作者真的新起了一串，要从 1 重新开始。
    """
    out = []
    i = 0
    n = len(blocks)
    prev_id = None
    while i < n:
        if blocks[i].get("_list"):
            # 收集连续的 list 项。中途遇到「同层的有序/无序变了」或「回到更外层」就断开：
            # 否则紧跟编号列表的项目符号列表会被并进来，圆点全变成数字。
            group = []
            j = i
            base = None      # (level, ordered) 这一组的基准
            while j < n and blocks[j].get("_list"):
                item = blocks[j]
                lvl = item["_list"]["level"]
                ord_ = doc.numbering.get(item["_list"]["id"], {}).get("ordered", False)
                if base is None:
                    base = (lvl, ord_)
                elif lvl < base[0] or (lvl == base[0] and ord_ != base[1]):
                    break
                group.append(item)
                j += 1
            cur_id = group[0]["_list"].get("id")
            restart = prev_id is not None and cur_id != prev_id
            out.extend(_build_list_tree(group, doc, restart=restart))
            prev_id = cur_id
            i = j
            continue
        if blocks[i].get("type") in ("heading", "hr"):
            prev_id = None      # 新的一节：编号本来就要重新开始
        out.append(blocks[i])
        i += 1
    return out


def _build_list_tree(group, doc, restart=False):
    """按 level 递归构建 list AST。"""
    if not group:
        return []
    base_level = min(x["_list"]["level"] for x in group)

    def render_level(idx, level):
        """处理从第 idx 个开始、level 层的列表项。"""
        items = []
        while idx < len(group):
            item = group[idx]
            lvl = item["_list"]["level"]
            if lvl < level:
                break
            if lvl > level:
                # 子列表：先递归构建子树，再作为一个嵌套 list 节点挂到上一个 item 上
                children, idx = render_level(idx, lvl)
                sub = {
                    "type": "list",
                    "ordered": doc.numbering.get(item["_list"]["id"], {}).get("ordered", False),
                    "items": children,
                }
                if items:
                    items[-1].append(sub)
                else:
                    items.append([sub])
                continue
            content = {"type": "paragraph", "inline": item["inline"]}
            if item.get("type") == "code":
                content = item
            items.append([content])
            idx += 1
        return items, idx

    trees, pos = render_level(0, base_level)
    # coverage of stray trailing items that have smaller level
    while pos < len(group):
        trees.append([{"type": "paragraph", "inline": group[pos]["inline"]}])
        pos += 1
    if not trees:
        return []
    first = group[0]
    ordered = doc.numbering.get(first["_list"]["id"], {}).get("ordered", False)
    node = {"type": "list", "ordered": ordered, "items": trees}
    if ordered and restart:
        node["restart"] = True
    return [node]


def _parse_table(tbl, doc):
    rows = []
    for tr in tbl.findall(W + "tr"):
        cells = []
        for tc in tr.findall(W + "tc"):
            paras = []
            for p in tc.findall(W + "p"):
                inline = _run_inline(list(p), doc)
                if inline.strip():
                    paras.append(inline)
            cells.append("<br>".join(paras))
        rows.append(cells)
    if not rows:
        return {"type": "table", "header": [], "align": [], "rows": []}
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    header = rows[0]
    body = rows[1:] if len(rows) > 1 else []
    return {"type": "table", "header": header, "align": [""] * ncols, "rows": body}


if __name__ == "__main__":
    import json
    import sys
    blocks, imgs = read_docx(sys.argv[1])
    print(json.dumps(blocks, ensure_ascii=False, indent=2)[:4000])
