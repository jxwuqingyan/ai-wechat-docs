# ai-wechat-docs — Agent 工作手册

给「在这个仓库里干活的 AI 助手」以及「三个月后的自己」看的工作手册。

> **本文件是所有 AI 工具的唯一规则源**：约定只在这里写一份。
> 仓库里**不放**任何工具专属的规则副本或桥接文件——复制出去就会漂移，
> 漂移之后 agent 会照着旧规则干活，比没有规则更糟。

- 给人看的上手说明 + **服务器部署指南（四种方案）** → `README.md`
- 给 AI 的技能说明书（触发词、工作流、参数速查）→ `wechat-mp-formatter/SKILL.md`

### 各个工具怎么读到本文件

| 工具 | 接入方式 |
| --- | --- |
| Codex、Cursor、GitHub Copilot、Gemini CLI、Jules、Aider、Zed、Warp、goose、Windsurf/Devin、JetBrains Junie、Amp、RooCode、Kilo Code | **原生读**仓库根的 `AGENTS.md`，零配置 |
| Claude Code | 不原生读（截至 2026 年中）。要用时在本地建软链接，**不要提交**：`ln -s AGENTS.md CLAUDE.md`（`CLAUDE.md` 已在 `.gitignore` 里） |
| WorkBuddy | 会话启动时自动把 `AGENTS.md` 注入项目上下文 |

**不要再新建** `.cursorrules`（Cursor 已废弃该格式）、`.windsurfrules`、`copilot-instructions.md`、
`CLAUDE.md` 这类重复文件。某个工具确实需要专属内容时，写进它**本地**的桥接文件并保证不被提交；
**共用规则一律回本文件改**。

**仓库**：`git@code.easyops.online:easyops/ai-wechat-docs.git`（内网 GitLab，远端名 `origin`，主分支 `main`）。
这份仓库是**唯一源码位置**；`~/.workbuddy/skills/wechat-mp-formatter/` 是 `./install.sh` 同步出来的产物，改它等于白改。

**一句话**：把 Markdown / Word(`.docx`) 排版成可以直接粘贴进微信公众号编辑器的 HTML，
并保证粘过去之后**排版不失真**。纯 Python 标准库，不装任何第三方包。

---

## 1. 30 秒上手

> 下面的命令都在**仓库根目录**执行（`dev/` 的脚本用相对路径读文件）。
> 脚本本身零第三方依赖，用系统 `python3`（≥ 3.8）即可。

```bash
# 起本地工作台（开发时最常用；改前端后刷新即可，静态资源不走缓存）
./start.sh                      # http://127.0.0.1:8765/
PORT=9000 ./start.sh            # 换端口；端口被占会自动往后试并在终端提示

# 命令行转换 + 粘贴前自检
python3 wechat-mp-formatter/scripts/convert.py 文章.md -o /tmp/a.html --theme green
python3 wechat-mp-formatter/scripts/check_html.py /tmp/a.html

# 回归测试（改完代码跑这个，--quick 约 3 秒，全量约 27 秒）
python3 dev/regression.py --quick

# 要看渲染效果 / 点按钮 / 传文件（无依赖 CDP 工具，会自己拉浏览器）
node dev/shot.mjs --launch --url http://127.0.0.1:8765/ --steps dev/steps.example.json

# 改完代码必须同步到技能目录，否则 WorkBuddy 里跑的还是旧代码
./install.sh
```

> 本机推荐用受管 Python：`/Users/wuqy/.workbuddy/binaries/python/versions/3.13.12/bin/python3`。
> 脚本零依赖，用 `python3` 也一样，只要 ≥ 3.8。

---

## 2. 代码地图（改哪里）

> 下表的 `scripts/` 与 `assets/`、`references/` 都在 **`wechat-mp-formatter/`** 下
> （那个目录同时就是 WorkBuddy 技能包本体）。

| 文件 | 职责 | 动它的时候注意 |
| --- | --- | --- |
| `scripts/mdparser.py` | Markdown → AST | 列表分组规则很脆：标记类型（有序↔无序）变化、缩进回外层都必须断开 |
| `scripts/docxreader.py` | Word → AST（`zipfile` + `ElementTree`） | 只认 `.docx`/`.docm`；代码块靠等宽字体识别；图片在 `<w:r>` 子树里找 |
| `scripts/renderer.py` | AST → 全内联样式 HTML | **本项目的心脏**。配色、字号、列表 marker、代码块分行都在这里 |
| `scripts/highlighter.py` | 语法高亮 + 代码配色 | token 级上色，先分词后转义（避免二次转义） |
| `scripts/convert.py` | 命令行入口：md/docx → HTML + 预览页 + JSON 报告 | 业务错误走 `ValueError`，别把异常类名吐给用户 |
| `scripts/check_html.py` | 粘贴前合规自检 | 新踩的坑就往这里加规则，最好报成 error |
| `scripts/server.py` | 本地 Web 服务（`ThreadingHTTPServer`） | 默认 `127.0.0.1`，**不要改成 0.0.0.0** |
| `scripts/preview.py` | 生成带「复制全文」按钮的预览页 | 页面外壳里的 `<ul>/<li>` 只用于工具条，不进正文 |
| `assets/web/{index.html,app.css,app.js}` | 工作台前端 | 无构建步骤，改完刷新即可 |
| `references/wechat-editor-rules.md` | 微信编辑器兼容规则详表 | **改渲染规则前先读它**，里面写了每条规则的来由 |
| `references/troubleshooting.md` | 排错清单 | **每修一个 bug 都往这里加一行**（症状 → 根因 → 解法） |
| `dev/regression.py` / `dev/shot.mjs` | 回归测试 / 浏览器验证 | 见第 5 节 |

---

## 3. 六条铁律（违反＝必出 bug）

微信后台保存正文时会**重新解析并清洗内联样式**。实测：容器 `<section>` 的
`background-color`/`border-radius`、`<span>` 上的 `display:inline-block` 都活着，
但 `<span style="display:block">` 的 `display` 会丢。由此得出：

1. **结构只能用标签语义**（`<section>` / `<p>` / `<br>`），**永远不要用 `display` 撑结构**。
   样式只负责好看，不负责结构。
2. **代码块不用 `<pre>` / `<code>`**：后台「内容结构检测」会弹窗提示不会自动换行。
   做法是**每行一个 `<section>`**，空行用 `&nbsp;`，缩进用 `&nbsp;`，token 用
   `<span style="color:#xxx">` 上色。
3. **列表不用 `<ol>` / `<ul>` / `<li>`**：序号是 CSS 画的，洗掉后整篇有序项全变 `1.`。
   做法是**序号写成文本**（`1.` / `a.` / `•`），每个列表项一个 `<section>`。
4. **图片**：本地路径 / base64 微信一定不收。脚本只能内嵌 base64 让预览好看，
   **交付时必须提醒用户去素材库上传后替换**。
5. **布局不用** `position:absolute/fixed`、`transform`、`animation`、`float`、`flex`
   —— 会被清掉导致错版。表格超宽用外层 `<section style="overflow-x:auto">` 兜。
6. **正文不放可点击外链**：`<a href>` 在公众号正文里点不开，教学文建议
   `--link-mode text` 把 URL 明文写出来。

**派生规则**：正文里承载「结构含义」（分行、分栏、占位、序号）的东西只能用自带块级语义的标签；
少用一个 CSS 属性就少一处被清洗的变量。

---

## 4. 字号与配色（不要自作主张）

- **字号一律用 `Renderer._fs(delta)` 推导**，禁止直接写 `font-size` 字面量。
  基准是 `DEFAULT_FONT_SIZE = 16`（移动端最佳阅读字号），派生有 `MIN_DERIVED_FONT_SIZE = 11` 兜底。
  正文选 12px 时代码块（−3）不会被压到不可读。
- **主题色分三层用**，见 `ARTICLE_THEMES`：
  `accent` 给装饰（竖条/圆点/分隔线/渐变条）、`accent_deep` 给**所有标题文字和行内代码文字**、
  `accent_soft` 给底色（引用/行内代码/表头/片尾）。
  把标题设成近黑色，整篇就「没有主题感」了。
- 拼 `style` 字符串**别拼出 `;;`**（空声明），`check_html.py` 会判「style 写法异常」并告警。
- **零第三方依赖**：连 `dev/` 下的验证脚本也只能用标准库 / Node 内置模块。
  这条是刻意的 —— 离线服务器、受限容器里都要能直接跑。

---

## 5. 改完必须怎么验

按改动范围选档，**不要跳过**：

| 改了什么 | 最低验证 |
| --- | --- |
| 注释 / 文档 | 无 |
| 主题、字号、间距等样式常量 | `dev/regression.py` |
| `renderer.py` / `highlighter.py` | `dev/regression.py` + 下面「模拟微信清洗」 |
| `mdparser.py` / `docxreader.py` | `dev/regression.py`（它自带 Word 与 Markdown 两侧的编号序列断言） |
| `assets/web/*` 前端 | `dev/shot.mjs` 截图 + HTML 里的 `id` 与 JS 里 `$('...')` 交叉校验 |
| 代码块分行 / 列表编号 | 断言 marker 序列 + **把所有 `style` 整条抹掉再渲染** |

### 5.1 回归脚本

```bash
python3 dev/regression.py            # 全量：3 输入 × 6 主题 × 3 字号 + 8 个列表用例 + Word 用例
python3 dev/regression.py --quick    # 约 3 秒，覆盖全部断言，只砍组合矩阵
```

它守四件事：语法、结构红线（不得出现 `ol/ul/li/pre/code` 与 `span[display:block]`）、
**列表编号的 marker 文本序列**、`check_html.py` 必须 ok，外加一个「自检能拦住旧写法」的负例。

> 列表编号是最容易静默回归的地方：肉眼看截图看不出 `1. 1. 1. 1.` 和 `1. 2. 3. 4.` 的区别，
> 所以必须按序列断言。改了 marker 的 style 后，同步更新 `dev/regression.py` 里的 `RE_MARKER`。

### 5.2 模拟微信清洗（最接近真实后台的一步）

把产物里**所有 `style` 属性整条抹掉**再渲染：代码块应该仍然一行一行、列表编号应该仍然
`1. 2. 3.`。如果抹掉样式后串行、编号退化成全 `1.`，说明还有依赖样式的地方。

`dev/steps.example.json` 里就有这一步，直接跑：

```bash
node dev/shot.mjs --launch --url http://127.0.0.1:8765/ --steps dev/steps.example.json
```

截图落在 `dev/shots/`（已在 `.gitignore` 里）。步骤格式、可用字段见 `dev/shot.mjs` 顶部注释。

### 5.3 交付前的固定动作

```bash
./install.sh                                    # 同步到 ~/.workbuddy/skills/wechat-mp-formatter/
python3 wechat-mp-formatter/scripts/check_html.py <产物>   # 必须 ✅
```

`examples/公众号排版示例.wechat.html` 是给别人看的成品，改了渲染规则要重新生成：

```bash
python3 wechat-mp-formatter/scripts/convert.py wechat-mp-formatter/assets/sample.md \
  -o examples/公众号排版示例.wechat.html --title "Pod 一直 Pending 怎么查" \
  --author "运维笔记" --date "2026-10-16"
rm -f examples/*.fragment.html examples/*.report.json   # 只留那一个成品
```

---

## 6. 已知的坑（都踩过，别再踩）

| 坑 | 症状 | 正确做法 |
| --- | --- | --- |
| `<span style="display:block">` 分行 | 代码行**无缝挤成一行** | 用 `<section>` 分行，见铁律 1 |
| `<li>` 的编号靠 `list-style` | 有序列表全变 `1.` | 序号写文本，见铁律 3 |
| 列表被正文/代码块打断 | 拆成多个 `<ol>`，各自从 1 开始 | 渲染器按层续号；标题/`<hr>` 才归零 |
| `text-indent` 是**继承属性** | 列表项里的代码块首行被往左拽出去 | 项内非首行内容包一层 `<section style="text-indent:0">` |
| 列表项首个段落包 `<p>` | 序号独占一行，正文掉到下一行 | 首个段落直接内联到 marker 后面 |
| CSS 渐变拼图标 | WiFi 图标糊成一团彩虹圈 | 状态栏图标一律内联 SVG（`assets/web/index.html`） |
| 给被 `overflow:hidden` 裁掉的元素加 `scale` | 放大后看不见 | 克隆到 `position:fixed` 浮层里再放大（`shot.mjs` 的 `clipShot`） |
| `.check-panel[hidden]` | 自检面板收不起来 | CSS 里必须有 `.check-panel[hidden]{display:none}` |
| `rsync --delete` | 被 `--exclude` 的文件删不掉 | 用 `--delete-excluded` |
| `file://` 导航 | 从 http 页面跳不到本地文件 | 起个临时静态服务，或直接在页面里注入 DOM |
| 想直接改 `~/.workbuddy/skills/` | 下次同步被覆盖 | **唯一源码是本仓库**，改完跑 `./install.sh` |
| `chrome-headless-shell` 起不来 | `GPU process isn't usable` | 加 `--no-sandbox --disable-gpu`（`shot.mjs` 已内置） |

---

## 7. 迭代约定

- **一次只动一件事**，改完立刻跑对应档位的验证，别攒到最后一起验。
- **修 bug 必须留痕**：`references/troubleshooting.md` 加一行（症状 → 根因 → 解法）。
  再往项目日志 `.workbuddy/memory/YYYY-MM-DD.md` 记一笔（本仓库内，已在 `.gitignore` 里，
  不随仓库分发）。同一个坑踩两次是浪费。
- **不引入依赖、不加构建步骤**。要加依赖之前先问：标准库 / 原生 JS 真的做不到吗？
- **保持单机定位**：默认只监听 `127.0.0.1`。要对外就加 Nginx + Basic Auth + HTTPS，
  别把 `--host 0.0.0.0` 当成"让同事也能用"的捷径（这服务没有任何认证）。
- **改渲染规则前先读** `references/wechat-editor-rules.md`：里面每条规则都写了是哪个坑换来的。
- 交付给用户的产物，**必须提醒**：本地图片要自己上传替换；改过结构的话要重新生成再粘贴。
