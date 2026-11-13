---
name: wechat-mp-formatter
description: 把 Markdown 或 Word(.docx) 文档排版成可直接复制粘贴到微信公众号编辑器的精美网页（全内联样式、代码块语法高亮、表格/引用/列表完整保真），并提供粘贴前合规自检。当用户提到「公众号排版」「微信文章」「粘贴到公众号编辑器」「把这篇 md/docx 转成公众号」「微信排版」「代码块别乱」等需求时应使用本技能。
agent_created: true
---

# 微信公众号排版助手

把已经写好的 Markdown 或 Word 文档，转成一份**能在微信公众号编辑器里原样保留样式的网页**：
打开网页 → 点「复制全文」→ 到公众号后台粘贴。代码块带语法高亮，缩进和结构不会串行。

所有产物零第三方依赖（纯 Python 标准库），不需要 pip install。

## 何时使用

- 用户给了 `.md` / `.markdown` / `.docx` 文件（或直接贴来的正文），要发到微信公众号
- 用户抱怨「粘贴到公众号后格式全乱了」「代码块没颜色」「表格边框没了」
- 用户要求「排版成公众号文章」「生成公众号 HTML」「做个能一键复制的网页」

## 六条铁律（决定成败）

公众号后台编辑器会在保存时清洗 HTML：剥掉 `<style>` / `<script>` / class / id，并把层级结构标准化。因此：

1. **每个元素必须自带 `style`**，不得依赖 class / id / `<style>` / `<link>` / CSS 变量。
2. **代码块不要用 `<pre>` / `<code>` 标签**：后台的「内容结构检测」会对 `pre` 报
   「内容不会自动换行，移动端可能出现水平溢出」。正确做法是**每一行包一个 `<section>`**
   来分行（块级来自标签语义）、缩进空格写成 `&nbsp;` 来保位、token 用
   `<span style="color:#xxx">` 上色。
   ⚠️ **绝对不要用 `<span style="display:block">` 分行**：微信重排时会洗掉 span 上的
   `display`，而相邻行之间没有任何换行标签，整块代码会**无缝挤成一行**（实测踩过，
   详见 `references/wechat-editor-rules.md` 第 4 节）。**结构只能靠标签语义，不能靠 `display`。**
   长行默认用 `word-break:break-all` 在容器内折行（`--code-mode scroll` 可改回横向滚动）。
3. **列表不要用 `<ol>` / `<ul>` / `<li>`**：序号/圆点是 CSS 的 `list-style` 画出来的，
   微信清洗后会整篇变成 `1.`（或编号整体消失）。而且写教程时列表常被说明段落和代码块打断，
   会被拆成多个 `<ol>`，每个都从 1 重新开始 —— 就是「同一级标题下面全是 1」。
   正确做法：**序号写成文本**（`1.` / `2.` / `•` / `◦`），每项一个
   `<section style="margin:6px 0;padding-left:1.9em;text-indent:-1.9em">`，
   marker 放在固定宽度的 `inline-block` span 里；渲染器按层计数，
   同一标题下被打断的列表接着数，遇到标题/分隔线（或 Word 换了 `numId`）才归零。
   注意 `text-indent` 会被子元素继承，项内的代码块要先包一层 `text-indent:0`。
   详见 `references/wechat-editor-rules.md` 第 5 节。
4. **图片**：微信不接收本地路径和 base64，必须先在素材库上传拿到 `mmbiz.qpic.cn` 链接。脚本只能把本地图 base64 嵌进去让预览好看，**粘贴前必须提醒用户换图**。
5. **正文布局不要用** `position:absolute/fixed`、`transform`、`animation`、`float`、`flex`，会被清掉导致错版。表格超宽用外层 `<section style="overflow-x:auto">` 兜。
6. **正文不要放可点击外链**：`<a href>` 在公众号正文里点了打不开；教学类文章建议用 `--link-mode text` 把 URL 明文写出来。

完整支持 / 不支持清单见 `references/wechat-editor-rules.md`。

## 工作流

有两种用法：**命令行批处理**（适合"帮我转一下这个文件"）和 **本地 Web 工作台**（适合用户想自己反复调排版）。

### 方式一：命令行转换

#### 第 1 步：确认输入与偏好

读一遍用户给的文件，判断来源（md / docx / 正文），然后定三件事：

| 项目 | 默认 | 什么时候改 |
| --- | --- | --- |
| 文章主题 `--theme` | `green` 青竹绿 | `blue` 科技、`orange` 生活、`purple` 设计、`red` 节日、`classic` 纯墨黑 |
| 代码配色 `--code-theme` | 随文章主题（`green`→`github-light` 等） | 深色常用 `one-dark`/`monokai`/`dracula`，浅色文章用 `github-light`/`xcode` |
| 正文字号 `--font-size` | `16`（移动端最佳阅读字号） | 信息密度高的长文用 14/15，短文或老年读者用 17/18 |
| 行号 `--line-numbers` | 关 | 教程类长代码建议开 |

用户没说就用默认值，先把结果做出来，用户看到预览后再微调，不要上来反问一堆问题。

#### 第 2 步：执行转换

```bash
# Markdown
python3 <SKILL_DIR>/scripts/convert.py 文章.md -o 输出目录/文章.wechat.html \
  --theme blue --title "标题" --author "署名" --date "2026-10-14" --line-numbers

# Word
python3 <SKILL_DIR>/scripts/convert.py 文章.docx -o 输出目录/文章.wechat.html --theme green
```

`<SKILL_DIR>` 为本技能所在目录。命令输出 JSON 报告，并生成三个文件：

| 文件 | 用途 |
| --- | --- |
| `xxx.wechat.html` | **成品**：浏览器打开 → 点顶栏「复制全文」→ 到公众号粘贴 |
| `xxx.fragment.html` | 纯正文片段，便于排查或二次处理 |
| `xxx.report.json` | 统计与警告的结构化数据，用于向用户汇报 |

#### 第 3 步：合规自检（不要跳过）

```bash
python3 <SKILL_DIR>/scripts/check_html.py 输出目录/文章.wechat.html
```

返回码 0 且没有「❌ 必须修复」才算合格。先处理 error（违规标签 / class / id / 本地图片路径），再看 warning。

#### 第 4 步：交付

用 present_files 展示 `xxx.wechat.html`，回复里讲清楚三件事：

1. 怎么用：打开网页 → 点「复制全文」→ 公众号后台 Ctrl/Cmd+V
2. 统计：多少字、多少代码块、多少表格
3. **需要用户手动处理的事**：本地图片要先上传素材库再替换（列出文件名）

### 方式二：本地 Web 工作台（推荐给需要反复调排版的场景）

用户想要"上传文件 → 实时预览 → 复制/下载"的可视化界面时，启动内置的零依赖 Web 服务：

```bash
python3 <SKILL_DIR>/scripts/server.py --open        # 默认 http://127.0.0.1:8765
python3 <SKILL_DIR>/scripts/server.py --port 9000 --no-open
```

启动后用 present_files 把 `http://127.0.0.1:8765/` 传进去，内置浏览器面板就能直接操作。
工作台提供：拖拽/粘贴 Markdown、上传 .docx、iPhone 18 Pro 真机尺寸预览（屏幕 402 × 874 pt）、
正文字号调节、一键复制富文本、下载「可复制页面」、合规自检面板、主题切换、草稿自动保存。
界面配色与微信保持一致（品牌绿 `#07c160`）。

预览用 iPhone 18 Pro 的**真实 CSS 视口尺寸**：机身 424px 宽 × 896px 高，含左右各 11px 边框，
屏幕内容区正好 402 × 874 —— 这样折行位置、字号观感与真机一致，预览才有参考价值。
改动预览相关样式时不要随手改这几个数字：`402`/`874` 是设备规格，`11` 是边框厚度，两者相加才是机身尺寸。

**预览永远按原始尺寸渲染，再整体 `transform: scale()` 缩放到可视区**（比例在 `fitPhone()` 里算），
所以整块屏幕始终完整可见，而不是只露出上面一小截。三种模式：

| 模式 | 行为 |
| --- | --- |
| `iPhone 18 Pro`（默认） | 真机比例自动缩放，整屏可见，标题栏右侧显示当前缩放比例 |
| `1:1` | 100% 实际像素，预览区可滚动，用于逐字核对观感 |
| `宽屏` | 去掉机身外壳铺满预览区，看长表格 / 长代码方便 |

不要把缩放改成压缩机身尺寸（例如 `height:min(896px,100%)`）——那样屏幕内容区会窄于 402px，
折行位置与真机不符，预览就失去意义。机身尺寸在 `.phone` 的 CSS 里，缩放只走 `transform`。

**状态栏（时间 / 灵动岛 / 信号 / WiFi / 电池）的三个图标一律用内联 SVG，不要退回 CSS 拼**：
信号条是 4 个圆角 `rect`、WiFi 是「三段圆弧描边 + 底部圆点」、电池是「外框描边 + 极耳 + 内芯」。
用 `radial-gradient` 叠出来的 WiFi 在小尺寸下会糊成一个彩虹圈（画不出扇形弧带的锐利切口），
这是踩过的坑。为了让三者视觉重量一致：WiFi 的 `stroke-width: 2.4`（24 的 viewBox 缩到 16px ≈ 1.6px）
对齐电池外框的 `1.6`；电池极耳要和外壳重叠约 0.5 单位，否则抗锯齿会切出一条白缝。
`.status-icons` 用 `color` + `fill:currentColor` 上色，改颜色只改一处。

合规自检面板折叠在**左侧编辑区下方**（展开时挤压编辑区，收起时完全不占位），
**不要**放回预览面板，更**不要**做成 `position:fixed` 浮层，否则会遮挡正文。
收起态靠 `hidden` 属性，所以 CSS 里必须有 `.check-panel[hidden]{display:none}` ——
否则 `.check-panel` 上的 `display:flex` 会盖过浏览器默认的 `[hidden]` 规则，表现为「点了收起也收不起来」。

服务是**只监听 127.0.0.1 的单机进程**，用户关掉终端即停止；不要改成 0.0.0.0 暴露到网络。

## 常用参数速查

```
--theme          green(默认 青竹绿)|blue|purple|red|orange|classic(经典墨黑)
--code-theme     one-dark|monokai|dracula|github-light|xcode
--font-size      正文字号 px，12 ~ 20，默认 16（移动端最佳阅读字号；其余元素按相对比例推导）
--line-numbers   代码块显示行号
--code-mode      block(默认，长行自动折行)|scroll(不折行，横向滚动；pre 为旧别名)
--heading-style  modern(默认)|simple
--divider        dots(默认)|line|gradient
--link-mode      keep(默认)|text(URL 明文)|strip
--image-mode     embed(默认，本地图转 base64)|keep|drop
--no-code-chrome 代码块去掉顶部语言栏
--flat-tags      标题也用 <p>（兼容性拉满，牺牲语义）
--title/--author/--date   生成居中片头
--no-footer / --footer-text  片尾引导语
--stdout        把可粘贴片段打到 stdout
```

### 关于正文字号

`--font-size` 只给正文基准，其余元素在 `Renderer._fs(delta)` 里按**相对偏移**推导，保证整体比例不变
（正文 16 时：段落/列表/引用 15、表格/行内代码 14、代码块 13、H2 19、H3 17、大标题 24）。
**不要**去改某个具体的 `font-size` 字面量，否则调字号时会出现「正文变了、表格没变」的错位。
基准值夹在 12 ~ 20px（越界或非法值自动回落默认，不报错），派生字号另有一条
`MIN_DERIVED_FONT_SIZE = 11` 的兜底：正文选 12px 时，代码块（−3）不会再被压到 9px。

### 关于文章主题（配色改动的规矩）

每个主题在 `ARTICLE_THEMES` 里是 12 个色位，**分工不能混**，否则整篇会「不成套」：

| 色位 | 用途 |
| --- | --- |
| `accent` | 主色：装饰元素（H2 竖条、H3 圆点、分隔线、渐变条、引用左边框）与链接 |
| `accent_deep` | 主色的深色版：**所有标题文字**、行内代码文字、表头文字 |
| `accent_soft` | 主色浅色版：引用底、行内代码底、表头底、片尾底 |
| `title` | 等于 `accent_deep`，保留该键只为兼容旧调用方 |
| `text` / `muted` | 正文色 / 次要文字（署名、图注、语言标签） |
| `quote_bg` / `border` | 引用块底色 / 边框与分割线底色 |
| `zebra` | 表格斑马纹（偶数行）底色 |
| `code_theme` | 该主题推荐的代码配色（前端会做「跟随主题」联动） |

**两条铁律**（都踩过）：

1. **标题必须用 `accent_deep`，不能用 `title` 那种近黑色**。之前的版本 H1/H2 用的是近黑
   （`#1a1a1a` / `#12263f` 之类），结果用户反馈「主题不明显、一级标题都是黑色」——装饰再花，
   文字全是黑的，主题感就没了。
2. **不能用 `accent` 直接当标题/正文色**。暖橙 `#ee7a1e`、亮绿这类主色在白底上只有 2~3:1 的对比度，
   当文字会糊。`accent_deep` 必须是同色系压深到 **≥ 4.5:1**（白底）的版本，改动配色后请复算。

其余主题化细节：行内代码用 `accent_soft` 底 + `accent_deep` 字（**不要**再写死 `#c7254e`）；
表格表头用 `accent_soft` 底 + `accent_deep` 字 + 下沿一条 `accent` 实线；正文用 `zebra` 做偶数行斑马纹。

主题顺序即界面下拉框顺序，**第一项 `green` 就是默认主题**（与工作台界面的微信绿呼应）。
改默认主题要同时改 `DEFAULT_THEME` 和 `ARTICLE_THEMES` 里的顺序。

> 拼 style 字符串时注意别拼出 `;;`（空声明）——`check_html.py` 会判定「style 写法异常」并告警，
> 那是真的会出问题（微信可能整条 style 丢弃）。表格表头那段就踩过：`font-weight:bold;` 后面
> 又接了一个以 `;` 开头的片段。

## 代码块处理要点（用户最在意的部分）

- 支持 `python py javascript js ts java go rust c cpp csharp php ruby sql swift kotlin bash sh yaml json html xml css nginx dockerfile diff` 等别名，未知语言降级为纯文本但**排版不乱**
- 先做词法切分再逐个 token 转义，所以 `<`、`&`、`&amp;` 不会被二次转义
- 缩进空格统一转成 `&nbsp;`，不会被 HTML 折叠
- **不使用 `<pre>` / `<code>` 标签**：后台结构检测对 `pre` 会报「不会自动换行、移动端可能水平溢出」。
  **分行靠每行一个 `<section>`**（标签自带块级，样式被洗掉也不串行），长行默认
  `word-break:break-all` 折行；若用户明确要求保留单行原样（代码更长、更在意对齐），
  用 `--code-mode scroll`，但要提醒超宽行在手机上可能看不到右半部分。
  再次强调：**不要退回 `<span style="display:block">` 分行**，微信会洗掉 `display` 导致整块挤成一行。
- 语言来源：Markdown 看围栏标注；**Word 没有代码块概念**，靠等宽字体或样式名含「代码 / code」来识别。
  Word 里「整段 + 软换行（Shift+Enter）」写的代码已经能正确还原成多行，详见 `references/troubleshooting.md`
- 改完代码块相关逻辑，务必用「逐行还原纯文本与原稿比对」+「抹掉 span 样式后再渲染」两步验证
  （缩进和空行最容易悄悄丢；分行是否依赖样式只有第二步才看得出来）

## 列表处理要点（同样容易被微信洗坏）

- **不用 `ol` / `ul` / `li`**，序号写文本：一层 `1.` 二层 `a.` 三层 `i.`，无序 `•` `◦` `▪`
- 每项一个 `<section style="margin:6px 0;padding-left:1.9em;text-indent:-1.9em">`，
  首个段落直接内联在 marker 后面（不能包 `<p>`，否则序号独占一行），
  项内的代码块/后续段落统一包一层 `<section style="text-indent:0">`（`text-indent` 会被继承）
- 续号规则：渲染器按层计数，**同一标题下被正文/代码块打断的列表接着数**；
  遇到标题、分隔线，或 Word 里换了 `numId`（解析器标 `restart`）→ 从 1 开始
- 解析器只认「标记类型 + 缩进」：有序↔无序交替、缩进回到更外层都必须断开成两串列表，
  否则紧跟编号列表的项目符号会被吞进编号里（圆点变数字）
- 改完列表逻辑，用「marker 文本序列断言」+「把所有 `style` 全部抹掉再渲染」两步验证

## 已知限制

- Word 的公式、艺术字、文本框内容、复杂分栏无法可靠还原
- 公众号正文不支持交互（无 JS）、不支持外链跳转
- 图片必须由用户在后台上传，脚本无法代劳

遇到问题先查 `references/troubleshooting.md`。

## 文件清单

```
scripts/
  convert.py      命令行入口：md/docx -> 公众号 HTML + 预览页 + JSON 报告
  server.py       本地 Web 工作台服务（零依赖 HTTP，默认 127.0.0.1:8765）
  check_html.py   粘贴前合规自检（违规标签/class/图片/闭合/重复转义/ol·ul·li）
  mdparser.py     Markdown -> AST（纯标准库）
  docxreader.py   Word -> AST（zipfile + ElementTree，不依赖 python-docx）
  renderer.py     AST -> 全内联样式 HTML（配色与排版规则集中在这里）
  highlighter.py  语法高亮 + 代码配色主题
  preview.py      生成带「复制全文」按钮的预览页
assets/
  sample.md       冒烟测试样例（代码/表格/引用/列表齐全），也是工作台的示例文章
  web/            工作台前端（index.html / app.css / app.js）
references/
  wechat-editor-rules.md   编辑器兼容规则详表
  troubleshooting.md       排错清单与 Word 代码块识别约定
```

## 改动这个技能时请注意

- 抓取仓库/网站上别人写的 `class` 样式来改 `renderer.py` 是**错的**：产物必须全内联样式。
- 新增主题只需在 `renderer.ARTICLE_THEMES` / `highlighter.CODE_THEMES` 里加一项，工作台下拉会自动出现。
- 改完务必跑一遍冒烟：`convert.py assets/sample.md -o /tmp/t.html` + `check_html.py /tmp/t.html`，
  再用 `server.py` 手工点一遍上传/复制/下载。
- 动了列表解析或渲染，除了上面两步，还要断言 marker 文本序列（例如 `1. 2. 3. 4. / 1. 2. / • •`），
  并把产物里所有 `style` 整条抹掉再渲染一次 —— 编号仍然正确才算修好。
