#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「预览 + 一键复制」页面。

预览页本身只是给浏览器看的（不是粘贴对象），所以可以自由使用 <style>/class/JS；
被复制的内容永远是 #mp-content 的 innerHTML，也就是 renderer 产出的全内联样式片段。
"""

import json
import os

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ · 公众号排版预览</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0; background: #f4f5f7; color: #23272e;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif;
  }
  .bar {
    position: sticky; top: 0; z-index: 99; display: flex; flex-wrap: wrap; gap: 10px;
    align-items: center; padding: 12px 18px; background: #fff;
    border-bottom: 1px solid #e6e8eb; box-shadow: 0 1px 6px rgba(0,0,0,.04);
  }
  .bar h1 { margin: 0 12px 0 0; font-size: 15px; font-weight: 600; white-space: nowrap; }
  .bar .spacer { flex: 1; }
  button {
    border: 1px solid #dcdfe6; background: #fff; color: #303133; cursor: pointer;
    padding: 7px 14px; border-radius: 6px; font-size: 13px; transition: .15s;
    font-family: inherit;
  }
  button:hover { border-color: #07c160; color: #07c160; }
  button.primary { background: #07c160; border-color: #07c160; color: #fff; }
  button.primary:hover { background: #06ad56; color: #fff; }
  .meta { font-size: 12px; color: #909399; margin-right: 4px; }
  .stage { display: flex; justify-content: center; padding: 26px 14px 60px; }
  .phone {
    background: #fff; width: 750px; max-width: 100%; padding: 34px 22px;
    border-radius: 10px; box-shadow: 0 6px 28px rgba(0,0,0,.07);
  }
  /* 手机视图按 iPhone 18 Pro 的 CSS 视口宽度 402px，左右内边距 20px，
     正文可用宽度 362px —— 与工作台里的真机预览保持一致，折行位置才对得上 */
  .phone.narrow { width: 402px; padding: 30px 20px; }
  .notice {
    margin: 0 0 18px; padding: 12px 14px; border-radius: 8px; font-size: 13px;
    line-height: 1.7; background: #fff7e6; border: 1px solid #ffe0a3; color: #8a5a00;
  }
  .notice code { background: #fff; padding: 1px 5px; border-radius: 3px; font-size: 12px; }
  .notice ul { margin: 8px 0 0; padding-left: 20px; }
  .hidden { display: none !important; }
  #toast {
    position: fixed; left: 50%; bottom: 40px; transform: translateX(-50%) translateY(20px);
    background: #23272e; color: #fff; padding: 11px 22px; border-radius: 8px; font-size: 14px;
    opacity: 0; pointer-events: none; transition: .25s; z-index: 999;
  }
  #toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
  .tip { text-align: center; color: #a8abb2; font-size: 12px; margin-top: 22px; }
</style>
</head>
<body>
<div class="bar">
  <h1>公众号排版预览</h1>
  <span class="meta">__STATS__</span>
  <span class="spacer"></span>
  <button class="primary" onclick="copyRich()">复制全文（推荐）</button>
  <button onclick="toggleHome()">手机视图</button>
</div>

<div class="stage">
  <div class="phone" id="phone">
    __NOTICE__
    <div id="mp-content">
__BODY__
    </div>
    <p class="tip">选中正文 → 复制，或点击顶部「复制全文」按钮，然后到公众号后台编辑器粘贴</p>
  </div>
</div>

<div id="toast"></div>
<script>
var noticeList = {};

function toast(msg) {
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(function () { t.classList.remove('show'); }, 2200);
}

function copyRich() {
  var el = document.getElementById('mp-content');
  var html = el.innerHTML;
  if (navigator.clipboard && window.ClipboardItem) {
    var item = new ClipboardItem({
      'text/html': new Blob([html], { type: 'text/html' }),
      'text/plain': new Blob([el.innerText], { type: 'text/plain' })
    });
    navigator.clipboard.write([item]).then(function () {
      toast('已复制，去公众号编辑器粘贴即可');
    }, function () { legacyCopy(html); });
  } else {
    legacyCopy(html);
  }
}

function legacyCopy(html) {
  var holder = document.createElement('div');
  holder.innerHTML = html;
  holder.style.position = 'fixed';
  holder.style.left = '-9999px';
  holder.style.top = '0';
  document.body.appendChild(holder);
  var range = document.createRange();
  range.selectNodeContents(holder);
  var sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  var ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  sel.removeAllRanges();
  document.body.removeChild(holder);
  toast(ok ? '已复制，去公众号编辑器粘贴即可' : '复制失败，请手动选中正文后 Ctrl/Cmd+C');
}

function toggleHome() {
  document.getElementById('phone').classList.toggle('narrow');
}

document.addEventListener('keydown', function (e) {
  if ((e.metaKey || e.ctrlKey) && e.shiftKey && (e.key === 'C' || e.key === 'c')) {
    e.preventDefault(); copyRich();
  }
});
</script>
</body>
</html>
"""

FRAGMENT_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>__TITLE__（可粘贴片段）</title></head>
<body style="max-width:750px;margin:0 auto;padding:20px">
__BODY__
</body>
</html>
"""


def build_preview(body_html: str, stats: dict, meta: dict, out_path: str) -> str:
    title = meta.get("title") or "文章"
    stat_bits = ["正文字数 %d" % stats.get("words", 0),
                 "代码块 %d" % stats.get("code_blocks", 0),
                 "表格 %d" % stats.get("tables", 0),
                 "图片 %d" % stats.get("images", 0)]
    stats_str = " · ".join(stat_bits)

    local_imgs = stats.get("local_images") or []
    remote_imgs = stats.get("remote_images") or []
    notice = ""
    msgs = []
    if local_imgs:
        msgs.append(
            "本文含 <b>%d 张本地图片</b>，预览已用 base64 显示，但<b>微信不会接收 base64</b>。"
            "粘贴前请在公众号后台「图片」里上传这些图片，或用原文自上而下替换对应位置的图片："
            % len(local_imgs))
        msgs.append("<ul>" + "".join("<li><code>%s</code></li>" % os.path.basename(p)
                                     for p in local_imgs[:20]) + "</ul>")
    if remote_imgs:
        msgs.append("含 %d 张外链图片（%s），微信通常会尝试自动抓取转存；若粘贴后裂图，请手动上传。"
                    % (len(remote_imgs), ", ".join(os.path.basename(x) for x in remote_imgs[:3])))
    if msgs:
        notice = '<div class="notice">%s</div>' % "".join(msgs)

    page = (PAGE
            .replace("__TITLE__", title)
            .replace("__STATS__", stats_str)
            .replace("__NOTICE__", notice)
            .replace("__BODY__", body_html))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)
    return out_path


def build_fragment(body_html: str, meta: dict, out_path: str) -> str:
    page = FRAGMENT_PAGE.replace("__TITLE__", meta.get("title") or "文章").replace("__BODY__", body_html)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)
    return out_path


def write_report(report: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
