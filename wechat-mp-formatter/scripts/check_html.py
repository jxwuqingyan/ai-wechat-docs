#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""粘贴前合规自检：检查生成的 HTML 是否会踩微信编辑器的坑。

用法：
    python3 check_html.py 文章.fragment.html
    python3 check_html.py 预览页.html --node mp-content   # 只检查页面中某个节点的内容

检查项：
  1. 违规标签  <style>/<script>/<link>/<iframe> 等（微信一定剥离，等于白写）
  2. class / id 属性（微信会清理，样式会全部丢失）
  3. 未被继承的风险 CSS：position:fixed/absolute、transform、animation、float 等
  4. 可见元素缺少 style 属性（会退化成微信默认样式）
  5. 图片来源（本地路径 / base64 / 相对路径都要在粘贴前处理）
  6. 标签是否闭合、是否有 HTML 实体残留（如 &amp;lt;）
"""

import argparse
import json
import os
import re
import sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DENY_TAGS = {
    "script", "style", "link", "meta", "iframe", "frameme", "embed", "object",
    "form", "input", "textarea", "select", "button", "video", "audio", "source",
    "canvas", "svg", "nav", "map", "base", " noscript",
}

VOID_TAGS = {"br", "hr", "img", "meta", "link", "input", "source", "col", "area", "wbr"}

RISKY_PROPS = {
    "position": ("fixed", "absolute", "sticky"),
    "transform": None,
    "animation": None,
    "transition": None,
    "float": None,
    "filter": None,
    "clip-path": None,
    "grid-template-columns": None,
    "display": ("flex", "grid"),
}

VISIBLE_TAGS = {"section", "p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
                "ul", "ol", "li", "pre", "code", "span", "strong", "em", "del", "u",
                "table", "thead", "tbody", "tr", "th", "td", "img", "figure", "figcaption"}

# 没有内联 style 就会被打回微信默认样式的标签（strong/em/u/del/tr/thead/tbody 有浏览器默认样式，不告警）
STRICT_STYLE_TAGS = {"section", "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "pre",
                     "table", "th", "td", "span", "blockquote", "img", "code"}

ALLOWED_STYLE_PREFIX = re.compile(
    r"^\s*(?:[-\w]+\s*:\s*[^;]*;?\s*)+$", re.S)

RE_CLASS_ID = re.compile(r'\s(?:class|id)\s*=', re.I)
RE_DOUBLE_ENTITY = re.compile(r"&amp;(lt|gt|amp|quot|nbsp|#\d+);")


def _split_style(style: str):
    out = []
    for decl in style.split(";"):
        if ":" not in decl:
            continue
        prop, val = decl.split(":", 1)
        out.append((prop.strip().lower(), val.strip().lower()))
    return out


class _Checker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = []
        self.code_stack = []   # 与 stack 同步：该层是否处于「代码块容器」内
        self.plain = []        # 代码块之外的文本，用于重复转义检查
        self.issues = []
        self.no_style = []
        self.images = []
        self.open_count = 0
        self.pre_count = 0
        self.block_span_warned = False   # 同一问题只报一次，避免刷屏
        self.list_tags_warned = set()    # 每种列表标签也只报一次

    def _in_code(self):
        return any(self.code_stack)

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag in DENY_TAGS:
            self.issues.append(("error", "违规标签 <%s>：微信会直接剥离" % tag))
        if "class" in d or "id" in d:
            self.issues.append(("error", "<%s> 带 class/id 属性：微信会清理，样式全部丢失" % tag))
        style = d.get("style", "")
        if tag == "pre":
            self.pre_count += 1
        if tag in VISIBLE_TAGS:
            self.open_count += 1
            if not style and tag in STRICT_STYLE_TAGS:
                self.no_style.append(tag)
        if style:
            for prop, val in _split_style(style):
                if prop in RISKY_PROPS:
                    bad = RISKY_PROPS[prop]
                    if bad is None or val.startswith(bad):
                        tip = "微信通常不支持 %s:%s，建议去掉" % (prop, val)
                        self.issues.append(("warn", "<%s> %s" % (tag, tip)))
                if prop == "white-space" and val == "pre":
                    self.issues.append((
                        "warn",
                        "<%s> 用了 white-space:pre：内容不会自动换行，移动端可能水平溢出"
                        "（公众号后台的结构检测也会这样提示）" % tag))
            if not ALLOWED_STYLE_PREFIX.match(style + ";"):
                self.issues.append(("warn", "<%s> 的 style 写法异常，可能被整体丢弃" % tag))
        # 代码块的分行方式：靠 <span style="display:block"> 分行是不安全的——
        # 微信保存/预览时会重排正文并洗掉 span 上的 display，届时行内 span 之间
        # 连换行符都没有，所有代码行会**无缝挤成一行**（如 "EOFvm.swappiness = 1"）。
        # 分行必须交给 <section> / <br> 这类结构本身就能断行的标签。
        if (tag == "span" and "display:block" in style.replace(" ", "")
                and self.code_stack and self.code_stack[-1]
                and not self.block_span_warned):
            self.block_span_warned = True
            self.issues.append((
                "error",
                '代码块用 <span style="display:block"> 分行：微信会丢掉 span 上的 display，'
                '所有代码行会挤成一行。请改用每行一个 <section>'))
        # 列表的编号方式：序号交给 <ol>/<li> + list-style 是不安全的——
        # 微信重排时会洗掉 list-style，整篇有序项会全变成 "1."（或编号整体消失）。
        # 尤其是列表中间夹了段落/代码块时，列表被拆成多个 <ol>，每个都从 1 重新开始，
        # 就是用户看到的「同一级标题下面的有序项全是 1」。
        # 序号必须写成文本（渲染器已按 ordinal_marker 输出），序号不依赖 CSS。
        if tag in ("ol", "ul", "li"):
            if tag not in self.list_tags_warned:
                self.list_tags_warned.add(tag)
                self.issues.append((
                    "error",
                    "<%s> 标签：序号/圆点依赖 CSS 的 list-style，微信清洗后会全变 1 或不显示。"
                    "请重新生成（新版已把序号写成文本，不再使用 ol/ul/li）" % tag))
        if tag == "img":
            src = d.get("src", "")
            if src.startswith("data:"):
                self.images.append(("base64", src[:40]))
            elif src.startswith(("http://", "https://", "//")):
                self.images.append(("remote", src))
            else:
                self.images.append(("local", src))
            if not d.get("style"):
                self.issues.append(("warn", "<img> 缺少 style，宽度可能失控"))
        if tag not in VOID_TAGS:
            self.stack.append(tag)
            # 等宽字体容器即代码块；其内部内容不参与"重复转义"检查
            # （代码里本来就写着 &lt; 之类，转义成 &amp;lt; 是正确的）
            self.code_stack.append("monospace" in style.lower() or "Menlo" in style)

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
            if self.code_stack:
                self.code_stack.pop()
        elif tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                if self.code_stack:
                    self.code_stack.pop()
            if self.code_stack:
                self.code_stack.pop()
            self.issues.append(("warn", "</%s> 与开标签不匹配，存在嵌套错误" % tag))
        else:
            self.issues.append(("warn", "多余的 </%s>" % tag))

    def handle_data(self, data):
        if not self._in_code():
            self.plain.append(data)

    def handle_entityref(self, name):
        if not self._in_code():
            self.plain.append("&%s;" % name)

    def handle_charref(self, name):
        if not self._in_code():
            self.plain.append("&#%s;" % name)


RE_SHELL = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)


def _strip_shell(html: str) -> str:
    """去掉页面外壳自带的 <script>/<style>（它们不会被粘贴到微信）。"""
    return RE_SHELL.sub("", html)


def extract_node(html: str, node_id: str) -> str:
    """按配对计数提取某个节点的内容（比正则更可靠）。"""
    m = re.search(r'<(\w+)[^>]*\bid=["\']%s["\'][^>]*>' % re.escape(node_id), html)
    if m:
        tag = m.group(1)
        rest = html[m.end():]
        depth = 1
        for tok in re.finditer(r"</?%s\b[^>]*>" % tag, rest):
            depth += -1 if tok.group(0).startswith("</") else 1
            if depth == 0:
                return _strip_shell(rest[:tok.start()])
    # 退回到 <body> 内部
    m = re.search(r"<body[^>]*>", html)
    if m:
        body = html[m.end():]
        end = body.rfind("</body>")
        if end > 0:
            body = body[:end]
        return _strip_shell(body)
    return _strip_shell(html)


def check(html: str) -> dict:
    c = _Checker()
    c.feed(html)
    c.close()

    errors = [m for lvl, m in c.issues if lvl == "error"]
    warns = [m for lvl, m in c.issues if lvl == "warn"]

    if c.stack:
        warns.append("存在未闭合标签：%s" % ", ".join(c.stack[:5]))

    local_imgs = [s for k, s in c.images if k == "local"]
    base64_imgs = [s for k, s in c.images if k == "base64"]
    remote_imgs = [s for k, s in c.images if k == "remote"]
    if local_imgs:
        shown = "、".join(local_imgs[:3]) + ("…" if len(local_imgs) > 3 else "")
        errors.append("%d 张图片使用本地路径，粘贴后会裂图（%s）。"
                      "请先在公众号后台上传图片，再替换 src 为 mmbiz.qpic.cn 链接。"
                      % (len(local_imgs), shown))
    if base64_imgs:
        warns.append("%d 张图片为 base64，微信不会接收，需在公众号后台上传后替换" % len(base64_imgs))

    if c.pre_count:
        warns.append(
            "检测到 %d 处 <pre> 标签：公众号后台的「内容结构检测」会提示它不会自动换行、"
            "移动端可能水平溢出。请用 --code-mode block（当前默认）重新生成，"
            "新版输出已改用逐行 block span，不再包含 pre 标签。" % c.pre_count)

    # 重复转义只查代码块之外的文本：代码里本来就写着 &lt;，转义成 &amp;lt; 是正确的
    entities = RE_DOUBLE_ENTITY.findall("".join(c.plain))
    if entities:
        warns.append("发现 %d 处重复转义（如 &amp;lt;），正文会显示成乱码字符" % len(entities))

    dedup_no_style = sorted(set(c.no_style))
    if dedup_no_style:
        warns.append("以下标签没有内联样式，会被微信还原成默认样子：%s"
                     % ", ".join(dedup_no_style))

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warns,
        "images": {"local": local_imgs, "base64": len(base64_imgs), "remote": remote_imgs},
        "styled_elements": c.open_count,
        "pre_tags": c.pre_count,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="微信公众号 HTML 合规自检")
    ap.add_argument("html")
    ap.add_argument("--node", default=None, help="预览页中正文容器的 id（默认 mp-content）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    with open(args.html, "r", encoding="utf-8") as f:
        html = f.read()
    node = args.node
    if node is None and ("id=\"mp-content\"" in html or "id='mp-content'" in html):
        node = "mp-content"
    html = extract_node(html, node) if node else extract_node(html, "\x00")

    result = check(html)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    if result["errors"]:
        print("❌ 必须修复：")
        for e in result["errors"]:
            print("   · " + e)
    else:
        print("✅ 没有会导致粘贴失败的问题")
    if result["warnings"]:
        print("⚠️  建议处理：")
        for w in result["warnings"][:12]:
            print("   · " + w)
    print("\n图片统计：本地 %d / base64 %d / 外链 %d"
          % (len(result["images"]["local"]), result["images"]["base64"],
             len(result["images"]["remote"])))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
