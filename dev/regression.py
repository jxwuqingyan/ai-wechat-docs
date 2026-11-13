#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：改完排版逻辑后跑这个。

    python3 dev/regression.py            # 全量（3 输入 × 6 主题 × 3 字号 + 全部断言）
    python3 dev/regression.py --quick    # 快速（1 主题 × 1 字号 + 全部断言）

只依赖 Python 标准库（和项目本身一样零依赖）。

它守住四类会「静默回归」的东西：

  1. 语法      —— 所有 .py 能 parse；有 node 的话顺带 node --check 前端 js
  2. 结构红线  —— 产物里不得出现 ol / ul / li / pre / code、不得出现
                  span 上的 display:block（这三样都会在微信后台被洗坏）
  3. 列表编号  —— 逐个断言 marker 文本序列。编号是最容易悄悄退回「全是 1」的地方，
                  肉眼看截图看不出来，必须按序列断言
  4. 合规自检  —— check_html.py 必须 ok（违规标签 / class / 本地图片等）

外加现场生成一个含「编号 + 项目符号 + 被正文打断的列表」的 .docx，
保证 Word 那条输入路径同样被覆盖（Word 跟 Markdown 走的是同一套渲染器，
但解析器是两份代码）。

退出码 0 = 全绿。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "wechat-mp-formatter")
SCRIPTS = os.path.join(SKILL, "scripts")
CONVERT = os.path.join(SCRIPTS, "convert.py")
CHECK = os.path.join(SCRIPTS, "check_html.py")
SAMPLE = os.path.join(SKILL, "assets", "sample.md")

ARTICLE_THEMES = ["green", "blue", "purple", "red", "orange", "classic"]
CODE_THEMES = ["github-light", "monokai", "one-dark", "dracula", "xcode"]
FONT_SIZES = [12, 16, 20]

# 结构红线：这些写法都会被微信后台洗坏，出现即失败
RE_FORBIDDEN = [
    (re.compile(r"</?(?:ol|ul|li)\b"), "出现了 ol/ul/li（编号会被洗成全是 1）"),
    (re.compile(r"<pre\b"), "<pre>（后台会弹「内容不会自动换行」）"),
    (re.compile(r"<code\b"), "<code>（同上，本项目一律用 span）"),
    (re.compile(r'<span[^>]*style="[^"]*display:\s*block'), 'span 上的 display:block（代码会挤成一行）'),
]

# 列表 marker 的提取式。它和 renderer._list() 里 marker span 的写法是配套的：
#   <span style="display:inline-block;width:1.9em;text-indent:0;color:#xxx;font-weight:bold">1.&nbsp;</span>
# 改动 marker 的样式后，这里要同步更新，否则会以「marker 数量对不上」的形式失败。
RE_MARKER = re.compile(
    r'display:inline-block;width:[\d.]+em;text-indent:0;[^"]*?font-weight:bold">([^<>]{1,6})&nbsp;</span>')

failed = []
passed = 0


def ok(msg):
    global passed
    passed += 1
    print("  \033[32m✓\033[0m %s" % msg)


def bad(msg, detail=""):
    failed.append(msg)
    print("  \033[31m✗\033[0m %s" % msg)
    if detail:
        for line in str(detail).splitlines()[:8]:
            print("      " + line)


def run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def convert(py, src, out, theme="green", font=16, code_theme=None):
    args = [py, CONVERT, src, "-o", out, "--theme", theme,
            "--font-size", str(font), "--no-fragment"]
    if code_theme:
        args += ["--code-theme", code_theme]
    r = run(args)
    for extra in (out.replace(".html", ".report.json"),):
        if os.path.exists(extra):
            os.unlink(extra)
    return r


def markers(html):
    return RE_MARKER.findall(html)


# ---------------------------------------------------------------- 1. 语法

def check_syntax(py):
    print("\n[1/5] 语法")
    for name in sorted(os.listdir(SCRIPTS)):
        if not name.endswith(".py"):
            continue
        src = open(os.path.join(SCRIPTS, name), encoding="utf-8").read()
        try:
            compile(src, name, "exec")
        except SyntaxError as exc:
            bad("%s 语法错误" % name, "%s: line %s" % (exc.msg, exc.lineno))
            return
    ok("%d 个 .py 全部通过" % len([n for n in os.listdir(SCRIPTS) if n.endswith(".py")]))

    node = shutil.which("node")
    js = os.path.join(SKILL, "assets", "web", "app.js")
    if not node:
        print("  · 跳过 app.js（没找到 node）")
        return
    r = run([node, "--check", js])
    if r.returncode == 0:
        ok("app.js 语法正确")
    else:
        bad("app.js 语法错误", r.stderr)


# ---------------------------------------------------------------- 2. 列表编号

# 每项 = (说明, markdown, 期望的 marker 序列)
FIXTURES = [
    ("被正文/代码块打断的编号（用户报的 bug）", """### 从库配置

1. 确认从库未初始化数据目录

如果从库安装时已自动初始化，需先清理：

```
# 停止从库
$ systemctl stop postgresql-18
```

2. 使用 pg_basebackup 创建从库基础备份

```
$ su - postgres
```

3. 写入 standby.signal

4. 在从库上验证复制状态

### 4.1 注意事项

1. 主库要放行复制用户
2. 从库 hot_standby 必须为 on
""", ["1.", "2.", "3.", "4.", "1.", "2."]),

    ("有序与无序混排（不能把圆点吞进编号）", """- 无序一层甲
- 无序一层乙
  - 无序二层甲
  - 无序二层乙

1. 有序一号
2. 有序二号
""", ["•", "•", "◦", "◦", "1.", "2."]),

    ("有序里嵌套有序", """1. 父项一
   1. 子项甲
   2. 子项乙
2. 父项二
""", ["1.", "a.", "b.", "2."]),

    ("显式起始序号", "5. 戊\n6. 己\n", ["5.", "6."]),

    ("分隔线归零", "1. 甲\n2. 乙\n\n---\n\n1. 丙\n", ["1.", "2.", "1."]),

    ("CRLF 换行 + 列表被代码块打断", "## 标题\r\n\r\n1. 甲\r\n\r\n代码：\r\n\r\n```\r\nls -l\r\n```\r\n\r\n2. 乙\r\n", ["1.", "2."]),

    ("列表项里嵌代码块", "1. 甲\n\n   ```\n   ls\n   ```\n\n2. 乙\n\n3. 丙\n", ["1.", "2.", "3."]),


    ("纯无序 / 三层嵌套", """- 一
  - 二甲
    - 三甲
- 二
""", ["•", "◦", "▪", "•"]),
]


def check_lists(py, tmp):
    print("\n[2/5] 列表编号序列 + 结构红线")
    for i, (name, md, expect) in enumerate(FIXTURES):
        src = os.path.join(tmp, "fx%d.md" % i)
        with open(src, "w", encoding="utf-8") as f:
            f.write(md)
        out = os.path.join(tmp, "fx%d.html" % i)
        r = convert(py, src, out)
        if r.returncode != 0:
            bad(name, (r.stderr or r.stdout)[-300:])
            continue
        html = open(out, encoding="utf-8").read()
        got = markers(html)
        if got != expect:
            bad("%s：marker 序列不符" % name,
                "期望 %s\n实际 %s" % (expect, got) if got else
                "期望 %s\n实际 0 个 marker —— 若刚改过 marker 的 style，"
                "请同步 dev/regression.py 里的 RE_MARKER" % expect)
            continue
        hit = [why for rx, why in RE_FORBIDDEN if rx.search(html)]
        if hit:
            bad("%s：触犯结构红线" % name, "、".join(hit))
            continue
        ok("%s → %s" % (name, " ".join(got)))


# ---------------------------------------------------------------- 3. Word 路径

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')

# Word 侧要用 numId 区分「同一串编号」和「新起一串」，所以这里刻意安排：
#   numId 5  被代码段打断，应当续号  -> 1 2 3 4
#   numId 7  换了标题后重开          -> 1 2
#   numId 7  被正文打断，仍是同一串   -> 3
#   numId 9  新的一串                -> 1 2
#   numId 11 项目符号                -> • •
DOCX_EXPECT = ["1.", "2.", "3.", "4.", "1.", "2.", "3.", "1.", "2.", "•", "•"]


def build_docx(path):
    def para(text, style=None, num=None, mono=False):
        ppr = "<w:pPr>"
        if style:
            ppr += '<w:pStyle w:val="%s"/>' % style
        if num:
            ppr += '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="%d"/></w:numPr>' % num
        ppr += "</w:pPr>"
        rpr = ('<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/></w:rPr>' if mono else "")
        runs = "".join('<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, t)
                       for t in text.split("\n"))
        return "<w:p>%s%s</w:p>" % (ppr, runs.replace("</w:r><w:r>", "</w:r><w:br/><w:r>"))

    body = "".join([
        para("三、从库配置", style="Heading2"),
        para("确认从库未初始化数据目录", num=5),
        para("如果从库安装时已自动初始化，需先清理："),
        para("# 停止从库\n$ systemctl stop postgresql-18", mono=True),
        para("使用 pg_basebackup 创建从库基础备份", num=5),
        para("$ su - postgres", mono=True),
        para("写入 standby.signal 并启动从库", num=5),
        para("在从库上验证复制状态", num=5),
        para("4.1 注意事项", style="Heading3"),
        para("主库要放行复制用户", num=7),
        para("从库 hot_standby 必须为 on", num=7),
        para("补充说明：下面这项本来就是第 3 项。"),
        para("这一项应该显示成 3.", num=7),
        para("另起一串编号："),
        para("新列表第一项", num=9),
        para("新列表第二项", num=9),
        para("无序甲", num=11),
        para("无序乙", num=11),
    ])
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document %s><w:body>%s'
           '</w:body></w:document>' % (NS, body))
    numbering = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering %s>'
                 '<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0">'
                 '<w:numFmt w:val="decimal"/><w:lvlText w:val="%%1."/></w:lvl></w:abstractNum>'
                 '<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0">'
                 '<w:numFmt w:val="bullet"/><w:lvlText w:val="&#8226;"/></w:lvl></w:abstractNum>'
                 '<w:num w:numId="5"><w:abstractNumId w:val="0"/></w:num>'
                 '<w:num w:numId="7"><w:abstractNumId w:val="0"/></w:num>'
                 '<w:num w:numId="9"><w:abstractNumId w:val="0"/></w:num>'
                 '<w:num w:numId="11"><w:abstractNumId w:val="1"/></w:num>'
                 '</w:numbering>' % NS)
    styles = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles %s></w:styles>' % NS
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
          '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
          '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    drels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
             '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
             '</Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
        z.writestr("word/_rels/document.xml.rels", drels)
        z.writestr("word/numbering.xml", numbering)
        z.writestr("word/styles.xml", styles)


def check_docx(py, tmp):
    print("\n[3/5] Word(.docx) 路径")
    src = os.path.join(tmp, "fixture.docx")
    try:
        build_docx(src)
    except Exception as exc:                       # pragma: no cover
        bad("生成 docx 测试文件失败", exc)
        return
    out = os.path.join(tmp, "fixture.html")
    r = convert(py, src, out)
    if r.returncode != 0:
        bad("docx 转换失败", (r.stderr or r.stdout)[-300:])
        return
    html = open(out, encoding="utf-8").read()
    got = markers(html)
    if got != DOCX_EXPECT:
        bad("docx marker 序列不符", "期望 %s\n实际 %s" % (DOCX_EXPECT, got))
        return
    hit = [why for rx, why in RE_FORBIDDEN if rx.search(html)]
    if hit:
        bad("docx 产物触犯结构红线", "、".join(hit))
        return
    ok("编号续号 / 换 numId 重开 / 项目符号 → %s" % " ".join(got))


# ---------------------------------------------------------------- 4. 组合矩阵

def check_matrix(py, tmp, quick):
    themes = ARTICLE_THEMES[:1] if quick else ARTICLE_THEMES
    fonts = [16] if quick else FONT_SIZES
    inputs = [("md", os.path.join(tmp, "mx.md"))]
    with open(inputs[0][1], "w", encoding="utf-8") as f:
        f.write(FIXTURES[0][1])
    if not quick:
        inputs.append(("sample.md", SAMPLE))
        inputs.append(("docx", os.path.join(tmp, "fixture.docx")))

    print("\n[4/5] 组合矩阵（%d 输入 × %d 主题 × %d 字号）"
          % (len(inputs), len(themes), len(fonts)))
    runs = 0
    problems = []
    for label, src in inputs:
        if not os.path.exists(src):
            problems.append("%s 不存在" % label)
            continue
        for th in themes:
            for fs in fonts:
                ct = CODE_THEMES[runs % len(CODE_THEMES)]
                out = os.path.join(tmp, "mx.html")
                r = convert(py, src, out, th, fs, ct)
                runs += 1
                if r.returncode != 0:
                    problems.append("%s/%s/%d 转换失败: %s" % (label, th, fs, (r.stderr or "")[-120:]))
                    continue
                html = open(out, encoding="utf-8").read()
                hit = [why for rx, why in RE_FORBIDDEN if rx.search(html)]
                if hit:
                    problems.append("%s/%s/%d 结构红线: %s" % (label, th, fs, "、".join(hit)))
                    continue
                c = run([py, CHECK, out, "--json"])
                try:
                    res = json.loads(c.stdout)
                except Exception:
                    problems.append("%s/%s/%d 自检输出异常" % (label, th, fs))
                    continue
                if not res.get("ok"):
                    problems.append("%s/%s/%d 自检报错: %s"
                                    % (label, th, fs, "; ".join(res.get("errors", []))[:120]))
    if problems:
        bad("%d/%d 组失败" % (len(problems), runs), "\n".join(problems[:6]))
    else:
        ok("%d 组全部通过（转换 + 结构红线 + 自检）" % runs)


# ---------------------------------------------------------------- 5. 自检的负例

NEGATIVE = """<section style="font-size:16px"><ol style="margin:0;list-style-type:decimal">
<li style="color:#333">甲</li><li style="color:#333">乙</li></ol></section>"""


def check_checker(py, tmp):
    print("\n[5/5] 自检能不能拦住旧写法（负例）")
    p = os.path.join(tmp, "old.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write(NEGATIVE)
    r = run([py, CHECK, p, "--json"])
    try:
        res = json.loads(r.stdout)
    except Exception:
        bad("自检输出不是 JSON", r.stdout[-200:] + r.stderr[-200:])
        return
    if res.get("ok"):
        bad("自检漏了 ol/li：这种写法粘到微信编号会全变 1")
        return
    if r.returncode == 0:
        bad("自检报了错但退出码是 0（CI 会误判通过）")
        return
    n = len(res.get("errors", []))
    ok("拦住了 %d 条：%s" % (n, res["errors"][0][:48] + "…"))


# ----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="公众号排版工具回归测试")
    ap.add_argument("--quick", action="store_true", help="跳过组合矩阵的大部分参数")
    ap.add_argument("--python", default=sys.executable, help="用哪个解释器跑子进程")
    args = ap.parse_args()

    if not os.path.isfile(CONVERT):
        print("找不到 convert.py：%s" % CONVERT)
        return 2

    print("回归测试 · 公众号排版工具")
    print("解释器：%s" % args.python)
    tmp = tempfile.mkdtemp(prefix="wxmp_reg_")
    try:
        check_syntax(args.python)
        check_lists(args.python, tmp)
        check_docx(args.python, tmp)
        check_matrix(args.python, tmp, args.quick)
        check_checker(args.python, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "-" * 56)
    if failed:
        print("结果：%d 通过 / \033[31m%d 失败\033[0m" % (passed, len(failed)))
        for f in failed:
            print("  ✗ %s" % f)
        return 1
    print("结果：\033[32m全部通过\033[0m（%d 项断言）" % passed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
