// dev/shot.mjs —— 无依赖的浏览器验证工具（截图 / 点按钮 / 传文件 / 读 DOM）
//
// 为什么需要它：排版好不好看、手机预览对不对，命令行断言看不出来，必须真的渲染一遍。
// 这个脚本用裸 CDP（Chrome DevTools Protocol）驱动一个 headless Chrome/Chromium，
// 不装 puppeteer / playwright 包 —— 和项目本身一样零依赖。
//
//   # 1) 自己拉起浏览器并跑步骤（会从 playwright 缓存里自动找 chrome-headless-shell）
//   node dev/shot.mjs --launch --url http://127.0.0.1:8765/ --steps dev/steps.example.json
//
//   # 2) 连接一个已经开着的调试端口（自己起浏览器时加 --remote-debugging-port=9333）
//   node dev/shot.mjs --port 9333 --steps dev/steps.example.json
//
// 步骤（JSON 数组，每项都是可选的组合）：
//   { "name": "说明", "url": "https://…" }              导航
//   { "name": "说明", "setEditor": "文章.md" }           把文件读进来塞进 #editor 并触发实时转换
//   { "name": "说明", "eval": "(()=>…)()" }              执行 JS，返回值会打印（便于断言）
//   { "name": "说明", "setFile": {"selector": "#fileInput", "path": "a.docx"} }
//   { "name": "说明", "wait": 1200 }                     等待
//   { "name": "说明", "shot": "名字" }                   整页截图 → <out>/名字.png
//   { "name": "说明", "clipShot": {"selector": ".phone-status", "scale": 4, "name": "状态栏"} }
//                                                       把某个元素克隆到浮层里放大后截图
//                                                       （元素被 overflow:hidden 裁掉时用这个）
//
// 退出码：所有步骤跑完为 0；步骤抛错为 1。

import http from 'node:http';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';

const argv = process.argv.slice(2);
const arg = (k, d) => {
  const i = argv.indexOf('--' + k);
  return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[i + 1] : d;
};
const flag = (k) => argv.includes('--' + k);

const PORT = Number(arg('port', 9333));
const OUT = arg('out', 'dev/shots');
const URL_ = arg('url', null);
const STEPS_FILE = arg('steps', null);
const CHROME = arg('chrome', null);
const RELOAD = !flag('no-reload');

fs.mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- CDP 客户端

function getJson(p) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port: PORT, path: p }, (res) => {
      let b = '';
      res.on('data', (c) => (b += c));
      res.on('end', () => { try { resolve(JSON.parse(b)); } catch (e) { reject(e); } });
    }).on('error', reject);
  });
}

class CDP {
  constructor() { this.seq = 0; this.pending = new Map(); this.buf = Buffer.alloc(0); }
  connect(wsUrl) {
    const u = new URL(wsUrl);
    return new Promise((resolve, reject) => {
      const key = crypto.randomBytes(16).toString('base64');
      const req = http.request({
        host: u.hostname, port: u.port, path: u.pathname + u.search,
        headers: { Connection: 'Upgrade', Upgrade: 'websocket',
                   'Sec-WebSocket-Key': key, 'Sec-WebSocket-Version': '13' },
      });
      req.on('upgrade', (_res, socket) => {
        this.socket = socket;
        socket.on('data', (d) => this._onData(d));
        socket.on('error', reject);
        resolve();
      });
      req.on('error', reject);
      req.end();
    });
  }
  _onData(d) {
    this.buf = Buffer.concat([this.buf, d]);
    for (;;) {
      const b = this.buf;
      if (b.length < 2) return;
      const op = b[0] & 0x0f;
      const masked = (b[1] & 0x80) !== 0;
      let len = b[1] & 0x7f, off = 2;
      if (len === 126) { if (b.length < 4) return; len = b.readUInt16BE(2); off = 4; }
      else if (len === 127) { if (b.length < 10) return; len = Number(b.readBigUInt64BE(2)); off = 10; }
      let mask = null;
      if (masked) { if (b.length < off + 4) return; mask = b.subarray(off, off + 4); off += 4; }
      if (b.length < off + len) return;
      let payload = b.subarray(off, off + len);
      if (masked) {
        const p = Buffer.from(payload);
        for (let i = 0; i < p.length; i++) p[i] ^= mask[i % 4];
        payload = p;
      }
      this.buf = b.subarray(off + len);
      if (op === 0x8) { this.closed = true; continue; }
      if (op === 0x1) {
        try {
          const obj = JSON.parse(payload.toString('utf8'));
          if (obj.id && this.pending.has(obj.id)) {
            this.pending.get(obj.id)(obj);
            this.pending.delete(obj.id);
          }
        } catch { /* 本工具的消息都很小，忽略异常帧 */ }
      }
    }
  }
  send(method, params = {}) {
    const id = ++this.seq;
    const data = Buffer.from(JSON.stringify({ id, method, params }), 'utf8');
    const mask = crypto.randomBytes(4);
    let header;
    if (data.length < 126) header = Buffer.from([0x81, 0x80 | data.length]);
    else if (data.length < 65536) {
      header = Buffer.alloc(4); header[0] = 0x81; header[1] = 0x80 | 126;
      header.writeUInt16BE(data.length, 2);
    } else {
      header = Buffer.alloc(10); header[0] = 0x81; header[1] = 0x80 | 127;
      header.writeBigUInt64BE(BigInt(data.length), 2);
    }
    const p = Buffer.from(data);
    for (let i = 0; i < p.length; i++) p[i] ^= mask[i % 4];
    this.socket.write(Buffer.concat([header, mask, p]));
    return new Promise((resolve) => this.pending.set(id, resolve));
  }
}

// ---------------------------------------------------------------- 浏览器

function findChrome() {
  if (CHROME) return CHROME;
  const base = path.join(process.env.HOME || '', 'Library/Caches/ms-playwright');
  if (fs.existsSync(base)) {
    for (const dir of fs.readdirSync(base)) {
      const p = path.join(base, dir);
      if (!dir.startsWith('chromium')) continue;
      for (const sub of fs.readdirSync(p)) {
        const bin = path.join(p, sub, 'chrome-headless-shell');
        if (fs.existsSync(bin)) return bin;
      }
    }
  }
  return null;
}

async function launchChrome(url) {
  const bin = findChrome();
  if (!bin) {
    console.error('没找到 chrome-headless-shell，请用 --chrome <路径> 指定，或自己起浏览器加 --remote-debugging-port=' + PORT);
    process.exit(2);
  }
  const args = [
    '--headless',
    // 在受限 shell / 沙箱里跑时，Chrome 自己的 sandbox 起不来（GPU 进程会 fatal），
    // 所以这两个开关是必须的；它只在本地开发用的临时实例上生效。
    '--no-sandbox', '--disable-gpu', '--disable-gpu-sandbox', '--disable-software-rasterizer',
    '--remote-debugging-port=' + String(PORT),
    '--user-data-dir=' + fs.mkdtempSync('/tmp/wxmp-chrome-'),
    '--window-size=1440,1200', '--no-first-run', '--hide-scrollbars',
  ];
  if (url) args.push(url);
  console.log('启动浏览器：' + bin);
  const child = spawn(bin, args, { stdio: 'ignore', detached: false });
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    try { await getJson('/json/version'); return child; } catch { /* 还没起来 */ }
  }
  child.kill();
  console.error('浏览器 30 秒内没起来');
  process.exit(2);
}

// ---------------------------------------------------------------- 步骤

async function main() {
  let chrome = null;
  if (flag('launch')) chrome = await launchChrome(URL_);

  const targets = await getJson('/json/list');
  const page = targets.find((t) => t.type === 'page');
  if (!page) { console.error('找不到页面目标'); process.exit(2); }

  const cdp = new CDP();
  await cdp.connect(page.webSocketDebuggerUrl);
  for (const m of ['Runtime.enable', 'Page.enable', 'Network.enable', 'DOM.enable']) await cdp.send(m);
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
  if (RELOAD) { await cdp.send('Page.reload', { ignoreCache: true }); await sleep(2000); }

  const evaluate = async (expr) => {
    const r = await cdp.send('Runtime.evaluate',
      { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result && r.result.exceptionDetails) {
      throw new Error('eval 抛错: ' + JSON.stringify(r.result.exceptionDetails).slice(0, 200));
    }
    return r.result && r.result.result ? r.result.result.value : undefined;
  };

  const selectNode = async (selector) => {
    const doc = await cdp.send('DOM.getDocument', { depth: 1 });
    const q = await cdp.send('DOM.querySelector', { nodeId: doc.result.root.nodeId, selector });
    if (!q.result || !q.result.nodeId) throw new Error('找不到元素: ' + selector);
    return q.result.nodeId;
  };

  const shot = async (name) => {
    const r = await cdp.send('Page.captureScreenshot', { format: 'png' });
    const file = path.join(OUT, name + '.png');
    fs.writeFileSync(file, Buffer.from(r.result.data, 'base64'));
    console.log('    截图 -> ' + file);
  };

  const steps = STEPS_FILE ? JSON.parse(fs.readFileSync(STEPS_FILE, 'utf8')) : [];
  if (!steps.length) console.log('（没有步骤，只做了页面加载）');

  for (const st of steps) {
    const label = st.name || '(未命名)';
    try {
      if (st.url) await evaluate('location.href=' + JSON.stringify(st.url));
      if (st.setEditor) {
        const md = fs.readFileSync(st.setEditor, 'utf8');
        const v = await evaluate(
          '(()=>{const e=document.getElementById("editor");if(!e)return "没有 #editor";'
          + 'e.readOnly=false;e.value=' + JSON.stringify(md) + ';'
          + 'e.dispatchEvent(new Event("input",{bubbles:true}));return e.value.length;})()');
        console.log('  [%s] 写入编辑器 %s 字', label, v);
      }
      if (st.setFile) {
        const id = await selectNode(st.setFile.selector);
        await cdp.send('DOM.setFileInputFiles', { nodeId: id, files: [st.setFile.path] });
        console.log('  [%s] 上传 %s', label, st.setFile.path);
      }
      if (st.eval) {
        const v = await evaluate(st.eval);
        if (v !== undefined) console.log('  [%s] => %s', label, JSON.stringify(v));
        else console.log('  [%s] (eval 无返回值)', label);
      }
      await sleep(st.wait || 500);
      if (st.shot) { await shot(st.shot); }
      if (st.clipShot) {
        const { selector, scale = 4, name } = st.clipShot;
        // 元素常常被 overflow:hidden 裁掉（比如手机屏幕里的状态栏），
        // 所以不能直接给本体加 scale —— 克隆一份塞进 fixed 浮层里再放大。
        // 尺寸用 offsetWidth/offsetHeight（布局尺寸），不用 getBoundingClientRect：
        // 后者会把祖先的 transform: scale 算进去，克隆出来的宽高就错了。
        const res = await evaluate(
          '(()=>{const old=document.getElementById("__clip");if(old)old.remove();'
          + 'const src=document.querySelector(' + JSON.stringify(selector) + ');'
          + 'if(!src)return "找不到";'
          + 'const w=src.offsetWidth,h=src.offsetHeight;'
          + 'const box=document.createElement("div");box.id="__clip";'
          + 'box.style.cssText="position:fixed;left:0;top:0;z-index:2147483647;background:#fff;'
          + 'box-shadow:0 0 0 2px #f00;overflow:hidden;width:"+w+"px;height:"+h+"px;'
          + 'transform:scale(' + scale + ');transform-origin:left top";'
          + 'const c=src.cloneNode(true);c.style.position="relative";'
          + 'box.appendChild(c);document.body.appendChild(box);return w+"x"+h;})()');
        if (res === '找不到') throw new Error('clipShot 找不到元素: ' + selector);
        console.log('  [%s] 克隆 %s（%s）放大 %sx', label, selector, res, scale);
        await sleep(400);
        await shot(name || 'clip');
        await evaluate('(()=>{const b=document.getElementById("__clip");if(b)b.remove();})()');
      }
    } catch (err) {
      console.error('  [%s] 失败：%s', label, err.message);
      if (chrome) chrome.kill();
      process.exit(1);
    }
  }

  cdp.socket.end();
  if (chrome) chrome.kill();
  process.exit(0);
}

main().catch((e) => { console.error(e); process.exit(1); });
