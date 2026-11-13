#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公众号排版工作台 · 本地 Web 服务（零第三方依赖）

启动：
    python3 server.py                # 默认 http://127.0.0.1:8765
    python3 server.py --port 9000 --no-open

能力：
    · 上传 / 粘贴 Markdown、上传 Word(.docx)
    · 实时转换 + 手机尺寸预览
    · 一键复制富文本（直接粘到公众号编辑器）
    · 下载「可复制页面」：带复制按钮，存下来可以随时打开再复制
    · 粘贴前合规自检（违反微信限制的地方直接标出来）

接口：
    GET  /                     工作台页面
    GET  /app.css  /app.js     静态资源
    GET  /api/themes           可选主题列表
    GET  /api/sample           内置示例 Markdown
    POST /api/convert          {source, markdown|docx_b64, options, meta} -> 片段 HTML + 统计 + 自检
    POST /api/export/preview   导出完整可复制页面（下载）
    POST /api/export/fragment  导出纯正文片段（下载）
"""

import argparse
import base64
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import check_html  # noqa: E402
import mdparser  # noqa: E402
import docxreader  # noqa: E402
import preview as preview_mod  # noqa: E402
from renderer import ARTICLE_THEMES, DEFAULT_THEME, Renderer  # noqa: E402
from highlighter import CODE_THEMES, DEFAULT_CODE_THEME  # noqa: E402

MAX_BODY = 24 * 1024 * 1024          # 单次请求上限 24MB（base64 后约等于 18MB 文件）
WEB_DIR = os.path.join(SKILL_DIR, "assets", "web")
SAMPLE_PATH = os.path.join(SKILL_DIR, "assets", "sample.md")
RE_IMG_SRC = re.compile(r'<img\s[^>]*?src="([^"]+)"', re.S)

OPTION_KEYS = {
    "theme": str, "code_theme": str, "line_numbers": bool, "code_mode": str,
    "heading_style": str, "divider": str, "link_mode": str, "flat_tags": bool,
    "code_chrome": bool, "lang_label": bool, "font_size": int,
}


# --------------------------------------------------------------------------
# 转换核心
# --------------------------------------------------------------------------

def _build_warnings(stats, source, images_meta=None):
    w = []
    if source == "docx":
        w.append("Word 里的代码块靠等宽字体（Consolas 等）或「代码」样式识别，本次识别到 %d 段。"
                 "若某段没被识别成代码块，请在 Word 里给它设置等宽字体后重新上传。"
                 % stats.get("code_blocks", 0))
    broken = stats.get("broken_images") or []
    if broken:
        w.append("有 %d 张图片用的是本地/相对路径，服务器上取不到，粘贴到公众号后会裂图；"
                 "请先在公众号后台上传图片再替换。" % len(broken))
    data_imgs = stats.get("data_images") or 0
    if data_imgs:
        w.append("有 %d 张内嵌(base64)图片，微信不会接收，正式发布前需上传素材库替换。" % data_imgs)
    remote = stats.get("remote_images") or []
    if remote:
        w.append("有 %d 张外链图片，微信可能自动转存，也可能裂图，建议手动上传。" % len(remote))
    if images_meta:
        w.append("已从 Word 中提取 %d 张内嵌图片。" % len(images_meta))
    if stats.get("code_blocks", 0) == 0 and stats.get("words", 0) > 300:
        w.append("这篇正文里没有识别到代码块。如果原文有代码，请检查围栏标注（```语言）或 Word 里的等宽字体设置。")
    return w


def convert_payload(payload):
    """把前端传来的请求体转成完整的转换结果。"""
    source = (payload.get("source") or "md").lower()
    options = payload.get("options") or {}
    meta = payload.get("meta") or {}

    opts = {}
    for k, caster in OPTION_KEYS.items():
        if k not in options:
            continue
        v = options[k]
        try:
            opts[k] = caster(v)
        except (TypeError, ValueError):
            continue

    images_meta = []
    tmpdir = None
    started = time.time()
    try:
        if source == "docx":
            b64 = payload.get("docx_b64") or ""
            if not b64:
                return {"ok": False, "error": "没有收到 Word 文件内容"}
            try:
                raw = base64.b64decode(b64, validate=False)
            except Exception:
                return {"ok": False, "error": "Word 文件解码失败，请重新上传"}
            if not raw.startswith(b"PK"):
                return {"ok": False, "error": "这不是有效的 .docx 文件。"
                                  "若你上传的是旧版 .doc，请在 Word 里另存为 .docx；"
                                  "若是加密文档，请先取消密码保护"}
            tmpdir = tempfile.mkdtemp(prefix="wxmp_")
            docx_path = os.path.join(tmpdir, "input.docx")
            with open(docx_path, "wb") as f:
                f.write(raw)
            blocks, images_meta = docxreader.read_docx(
                docx_path, image_dir=os.path.join(tmpdir, "images"))
        else:
            text = payload.get("markdown") or ""
            blocks = mdparser.parse_markdown(text)

        renderer = Renderer(theme=opts.get("theme", DEFAULT_THEME),
                            code_theme=opts.get("code_theme") or None,
                            opts=opts)
        body = renderer.render(blocks, meta=meta)
        stats = dict(renderer.stats)

        srcs = RE_IMG_SRC.findall(body)
        stats["data_images"] = sum(1 for s in srcs if s.startswith("data:"))
        stats["remote_images"] = [s for s in srcs if s.startswith(("http://", "https://", "//"))]
        stats["broken_images"] = [s for s in srcs
                                  if not s.startswith(("http://", "https://", "//", "data:"))]
        stats["images"] = len(srcs)
        stats["html_kb"] = round(len(body.encode("utf-8")) / 1024.0, 1)
        stats["cost_ms"] = int((time.time() - started) * 1000)
        # 与 preview.build_preview 的提示逻辑对齐
        local_list = list(stats["broken_images"])
        if stats["data_images"]:
            local_list.append("内嵌图片 × %d（需上传素材库）" % stats["data_images"])
        stats["local_images"] = local_list

        warnings = _build_warnings(stats, source, images_meta)
        report = check_html.check(body)
        return {
            "ok": True,
            "source": source,
            "body_html": body,
            "stats": stats,
            "warnings": warnings,
            "check": report,
        }
    except ValueError as exc:
        # 我们自己抛的业务错误：文案本来就是写给用户看的，
        # 不要再加 "ValueError: " 这种类型前缀（看起来像崩了，实际只是格式不对）
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # 意外错误：日志留全量堆栈，前端只说人话
        traceback.print_exc()
        print("[convert] 未预期的错误：%s" % exc, file=sys.stderr, flush=True)
        return {"ok": False, "error": "转换失败（%s）。详细信息已打印在服务端日志里，可以贴给我排查"
                                      % type(exc).__name__}
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


# --------------------------------------------------------------------------
# HTTP 服务
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "WxMpStudio/1.0"
    protocol_version = "HTTP/1.1"

    # ---------------- 基础工具 ----------------
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _static(self, name, ctype):
        path = os.path.join(WEB_DIR, name)
        if not os.path.isfile(path):
            return self._json({"ok": False, "error": "缺少静态资源 %s" % name}, 500)
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, "请求头异常"
        if length <= 0:
            return {}, None
        if length > MAX_BODY:
            return None, "内容过大（上限约 18MB 文件）"
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8")), None
        except Exception:
            return None, "请求体不是合法 JSON"

    def log_message(self, fmt, *args):  # 精简日志
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    # ---------------- GET ----------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._static("index.html", "text/html; charset=utf-8")
        if path == "/app.css":
            return self._static("app.css", "text/css; charset=utf-8")
        if path == "/app.js":
            return self._static("app.js", "application/javascript; charset=utf-8")
        if path == "/favicon.ico":
            return self._send(204, b"")
        if path == "/api/health":
            return self._json({"ok": True, "service": "wx-mp-studio"})
        if path == "/api/themes":
            return self._json({
                "ok": True,
                "articles": {k: v["label"] for k, v in ARTICLE_THEMES.items()},
                "codes": {k: v["label"] for k, v in CODE_THEMES.items()},
                # 每个文章主题推荐的代码配色，供前端做「跟随主题」联动
                "code_of": {k: v.get("code_theme", DEFAULT_CODE_THEME)
                            for k, v in ARTICLE_THEMES.items()},
                "defaults": {"theme": DEFAULT_THEME, "code_theme": DEFAULT_CODE_THEME},
            })
        if path == "/api/sample":
            try:
                with open(SAMPLE_PATH, "r", encoding="utf-8") as f:
                    return self._json({"ok": True, "markdown": f.read()})
            except OSError as exc:
                return self._json({"ok": False, "error": str(exc)}, 500)
        return self._json({"ok": False, "error": "未找到 %s" % path}, 404)

    # ---------------- POST ----------------
    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/convert", "/api/export/preview", "/api/export/fragment"):
            return self._json({"ok": False, "error": "未找到 %s" % path}, 404)

        payload, err = self._read_json()
        if err:
            return self._json({"ok": False, "error": err}, 413 if "过大" in err else 400)

        if path == "/api/convert":
            return self._json(convert_payload(payload))

        # 导出：直接返回文件流，前端用 blob 下载
        body = payload.get("body_html") or ""
        if not body.strip():
            return self._json({"ok": False, "error": "没有内容可导出"}, 400)
        meta = payload.get("meta") or {}
        stats = payload.get("stats") or {}
        name = _safe_name(meta.get("title") or payload.get("filename") or "公众号文章")

        if path.endswith("preview"):
            fd, tmp = tempfile.mkstemp(suffix=".html")
            os.close(fd)
            preview_mod.build_preview(body, stats, meta, tmp)
            with open(tmp, "rb") as f:
                data = f.read()
            os.unlink(tmp)
            return self._send(200, data, "text/html; charset=utf-8",
                              {"Content-Disposition": _disposition(name + ".wechat.html")})
        fd, tmp = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        preview_mod.build_fragment(body, meta, tmp)
        with open(tmp, "rb") as f:
            data = f.read()
        os.unlink(tmp)
        return self._send(200, data, "text/html; charset=utf-8",
                          {"Content-Disposition": _disposition(name + ".fragment.html")})


def _disposition(filename):
    """HTTP 头只能是 latin-1，中文文件名需按 RFC 5987 编码，并给 ASCII 兜底名。"""
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_") or "article.html"
    return "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (fallback, quote(filename))


def _safe_name(name):
    name = re.sub(r"[\\/:*?\"<>|\s]+", "-", str(name)).strip("-")
    return (name or "公众号文章")[:60]


def main(argv=None):
    ap = argparse.ArgumentParser(description="公众号排版工作台（本地 Web 服务）")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机可访问）")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args(argv)

    if not os.path.isdir(WEB_DIR):
        print("找不到界面资源目录：%s" % WEB_DIR, file=sys.stderr)
        return 1

    httpd = None
    port = args.port
    for _ in range(12):
        try:
            httpd = ThreadingHTTPServer((args.host, port), Handler)
            break
        except OSError:
            port += 1
    if httpd is None:
        print("端口 %d 起不来，请用 --port 指定其他端口" % args.port, file=sys.stderr)
        return 1

    url = "http://%s:%d/" % (args.host, port)
    # flush：部署时日志常被重定向到文件或被 systemd 接管，不加 flush 会看不到启动信息
    print("✅ 公众号排版工作台已启动：%s" % url, flush=True)
    if port != args.port:
        # 端口被占用时前面会自动顺延，但**必须说清楚**：
        # 否则用户以为还在 8765，实际新实例在 8766，看到的页面是旧进程提供的
        # （表现为"改完代码重启了却没生效"）
        print("   ⚠️ 端口 %d 已被占用，本次改用 %d。若这不是你要的，"
              "先停掉占用进程或用 --port 指定端口。" % (args.port, port), file=sys.stderr, flush=True)
    print("   停止服务按 Ctrl+C", flush=True)
    if args.host not in ("127.0.0.1", "localhost"):
        print("   ⚠️ 正在监听 %s：本服务没有任何访问认证，请确保前面有防火墙或反向代理保护"
              % args.host, file=sys.stderr, flush=True)
    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
