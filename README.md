# ai-wechat-docs

把 **Markdown / Word 文档**排版成可以直接粘贴进**微信公众号编辑器**的 HTML —— 带语法高亮的代码块、
保真的表格与列表，并且全程不需要安装任何第三方依赖（纯 Python 标准库）。

```
写好的 .md / .docx  ──▶  本项目  ──▶  打开网页点「复制全文」  ──▶  公众号后台粘贴
```

## 为什么需要它

微信公众号后台编辑器会清洗 HTML：剥掉 `<style>` 标签、`class`、`id` 和 `<script>`，
粘贴普通网页进去样式基本全丢，代码块尤其惨 —— 要么变成一行，要么没有颜色。
本项目围绕这条限制生成**全部内联样式**的 HTML，并针对代码块做了三层保真处理，
所以粘贴过去是什么样，发布后就是什么样。

## 能力一览

| 能力 | 说明 |
| --- | --- |
| 输入 | Markdown（`.md` / `.markdown` / `.txt`）、Word（`.docx` / `.docm`）；`.doc` / `.rtf` 会明确提示先另存为 .docx |
| 输出 | 可直接粘贴的正文 HTML、可反复使用的预览页、纯正文片段 |
| 代码块 | 30+ 语言语法高亮，彩色行内 span，缩进不丢、长行自动折行、可选行号；**不使用 `<pre>` 标签**，每行用 `<section>` 分行（不依赖 CSS，微信重排也不会串行） |
| 排版 | 标题 / 引用 / 有序无序多级列表 / 表格 / 图片 / 分隔线 / 片头片尾 |
| 主题 | 6 套文章配色 × 5 套代码配色 |
| 自检 | 粘贴前检查违规标签、class、风险 CSS、裂图风险、重复转义 |
| 界面 | 本地 Web 工作台：拖拽上传、iPhone 18 Pro 真机尺寸预览（屏幕 402 × 874 pt，整屏缩放可见 / 1:1 / 宽屏）、正文字号可选、一键复制、下载页面 |

---

## 快速开始

### 获取代码

```bash
git clone git@code.easyops.online:easyops/ai-wechat-docs.git
cd ai-wechat-docs
```

项目主页在内网 GitLab：`https://code.easyops.online/easyops/ai-wechat-docs`（远端名 `origin`，主分支 `main`）。

### 本地（个人电脑）

```bash
# macOS：双击「公众号排版工作台.command」
# 或者命令行：
./start.sh --open
```

浏览器会打开 <http://127.0.0.1:8765/>，左侧粘贴或拖入文档，右侧实时预览，点「复制全文」即可。

想换个端口用 `PORT=9000 ./start.sh` 或 `./start.sh --port 9000`；端口被占用时会自动往后试，
并在终端里说明实际地址。

### 命令行（批量或脚本化）

```bash
python3 wechat-mp-formatter/scripts/convert.py 文章.md -o 文章.wechat.html \
    --theme blue --title "标题" --author "署名" --line-numbers

python3 wechat-mp-formatter/scripts/check_html.py 文章.wechat.html
```

### 改代码（含 AI 助手协作）

改之前先读 **[AGENTS.md](AGENTS.md)**（铁律、字号配色约定、验证分档、已知的坑），
改完至少跑一遍：

> 仓库**只保留 `AGENTS.md` 这一个 AI 规则文件**，不放 `.cursorrules` / `copilot-instructions.md`
> / `CLAUDE.md` 之类的副本。主流工具原生读它；用 Claude Code 的话在本地软链接一个
> `ln -s AGENTS.md CLAUDE.md` 即可（该名字已在 `.gitignore`，不会误提交）。

```bash
python3 dev/regression.py --quick      # 语法 / 结构红线 / 列表编号序列 / 自检，约 3 秒
./install.sh                           # 同步到 ~/.workbuddy/skills/（技能目录是产物，勿直接改）
```

---

## 环境要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | 任意 Linux 发行版（Ubuntu / Debian / CentOS / Alpine 均可），也支持 macOS |
| Python | **3.8+**，无需 `pip install` 任何东西 |
| 磁盘 | 部署时只需要 `wechat-mp-formatter/`，约 270 KB（15 个文件）；运行时临时文件在 `/tmp`，单个文档最大 24 MB |
| 内存 | 常驻约 30 MB，处理文档时叠加几 MB |
| 浏览器 | 使用者的浏览器需要是 Chrome / Edge / Safari 等现代浏览器（Web 工作台需要） |

检查 Python：

```bash
python3 -V
# 期望输出 Python 3.8 或更高
```

> **不需要 `pip install`，也不需要虚拟环境。** 本项目刻意只用 Python 标准库实现
> （Markdown 解析、Word 解析、语法高亮全部自带），这样在离线服务器、受限容器里都能直接跑起来。

---

## 部署到服务器

面向：把这套「公众号排版工作台」部署到 Linux 服务器（云主机 / 内网机器 / 容器平台）上长期使用。
跟着下面的 **部署前必读** 看完，然后按你的场景选一种方案即可。

### 部署前必读

#### ⚠️ 这个服务没有登录功能

它的设计目标是**单机个人工具**：没有账号体系、没有权限控制、没有限流、没有审计日志。
默认只监听 `127.0.0.1`，也就是**只有本机能访问**。

所以：

| 部署方式 | 是否安全 | 说明 |
| --- | --- | --- |
| 只在本机用（默认） | ✅ 安全 | 监听 127.0.0.1，外部无法连接 |
| 内网 + IP 白名单 | ✅ 可接受 | 通过 Nginx 限制来源网段 |
| 公网 + HTTPS + Basic Auth | ⚠️ 基本可用 | **必须**两层都加，见〈方案四：Nginx 反向代理〉 |
| 直接 `--host 0.0.0.0` 暴露公网 | ❌ 千万别 | 任何人都能用你的服务器排版、并上传文件到你的机器 |

#### ⚠️ 文档内容会上传到服务器

使用 Web 工作台时，你粘贴或上传的文稿会以 HTTP 请求的形式发到部署这个服务的机器上并在那里解析。
如果用公网服务器，请自行评估内容敏感性 —— 重要的、未发布的稿件建议只在本机用。

#### 关于「复制全文」按钮

浏览器只在 **安全上下文**（HTTPS，或 `localhost` / `127.0.0.1`）下开放完整的剪贴板 API。
通过 `http://服务器IP:8765` 这种明文地址访问时，按钮会自动降级为「选中文本 + 复制」的兼容方案 ——
仍能复制成功，但**需要你手动触发一次**，体验会差一些。

结论：只要对外提供服务，就配上 HTTPS。

### 方案一：直接运行（最快，5 分钟搞定）

适合：临时使用、内网机器、想先看看效果。

#### 1. 上传代码

在你的本地机器上执行（把 `user@server` 换成你的服务器）：

```bash
# 整个项目
rsync -avz --exclude '.DS_Store' --exclude '__pycache__' \
  ./ai-wechat-docs/ user@server:~/ai-wechat-docs/
```

没有 rsync 也可以用 scp：

```bash
scp -r ./ai-wechat-docs user@server:~/
```

服务器上只需要 `wechat-mp-formatter/` 这一个子目录就能跑，`start.sh`、`Dockerfile` 这些是部署脚手架，可以不传。

#### 2. 启动

```bash
cd ~/ai-wechat-docs
chmod +x start.sh
./start.sh
```

看到这样的输出就是成功了：

```
Python : Python 3.12.3
监听   : http://127.0.0.1:8765/   （可用 PORT=9000 ./start.sh 修改）
停止   : 按 Control + C

✅ 公众号排版工作台已启动：http://127.0.0.1:8765/
   停止服务按 Ctrl+C
```

#### 3. 验证

另开一个终端：

```bash
curl -s http://127.0.0.1:8765/api/health
# {"ok": true, "service": "wx-mp-studio"}
```

#### 4. 后台常驻（不用 systemd 时）

```bash
# 方式 A：nohup
nohup ./start.sh > /var/log/wxmp.log 2>&1 &

# 方式 B：tmux（推荐，随时能回去看输出）
tmux new -s wxmp
./start.sh
# 按 Control+B 然后 D 脱离会话；下次 tmux attach -t wxmp 回来
```

停止：

```bash
pkill -f "wechat-mp-formatter/scripts/server.py"
```

> 机器重启后不会自动恢复，长期运行请用下面的 systemd 或 Docker 方案。

### 方案二：systemd 常驻服务（推荐）

适合：一台长期运行的 Linux 服务器，开机自启、崩溃自动重启。

#### 1. 建一个专用低权限用户

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin wxmp
```

#### 2. 部署代码到 /opt

```bash
sudo mkdir -p /opt/ai-wechat-docs
sudo rsync -a --exclude '.DS_Store' --exclude '__pycache__' \
  ~/ai-wechat-docs/ /opt/ai-wechat-docs/
sudo chown -R root:root /opt/ai-wechat-docs
sudo chmod -R a-w /opt/ai-wechat-docs      # 代码只读，服务不需要写权限
```

#### 3. 安装服务单元

```bash
sudo cp /opt/ai-wechat-docs/deploy/wechat-mp-formatter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wechat-mp-formatter
```

单元文件里几个可能需要按实际情况调整的地方：

- `ExecStart` 里的 Python 路径：用 `which python3` 的输出替换 `/usr/bin/python3`
- `User` / `Group`：如果你建的用户名不是 `wxmp`
- `ReadWritePaths=/tmp`：服务只在 `/tmp` 写临时文件（Word 图片提取、导出），这个权限必须保留

#### 4. 常用运维命令

```bash
sudo systemctl status wechat-mp-formatter      # 看运行状态
sudo journalctl -u wechat-mp-formatter -f      # 实时日志
sudo systemctl restart wechat-mp-formatter     # 重启
sudo systemctl stop wechat-mp-formatter        # 停止
sudo systemctl disable wechat-mp-formatter     # 取消开机自启
```

#### 5. 排错

服务起不来时，先看日志里有没有这类信息：

| 日志关键字 | 原因 | 处理 |
| --- | --- | --- |
| `Permission denied` | `/tmp` 不可写，或被 `ProtectHome` / `ProtectSystem` 挡了 | 确认 `PrivateTmp=true`、`ReadWritePaths=/tmp` 没被改掉 |
| `Address already in use` | 8765 被占用 | 改单元里的 `PORT`，或先找出占用进程 |
| `status=203/EXEC` | `ExecStart` 里的 python 路径不对 | `which python3` 确认真实路径 |
| `code=exited, status=1` + 找不到 server.py | 路径写错 | 确认 `/opt/ai-wechat-docs/wechat-mp-formatter/scripts/server.py` 存在 |

### 方案三：Docker / Docker Compose

适合：已有容器环境的团队，或想要干净隔离。

镜像里**不需要 `pip install`**（零依赖），所以构建很快、镜像很小。

#### 1. 构建与运行

```bash
cd ai-wechat-docs
docker build -t wx-mp-studio .

docker run -d \
  --name wx-mp-studio \
  --restart unless-stopped \
  -p 127.0.0.1:8765:8765 \
  --read-only --tmpfs /tmp:size=64m \
  --security-opt no-new-privileges:true \
  wx-mp-studio
```

**注意 `-p` 前面的 `127.0.0.1:` 不能省。** 少写这四个字，端口会绑定到所有网卡，
等于把没有任何认证的服务直接挂到公网。容器内部必须监听 `0.0.0.0`（Dockerfile 已配好），
真正的访问控制靠宿主机这一层的端口绑定和 Nginx。

#### 2. 用 Compose（更省事）

```bash
docker compose up -d          # 启动
docker compose logs -f        # 看日志
docker compose down           # 停止并删除
docker compose up -d --build  # 改了代码后重建
```

#### 3. 验证与健康检查

```bash
curl -s http://127.0.0.1:8765/api/health
docker inspect --format '{{.State.Health.Status}}' wx-mp-studio   # healthy
```

镜像内置了 HEALTHCHECK（每 30 秒探一次 `/api/health`）。

### 方案四：Nginx 反向代理（对外访问的唯一推荐方式）

适合：需要从别的机器访问。**这是把服务暴露出去之前必须做的一步。**

准备一个现成的配置模板：`deploy/nginx.conf.example`。

#### 1. 加访问口令

```bash
sudo apt install apache2-utils           # Debian/Ubuntu
# sudo yum install httpd-tools           # CentOS/RHEL

sudo htpasswd -c /etc/nginx/.htpasswd wxmp
# 按提示输入两次密码（这就是以后访问页面的账号密码）
```

#### 2. 启用站点

```bash
sudo cp deploy/nginx.conf.example /etc/nginx/conf.d/wxmp.conf
sudo vim /etc/nginx/conf.d/wxmp.conf     # 改 server_name 为你的域名
sudo nginx -t && sudo systemctl reload nginx
```

配置里有三个关键点，改动时别漏：

1. `auth_basic` + `auth_basic_user_file` —— 访问认证
2. `client_max_body_size 32m` —— 前端上传 Word 时会转成 base64（体积约为原文件的 1.37 倍），
   服务端上限 24 MB，所以 Nginx 这里要给到 32 MB，否则大文档会被拦成 **413**
3. `proxy_pass http://127.0.0.1:8765` —— 指向本地服务

#### 3. 配 HTTPS（强烈建议）

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d wxmp.example.com
```

配好 HTTPS 之后，「复制全文」按钮才能走完整的剪贴板 API（原因见〈部署前必读〉）。
Certbot 会自动处理续期。

#### 4. 只给内网开放的替代做法

如果用户都在公司内网，用 IP 白名单比口令更省事，把 `nginx.conf.example` 里注释掉的
`allow` / `deny` 打开即可：

```nginx
allow 10.0.0.0/8;
allow 192.168.0.0/16;
deny  all;
```

### 防火墙

只在本机使用（默认配置）时，**不要**开放 8765：

```bash
# 正确做法：什么都不用做。服务只监听 127.0.0.1，外部本来就连不上。
```

如果走 Nginx 对外提供访问，只放行 HTTP/HTTPS：

```bash
# ufw（Ubuntu）
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw status

# firewalld（CentOS/RHEL）
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

云服务器还要记得在**安全组**里放行 80/443，并且**不要**放行 8765。

### 升级与回滚

升级就是把新代码覆盖过去，然后重启 —— 没有任何数据库或状态需要迁移。

```bash
# 1. 从本地重新上传（先在本地改好代码）
rsync -avz --exclude '.DS_Store' --exclude '__pycache__' \
  ./ai-wechat-docs/ user@server:~/ai-wechat-docs/

# 2. 服务器上覆盖部署目录
sudo rsync -a --delete ~/ai-wechat-docs/ /opt/ai-wechat-docs/
sudo chmod -R a-w /opt/ai-wechat-docs

# 3. 重启并验证
sudo systemctl restart wechat-mp-formatter
curl -s http://127.0.0.1:8765/api/health
```

Docker 方式：

```bash
docker compose up -d --build
docker compose ps
```

回滚：把旧版本代码再覆盖一次、重启即可。建议保留一份上一个可用版本：

```bash
sudo cp -R /opt/ai-wechat-docs /opt/ai-wechat-docs.bak-$(date +%F)
```

### 日志与排错

#### 日志在哪

| 部署方式 | 看日志 |
| --- | --- |
| 前台运行 | 直接看终端输出 |
| nohup | `tail -f /var/log/wxmp.log` |
| systemd | `sudo journalctl -u wechat-mp-formatter -f` |
| Docker | `docker logs -f wx-mp-studio` |

服务日志格式很简洁，每次请求一行：`[21:14:03] "POST /api/convert HTTP/1.1" 200 -`。

#### 常见问题

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| 浏览器打不开页面 | 服务没起来 / 端口写错 | 先 `curl -s http://127.0.0.1:8765/api/health` 确认 |
| 从别的机器访问不了 | 服务只监听 127.0.0.1（这是默认且正确的） | 走 Nginx 反向代理，不要改成 0.0.0.0 |
| 页面能开但一片空白 | 直接打开了 `assets/web/index.html` 文件（`file://` 协议，接口调不通） | 必须通过 `http://主机:端口/` 访问 |
| 上传 Word 报 413 | Nginx 限制太小 | `client_max_body_size 32m;` 然后 reload |
| 上传提示「内容过大」 | 超过服务端 24 MB 上限 | 精简文档，或把图片从 Word 里去掉后重传 |
| 「复制全文」点了没反应 | 非安全上下文（HTTP + IP 访问） | 配 HTTPS；或手动选中预览区内容复制 |
| 页面提示「服务未响应」 | 后台服务挂了 | 看日志，`systemctl restart` 一次 |
| 端口被占用 | 8765 已有别的进程 | 服务会自动往后试到 8780，看终端打印的实际地址；或显式指定 `--port` |

#### 手工冒烟测试（部署后建议跑一次）

在服务器上直接验证核心链路，不依赖浏览器：

```bash
cd /opt/ai-wechat-docs
S=wechat-mp-formatter

# 1) 命令行转换示例文章
python3 $S/scripts/convert.py $S/assets/sample.md -o /tmp/smoke.html --theme blue
# 期望：JSON 报告里 "ok": true，并生成 /tmp/smoke.html

# 2) 合规自检
python3 $S/scripts/check_html.py /tmp/smoke.html
# 期望：✅ 没有会导致粘贴失败的问题

# 3) 接口连通性
curl -s http://127.0.0.1:8765/api/health
curl -s http://127.0.0.1:8765/api/themes | head -c 200
```

### 卸载

```bash
# systemd
sudo systemctl disable --now wechat-mp-formatter
sudo rm /etc/systemd/system/wechat-mp-formatter.service
sudo systemctl daemon-reload
sudo rm -rf /opt/ai-wechat-docs
sudo userdel wxmp

# Docker
docker compose down --rmi local
docker rmi wx-mp-studio:latest

# Nginx
sudo rm /etc/nginx/conf.d/wxmp.conf
sudo nginx -t && sudo systemctl reload nginx
```

服务本身不落任何数据库、不写用户目录，删掉代码目录就等于彻底清理干净。

### 资源占用与并发

| 指标 | 实测/预期 |
| --- | --- |
| 常驻内存 | 约 30 MB |
| 单次转换耗时 | 2–20 ms（普通文章） |
| 代码体积 | 约 270 KB（15 个文件，约 3500 行 Python，无第三方依赖） |
| 并发模型 | `ThreadingHTTPServer`，请求间无共享状态，可安全并发 |
| 磁盘写入 | 仅 `/tmp`，请求结束即清理 |

这是个轻量工具，单核 512 MB 的小机器完全够用。
需要限制资源时，systemd 单元里的 `MemoryMax` / `CPUQuota` / `TasksMax` 已经给了保守值，可直接改。

### 上线安全检查清单

部署完成后照着过一遍：

- [ ] 服务监听的是 `127.0.0.1`，不是 `0.0.0.0`
- [ ] 防火墙 / 云安全组**没有**放行 8765
- [ ] 对外访问走的是 Nginx，且启用了 `auth_basic` 或 IP 白名单
- [ ] 已配置 HTTPS 证书（同时能让「复制全文」走完整剪贴板 API）
- [ ] Nginx 配了 `client_max_body_size 32m`
- [ ] 服务以低权限用户运行（systemd 的 `User=wxmp` / Docker 的 `USER appuser`）
- [ ] 代码目录对服务用户是只读的
- [ ] 已跑通〈手工冒烟测试〉的三步
- [ ] 清楚这个服务没有任何认证，因此不打算把它裸奔在公网上

---

## 目录结构

```
ai-wechat-docs/
├── README.md                       本文件（含服务器部署指南）
├── AGENTS.md                       给 AI 助手 / 后续迭代的工作手册（铁律、验证方式、已知坑）
├── start.sh                        启动脚本（macOS / Linux）
├── 公众号排版工作台.command          macOS 双击启动
├── install.sh                      安装 / 同步为 WorkBuddy 技能
├── Dockerfile                      容器镜像（无需 pip install）
├── docker-compose.yml              一键编排
├── .dockerignore                   构建上下文过滤（构建更快、不带进缓存垃圾）
├── .gitignore                      macOS / Python 缓存 / 转换产物 过滤规则
├── dev/                            开发用工具（零依赖）
│   ├── regression.py               回归测试：语法 / 结构红线 / 列表编号序列 / 组合矩阵
│   ├── shot.mjs                    无依赖 CDP 工具：截图、点按钮、传文件、读 DOM
│   └── steps.example.json          shot.mjs 的示例步骤
├── deploy/
│   ├── wechat-mp-formatter.service systemd 常驻服务单元
│   └── nginx.conf.example          反向代理 + 访问控制示例
├── examples/
│   └── 公众号排版示例.wechat.html    成品效果（浏览器打开点「复制全文」试试）
└── wechat-mp-formatter/            ← 技能本体 / 核心代码
    ├── SKILL.md
    ├── scripts/
    │   ├── server.py              本地 Web 服务（零依赖 HTTP）
    │   ├── convert.py             命令行转换入口
    │   ├── check_html.py          粘贴前合规自检
    │   ├── mdparser.py            Markdown → AST
    │   ├── docxreader.py          Word → AST（zipfile + ElementTree）
    │   ├── renderer.py            AST → 全内联样式 HTML
    │   ├── highlighter.py         语法高亮
    │   └── preview.py             生成带复制按钮的预览页
    ├── assets/
    │   ├── sample.md              示例文章
    │   └── web/                   工作台前端
    └── references/
        ├── wechat-editor-rules.md 微信编辑器兼容规则详表
        └── troubleshooting.md     排错清单
```

## 与 WorkBuddy 技能的关系

`wechat-mp-formatter/` 同时也是一个 WorkBuddy 技能包。为了让 AI 助手能自动识别并调用它，
需要把这份代码同步到技能目录：

```bash
./install.sh
# 等价于同步到 ~/.workbuddy/skills/wechat-mp-formatter/
```

**本项目目录是唯一源码位置，技能目录是安装产物。** 改代码请改这里，改完跑一次 `./install.sh`，
避免两边内容漂移。同步后重启 WorkBuddy 会话即可生效，之后直接说「把这篇 md 排版成公众号文章」就会被触发。

如果只在服务器上使用，这一步可以跳过 —— 服务器只需要 `wechat-mp-formatter/` 里的代码。

## 常用参数

```
--theme          green（默认 青竹绿）| blue | purple | red | orange | classic 文章配色
--code-theme     one-dark|monokai|dracula|github-light|xcode 代码配色
--font-size      正文字号 px，12 ~ 20，默认 16（移动端最佳阅读字号）  其余元素按比例自动推导
--line-numbers   代码块显示行号
--code-mode      block（默认，长行自动折行）| scroll（不折行，横向滚动）
--heading-style  modern（默认）| simple
--divider        dots|line|gradient
--link-mode      keep（默认）| text | strip
--image-mode     embed（默认）| keep | drop
--title / --author / --date / --footer-text
```

## 已知限制

- **图片必须手动上传**：微信公众号不接收本地路径和 base64 图片，需在后台素材库上传后替换。
  工具会把正文里所有待处理的图片列出来。
- **Word 的代码块靠格式识别**：Word 没有「代码块」概念，本项目按等宽字体
  （Consolas / Monaco / Menlo 等）或样式名含「代码」来判定；建议写稿时把代码段设为 Consolas。
  用「整段 + 软换行（Shift+Enter）」写的代码也能正确还原成多行。
- 公式（OMML）、艺术字、SmartArt、复杂分栏无法可靠还原，建议改用 Markdown。
- 公众号正文不能放可点击的外部链接，正文里的 URL 建议用 `--link-mode text` 明文写出。
