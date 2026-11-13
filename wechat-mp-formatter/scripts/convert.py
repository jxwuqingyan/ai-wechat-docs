#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Markdown / Word(.docx) 转成可直接粘贴进微信公众号编辑器的 HTML。

用法：
    python3 convert.py 文章.md -o ~/Desktop/article.html --theme blue
    python3 convert.py 文章.docx -o out.html --title "标题" --author "作者" --date "2026-10-14"
    python3 convert.py 文章.md --code-theme monokai --line-numbers

零第三方依赖，纯 Python 标准库。详细的上层工作流见 SKILL.md。
"""

import argparse
import base64
import json
import mimetypes
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import docxreader  # noqa: E402
import mdparser  # noqa: E402
import preview as preview_mod  # noqa: E402
from renderer import (ARTICLE_THEMES, DEFAULT_THEME, DEFAULT_FONT_SIZE,  # noqa: E402
                      Renderer)
from highlighter import CODE_THEMES  # noqa: E402

RE_IMG_SRC = re.compile(r'<img\s[^>]*?src="([^"]+)"', re.S)
DATA_URI = re.compile(r"^data:image/(\w+);base64,")

# 这些是"看起来像 Word，但解析器读不了"的格式：必须明确报错，
# 不能兜底当 Markdown 读（二进制内容会变成一篇乱码文章）
BAD_WORD_EXTS = {
    ".doc": "旧版 Word 二进制格式",
    ".rtf": "RTF 格式",
    ".wps": "WPS 文字格式",
    ".odt": "OpenDocument 格式",
    ".pages": "Pages 格式",
}


def read_input(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def embed_local_images(html_str: str, base_dir: str, image_mode: str):
    """处理 Markdown 里的本地图片。

    embed(默认)：转成 data URI，保证浏览器预览可见（微信仍需重新上传素材）。
    keep        ：保持原 src（浏览器预览可能裂图）。
    drop        ：移除 <img>（适用于图片本来就要手插的场景）。
    """
    local, remote = [], []
    cache = {}
    total = [0]

    def repl(m):
        """只替换 src 的取值，保留整个 <img ...> 标签其余部分。"""
        whole, src = m.group(0), m.group(1)
        total[0] += 1
        new = None
        if image_mode == "drop":
            return whole.replace("<img", '<img data-removed="1" style="display:none"', 1)
        if DATA_URI.match(src):
            local.append("内嵌图片")
        elif src.startswith(("http://", "https://", "//")):
            remote.append(src)
        else:
            candidate = src if os.path.isabs(src) else os.path.normpath(os.path.join(base_dir, src))
            if os.path.isfile(candidate):
                local.append(candidate)
                if image_mode == "embed":
                    if candidate not in cache:
                        with open(candidate, "rb") as f:
                            data = f.read()
                        mime = mimetypes.guess_type(candidate)[0] or "image/png"
                        cache[candidate] = "data:%s;base64,%s" % (
                            mime, base64.b64encode(data).decode("ascii"))
                    new = cache[candidate]
            else:
                local.append(src + "（未找到）")
        if new is None or new == src:
            return whole
        return whole.replace('src="%s"' % src, 'src="%s"' % new, 1)

    out = RE_IMG_SRC.sub(repl, html_str)
    return out, local, remote


def main(argv=None):
    ap = argparse.ArgumentParser(description="Markdown/Word -> 微信公众号排版 HTML")
    ap.add_argument("input", help="输入的 .md / .markdown / .txt / .docx(.docm) 文件，或用 - 表示 stdin")
    ap.add_argument("-o", "--output", default=None, help="输出 HTML 文件路径（默认与输入同名 .html）")
    ap.add_argument("--theme", default=DEFAULT_THEME, choices=sorted(ARTICLE_THEMES.keys()),
                    help="文章配色主题（默认 classic）")
    ap.add_argument("--code-theme", default=None, choices=sorted(CODE_THEMES.keys()),
                    help="代码配色主题（默认随文章主题）")
    ap.add_argument("--title", default=None, help="文章大标题（生成片头）")
    ap.add_argument("--author", default=None, help="作者/署名")
    ap.add_argument("--date", default=None, help="日期")
    ap.add_argument("--footer-text", default="如果这篇文章对你有帮助，欢迎点赞、在看和转发 👋",
                    help="片尾引导语")
    ap.add_argument("--no-footer", action="store_true", help="不生成片尾")
    ap.add_argument("--line-numbers", action="store_true", help="代码块显示行号")
    ap.add_argument("--font-size", type=int, default=DEFAULT_FONT_SIZE,
                    help="正文字号 px（默认 %d，移动端最佳阅读字号；其余元素按相对比例推导）"
                         % DEFAULT_FONT_SIZE)
    ap.add_argument("--code-mode", default="block", choices=["block", "scroll", "pre"],
                    help="代码块长行处理：block 折行（默认，移动端不溢出）/ "
                         "scroll 保持单行靠横向滚动（pre 是旧参数名，等价于 scroll）")
    ap.add_argument("--no-code-chrome", action="store_true", help="代码块不显示顶部语言栏")
    ap.add_argument("--no-lang-label", action="store_true", help="语言栏不显示语言名")
    ap.add_argument("--heading-style", default="modern", choices=["modern", "simple"])
    ap.add_argument("--divider", default="dots", choices=["dots", "line", "gradient"])
    ap.add_argument("--link-mode", default="keep", choices=["keep", "text", "strip"],
                    help="超链接处理：keep 保留 a 标签 / text 转为「文本（URL）」/ strip 移除")
    ap.add_argument("--flat-tags", action="store_true",
                    help="标题全部用 <p> 输出（兼容性最高，语义最弱）")
    ap.add_argument("--image-mode", default="embed", choices=["embed", "keep", "drop"],
                    help="本地图片处理：embed 内嵌 base64（默认）/ keep 保持路径 / drop 移除")
    ap.add_argument("--no-fragment", action="store_true", help="不额外生成片段 HTML")
    ap.add_argument("--stdout", action="store_true", help="把可粘贴片段输出到 stdout")
    args = ap.parse_args(argv)

    src = args.input
    if src == "-":
        text = sys.stdin.read()
        base_dir = os.getcwd()
        kind = "md"
        src_label = "stdin.md"
    else:
        if not os.path.isfile(src):
            return _fail("找不到输入文件：%s" % src)
        ext = os.path.splitext(src)[1].lower()
        base_dir = os.path.dirname(os.path.abspath(src))
        src_label = os.path.basename(src)
        if ext in (".docx", ".docm"):
            # .docm 只是带宏的 docx，zip 结构一致，同样能读
            kind = "docx"
            text = None
        elif ext in (".md", ".markdown", ".mdown", ".txt", ".mkd"):
            kind = "md"
            text = read_input(src)
        elif ext in BAD_WORD_EXTS:
            # 早先这里会"兜底当 Markdown 读"，二进制内容被硬当成文本，
            # 结果是一篇乱码文章而不是一句报错——宁可失败也要说清原因
            return _fail("不支持 %s 格式（%s）。请在 Word / WPS 里另存为 .docx 再转换"
                         % (ext, BAD_WORD_EXTS[ext]))
        else:
            # 兜底：按 Markdown 读取，但二进制文件要拦下来
            raw = None
            try:
                with open(src, "rb") as f:
                    raw = f.read(4096)
            except OSError:
                pass
            if raw and b"\x00" in raw:
                return _fail("无法识别 %s 的内容（看起来是二进制文件）。"
                             "支持 .md / .markdown / .txt / .docx / .docm" % src_label)
            kind = "md"
            text = read_input(src)

    out_path = args.output or os.path.join(base_dir, os.path.splitext(src_label)[0] + ".wechat.html")
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)

    images_meta = []
    if kind == "docx":
        img_dir = os.path.join(out_dir, os.path.splitext(os.path.basename(out_path))[0] + "_images")
        try:
            blocks, images_meta = docxreader.read_docx(src, image_dir=img_dir)
        except Exception as e:
            return _fail("读取 Word 文件失败：%s" % e)
    else:
        blocks = mdparser.parse_markdown(text)

    title = args.title
    if title is None and kind == "md":
        for b in blocks:
            if b.get("type") == "heading" and b.get("level") == 1:
                title = re.sub(r"<[^>]+>", "", b.get("inline", "")).strip()
                break

    opts = {
        "line_numbers": args.line_numbers,
        "code_chrome": not args.no_code_chrome,
        "lang_label": not args.no_lang_label,
        "heading_style": args.heading_style,
        "divider": args.divider,
        "link_mode": args.link_mode,
        "flat_tags": args.flat_tags,
        "code_mode": args.code_mode,
        "font_size": args.font_size,
    }
    meta = {
        "title": title,
        "author": args.author,
        "date": args.date,
        "footer": None if args.no_footer else args.footer_text,
    }

    r = Renderer(theme=args.theme, code_theme=args.code_theme, opts=opts)
    body = r.render(blocks, meta=meta)

    local_imgs, remote_imgs = [], []
    body, local_imgs, remote_imgs = embed_local_images(body, base_dir, args.image_mode)
    stats = dict(r.stats)
    stats["local_images"] = local_imgs
    stats["remote_images"] = remote_imgs
    stats["extracted_images"] = [m["path"] for m in images_meta]

    preview_mod.build_preview(body, stats, meta, out_path)
    frag_path = None
    if not args.no_fragment:
        frag_path = os.path.splitext(out_path)[0] + ".fragment.html"
        preview_mod.build_fragment(body, meta, frag_path)

    report = {
        "ok": True,
        "input": os.path.abspath(src) if src != "-" else "-",
        "kind": kind,
        "output_preview": os.path.abspath(out_path),
        "output_fragment": os.path.abspath(frag_path) if frag_path else None,
        "theme": args.theme,
        "code_theme": r.code_theme,
        "stats": stats,
        "warnings": [],
    }
    if kind == "docx":
        detected = stats["code_blocks"]
        report["warnings"].append(
            "Word 中的代码块是靠「等宽字体/『代码』样式」识别的，共识别到 %d 段。"
            "若发现某段代码没被识别成代码块，请提醒用户在 Word 里给它设置 Consolas/Monaco 等宽字体后重跑。"
            % detected)
    if local_imgs:
        report["warnings"].append(
            "含 %d 处本地图片，已 base64 嵌入预览；粘贴到微信前需在公众号后台重新上传图片素材。"
            % len(local_imgs))
    if remote_imgs:
        report["warnings"].append(
            "含 %d 张外链图片：微信可能自动抓取转存，也可能裂图，建议上传素材库。" % len(remote_imgs))
    if images_meta:
        report["warnings"].append(
            "已从 Word 提取 %d 张图片到 %s" % (len(images_meta), img_dir if kind == "docx" else ""))

    report_path = os.path.splitext(out_path)[0] + ".report.json"
    preview_mod.write_report(report, report_path)
    report["report_path"] = os.path.abspath(report_path)

    if args.stdout:
        print(body)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _fail(msg):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False, indent=2))
    return 1


if __name__ == "__main__":
    sys.exit(main())
