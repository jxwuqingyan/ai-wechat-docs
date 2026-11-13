/* 公众号排版工作台 · 前端逻辑（无框架、无外部依赖） */

/* id 与 CSS 选择器都支持：$('editor') 或 $('.pane-editor') */
const $ = (sel) => (sel[0] === '.' || sel[0] === '#' || sel.indexOf(' ') > -1)
  ? document.querySelector(sel)
  : document.getElementById(sel);

const SETTINGS_KEY = 'wxmp:settings:v2';   // v1 -> v2：主题色板重做，旧设置作废以启用新默认主题
const DRAFT_KEY = 'wxmp:draft';
const DRAFT_LIMIT = 400 * 1024;

  const state = {
  source: 'md',        // md | docx
  docxB64: '',
  docxName: '',
  bodyHtml: '',
  stats: {},
  check: null,
  warnings: [],
  scale: 1,            // 手机预览当前缩放比例
  codeOf: {},          // 文章主题 -> 推荐代码配色（来自 /api/themes）
  lastTheme: '',       // 用于判断代码配色是否还在「跟随主题」
  timer: null,
  seq: 0,
};

// ---------------------------------------------------------------- 工具

let toastTimer = null;
function toast(msg, ms) {
  const el = $('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  // 长文案按字数给阅读时间（约 12 字/秒），否则「请另存为 .docx」这类提示还没看清就消失了
  const dur = ms || Math.min(9000, Math.max(2200, String(msg).length * 85));
  toastTimer = setTimeout(() => el.classList.remove('show'), dur);
}

function downloadBlob(blob, filename) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

function filenameFromHeader(res, fallback) {
  const cd = res.headers.get('Content-Disposition') || '';
  const star = cd.match(/filename\*=UTF-8''([^;]+)/i);
  if (star) { try { return decodeURIComponent(star[1]); } catch (e) { /* 忽略 */ } }
  const plain = cd.match(/filename="([^"]+)"/i);
  return plain ? plain[1] : fallback;
}

function b64FromBuffer(buf) {
  const bytes = new Uint8Array(buf);
  let bin = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(bin);
}

// ---------------------------------------------------------------- 参数采集

function collectOptions() {
  return {
    theme: $('theme').value,
    code_theme: $('codeTheme').value,
    line_numbers: $('lineNumbers').checked,
    heading_style: $('headingStyle').value,
    divider: $('divider').value,
    link_mode: $('linkMode').value,
    code_mode: $('codeMode').value,
    code_chrome: $('codeChrome').checked,
    flat_tags: $('flatTags').checked,
    font_size: parseInt($('fontSize').value, 10) || 16,
  };
}

function collectMeta() {
  const val = (id) => $(id).value.trim();
  return {
    title: val('metaTitle') || null,
    author: val('metaAuthor') || null,
    date: val('metaDate') || null,
    footer: val('metaFooter') || null,
  };
}

function saveSettings() {
  try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(collectOptions())); } catch (e) { /* 忽略 */ }
}

function restoreSettings() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}'); } catch (e) { saved = {}; }
  const setSelect = (id, v) => { if (v && Array.from($(id).options).some(o => o.value === v)) $(id).value = v; };
  setSelect('theme', saved.theme);
  setSelect('codeTheme', saved.code_theme);
  setSelect('headingStyle', saved.heading_style);
  setSelect('divider', saved.divider);
  setSelect('linkMode', saved.link_mode);
  setSelect('codeMode', saved.code_mode);
  if (saved.font_size) $('fontSize').value = String(saved.font_size);
  if (typeof saved.line_numbers === 'boolean') $('lineNumbers').checked = saved.line_numbers;
  if (typeof saved.code_chrome === 'boolean') $('codeChrome').checked = saved.code_chrome;
  if (typeof saved.flat_tags === 'boolean') $('flatTags').checked = saved.flat_tags;
}

// ---------------------------------------------------------------- 转换

function scheduleConvert(delay = 420) {
  clearTimeout(state.timer);
  state.timer = setTimeout(runConvert, delay);
}

async function runConvert() {
  const seq = ++state.seq;
  const payload = { source: state.source, options: collectOptions(), meta: collectMeta() };
  if (state.source === 'docx') payload.docx_b64 = state.docxB64;
  else payload.markdown = $('editor').value;

  $('previewHint').textContent = '生成中…';
  let data;
  try {
    const res = await fetch('/api/convert', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    data = await res.json();
  } catch (e) {
    $('previewHint').textContent = '';
    return toast('服务未响应：' + e.message);
  }
  if (seq !== state.seq) return;   // 丢弃过期结果
  applyResult(data);
}

function applyResult(data) {
  if (!data.ok) {
    // 失败原因写进左侧「待处理项」面板，而不是只弹一个 2 秒的 toast：
    // 转换失败往往带着「请另存为 .docx」这种要照着做的动作，必须能停留、能选中复制。
    const msg = data.error || '未知错误';
    state.bodyHtml = '';
    state.stats = {};
    state.check = { ok: false, errors: [msg], warnings: [], images: {} };
    state.warnings = [];
    $('mpContent').innerHTML = emptyState('⚠️', '转换失败', msg);
    $('previewHint').textContent = '';
    renderStats();
    renderCheck();
    return toast('转换失败，原因见左侧「待处理项」', 3200);
  }
  state.bodyHtml = data.body_html;
  state.stats = data.stats || {};
  state.check = data.check || null;
  state.warnings = data.warnings || [];

  $('mpContent').innerHTML = data.body_html;
  renderHint();

  renderStats();
  renderCheck();
  saveDraft();
}

// 手机预览里的空状态（清空 / 转换失败共用）
function emptyState(ico, main, sub) {
  const esc = (t) => String(t).replace(/[&<>]/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[m]));
  return '<div class="empty-state"><div class="empty-ico">' + ico + '</div>'
    + '<p>' + esc(main) + '</p>'
    + (sub ? '<p class="empty-sub">' + esc(sub) + '</p>' : '') + '</div>';
}

function renderStats() {
  const s = state.stats;
  $('stWords').textContent = s.words || 0;
  $('stCode').textContent = s.code_blocks || 0;
  $('stTables').textContent = s.tables || 0;
  $('stImages').textContent = s.images || 0;
  $('stCost').textContent = s.code_lines ? ('代码 ' + s.code_lines + ' 行') : '';
  $('stCost').textContent += (s.remote_images && s.remote_images.length)
    ? ('　外链图 ' + s.remote_images.length) : '';
}

function renderCheck() {
  const badge = $('checkBadge');
  const btn = $('btnCheckDetail');
  const panel = $('checkPanel');
  const c = state.check || { ok: true, errors: [], warnings: [] };
  const errs = c.errors || [];
  const warns = (c.warnings || []).concat(state.warnings || []);
  badge.className = 'badge ' + (errs.length ? 'err' : (warns.length ? 'warn' : 'ok'));
  if (errs.length) badge.textContent = '❌ ' + errs.length + ' 个问题需修复';
  else if (warns.length) badge.textContent = '⚠️ ' + warns.length + ' 条建议';
  else badge.textContent = '✅ 合规自检通过';

  btn.hidden = !(errs.length || warns.length);
  $('checkBody').innerHTML = panelHtml(errs, warns, c);

  // 默认收起：只有出现「必须修复」的错误才自动展开提醒；
  // 仅是建议时不打扰，用户从底部徽标点「查看待处理项」再展开。
  if (errs.length) setCheckPanel(true);
  else if (!warns.length) setCheckPanel(false);
  else setCheckPanel(panel.hidden === false);   // 只有建议：保持用户当前的展开状态
}

// 自检面板展开/收起（面板在左侧编辑区下方，展开只挤压编辑区，不影响右侧预览）
function setCheckPanel(open) {
  const panel = $('checkPanel');
  const btn = $('btnCheckDetail');
  panel.hidden = !open;
  btn.textContent = open ? '收起待处理项' : '查看待处理项';
}

function toggleCheckPanel(forceOpen) {
  const panel = $('checkPanel');
  setCheckPanel(forceOpen === undefined ? panel.hidden : forceOpen);
}

function panelHtml(errs, warns, c) {
  const esc = (t) => String(t).replace(/[&<>]/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[m]));
  let html = '';
  // 转换失败时只显示原因，不要跟着报一串"图片 0 张"这种无意义的统计
  const failed = !!c && c.ok === false;
  if (errs.length) {
    html += '<h4>' + (failed ? '转换失败的原因' : '必须修复（会导致粘贴后样式丢失或裂图）') + '</h4><ul>' +
      errs.map((e) => '<li class="err-item">' + esc(e) + '</li>').join('') + '</ul>';
  }
  if (failed) return html;
  if (warns.length) {
    html += '<h4>建议处理</h4><ul>' +
      warns.map((w) => '<li class="warn-item">' + esc(w) + '</li>').join('') + '</ul>';
  }
  const imgs = (c && c.images) || {};
  html += '<h4>图片情况</h4><ul>' +
    '<li>本地/相对路径：' + ((imgs.local || []).length) + ' 张（粘贴后必裂图，需先上传素材库）</li>' +
    '<li>base64 内嵌：' + (imgs.base64 || 0) + ' 张（微信不接收，需替换）</li>' +
    '<li>外链图片：' + ((imgs.remote || []).length) + ' 张（微信可能自动转存）</li></ul>';
  if (!errs.length && !warns.length) html += '<p class="empty">没有发现任何问题，可以直接复制到公众号。</p>';
  return html;
}

// ---------------------------------------------------------------- 草稿

function saveDraft() {
  if (state.source !== 'md') return;
  const text = $('editor').value;
  if (text.length > DRAFT_LIMIT) return;
  try { localStorage.setItem(DRAFT_KEY, text); } catch (e) { /* 忽略 */ }
  $('saveHint').textContent = '草稿已自动保存';
  clearTimeout(saveDraft._t);
  saveDraft._t = setTimeout(() => { $('saveHint').textContent = ''; }, 1500);
}

// ---------------------------------------------------------------- 复制

async function copyRich() {
  if (!state.bodyHtml.trim()) return toast('还没有内容可复制');
  const el = $('mpContent');
  const html = el.innerHTML;
  if (navigator.clipboard && window.ClipboardItem) {
    try {
      await navigator.clipboard.write([new ClipboardItem({
        'text/html': new Blob([html], { type: 'text/html' }),
        'text/plain': new Blob([el.innerText], { type: 'text/plain' }),
      })]);
      return toast('已复制富文本，去公众号编辑器粘贴即可');
    } catch (e) { /* 落到兜底方案 */ }
  }
  legacyCopy(html);
}

function legacyCopy(html) {
  const holder = document.createElement('div');
  holder.innerHTML = html;
  holder.style.position = 'fixed';
  holder.style.left = '-9999px';
  document.body.appendChild(holder);
  const range = document.createRange();
  range.selectNodeContents(holder);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  sel.removeAllRanges();
  holder.remove();
  toast(ok ? '已复制，去公众号编辑器粘贴即可' : '复制失败：请手动选中预览区内容后复制');
}

// ---------------------------------------------------------------- 下载

async function download() {
  if (!state.bodyHtml.trim()) return toast('还没有内容可下载');
  try {
    const res = await fetch('/api/export/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        body_html: state.bodyHtml,
        meta: collectMeta(),
        stats: state.stats,
        filename: state.docxName || (collectMeta().title || '公众号文章'),
      }),
    });
    if (!res.ok) {
      const j = await res.json().catch(() => ({ error: res.statusText }));
      return toast('下载失败：' + (j.error || res.statusText));
    }
    const blob = await res.blob();
    downloadBlob(blob, filenameFromHeader(res, 'article.wechat.html'));
    toast('页面已保存，双击打开即可随时复制');
  } catch (e) {
    toast('下载失败：' + e.message);
  }
}

// ---------------------------------------------------------------- 文件

async function handleFiles(files) {
  const f = files && files[0];
  if (!f) return;
  const lower = f.name.toLowerCase();

  if (/\.(docx|docm)$/.test(lower)) {
    if (f.size > 18 * 1024 * 1024) return toast('Word 文件过大（上限 18MB）');
    const buf = await f.arrayBuffer();
    state.docxB64 = b64FromBuffer(buf);
    state.docxName = f.name;
    state.source = 'docx';
    const ed = $('editor');
    ed.readOnly = true;
    ed.value = '【已载入 Word 文档】' + f.name + '\n\n'
      + '· Word 里的代码块按「等宽字体（Consolas / Monaco 等）」或「代码」样式识别\n'
      + '· 若代码块没被识别，可在 Word 里把它们设成 Consolas 后重新上传\n'
      + '· 想在网页上手动改内容：点「清空」，改用 Markdown 编辑';
    updateSourceTag();
    toast('Word 已解析：' + f.name);
    runConvert();
    return;
  }

  if (/\.(doc|rtf|wps|odt|pages)$/.test(lower)) {
    return toast('不支持 ' + lower.split('.').pop().toUpperCase()
      + ' 格式，请在 Word / WPS 里另存为 .docx 再上传');
  }
  if (!/\.(md|markdown|mdown|mkd|txt)$/.test(lower)) {
    return toast('只支持 .md / .markdown / .txt / .docx / .docm 文件');
  }
  const text = await f.text();
  const ed = $('editor');
  state.source = 'md';
  state.docxName = '';
  state.docxB64 = '';
  ed.readOnly = false;
  ed.value = text;
  updateSourceTag();
  toast('已载入：' + f.name);
  scheduleConvert(60);
}

function updateSourceTag() {
  const tag = $('docxTag');
  if (state.source === 'docx') {
    tag.hidden = false;
    tag.textContent = 'Word 模式';
    $('editorHint').textContent = '当前按 Word 解析结果预览';
  } else {
    tag.hidden = true;
    $('editorHint').textContent = '支持 Markdown 编辑，或拖入 .md / .docx 文件';
  }
}

function bindDrop(zone) {
  ['dragenter', 'dragover'].forEach((ev) => zone.addEventListener(ev, (e) => {
    e.preventDefault();
    zone.classList.add('dragging');
  }));
  ['dragleave', 'drop'].forEach((ev) => zone.addEventListener(ev, (e) => {
    e.preventDefault();
    if (ev === 'dragleave' && zone.contains(e.relatedTarget)) return;
    zone.classList.remove('dragging');
  }));
  zone.addEventListener('drop', (e) => {
    if (e.dataTransfer && e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
  });
}

// ---------------------------------------------------------------- 手机预览

/* iPhone 18 Pro 真机尺寸（CSS px）：屏幕 402 × 874，四周边框各 11px -> 机身 424 × 896。
   预览始终按这个原始尺寸渲染，再整体 scale 到可视区，好处是：
   1) 排版（折行位置、字号观感）与真机逐像素一致；
   2) 整块屏幕都能一次看全，不会只露出上面一小截。 */
const PHONE_W = 424;
const PHONE_H = 896;
let previewMode = 'pro';   // pro=真机比例自适应 | actual=1:1 可滚动 | wide=无外壳宽屏

function applyPreviewMode() {
  const box = $('previewScroll');
  const stage = $('phoneStage');
  const phone = $('phone');
  phone.classList.toggle('wide', previewMode === 'wide');
  if (previewMode === 'wide') {
    // 宽屏模式没有机身，尺寸直接铺满预览区；注意要把 scrollable 清掉，
    // 否则从「1:1」切过来时会残留滚动条和顶对齐
    box.classList.remove('scrollable');
    stage.style.width = '100%';
    stage.style.height = '100%';
    phone.style.transform = '';
    state.scale = 1;
    renderHint();
    return;
  }
  fitPhone();
}

function fitPhone() {
  if (previewMode === 'wide') return;
  const box = $('previewScroll');
  const stage = $('phoneStage');
  const phone = $('phone');

  let fit = 1;
  let needScroll = false;
  if (previewMode === 'actual') {
    needScroll = true;                      // 1:1 时必然可能超出，交给滚动
  } else {
    const availW = Math.max(80, box.clientWidth - 30);   // 留 30px 给机身阴影
    const availH = Math.max(80, box.clientHeight - 30);
    fit = Math.min(1, availW / PHONE_W, availH / PHONE_H);
    if (fit < 0.34) { fit = 0.34; needScroll = true; }   // 兜底：别缩到看不清
  }
  box.classList.toggle('scrollable', needScroll);

  // 占位盒子取「缩放后」的尺寸，这样居中、滚动范围都是准的
  stage.style.width = Math.round(PHONE_W * fit) + 'px';
  stage.style.height = Math.round(PHONE_H * fit) + 'px';
  phone.style.transform = 'scale(' + fit + ')';
  state.scale = fit;
  renderHint();
}

function renderHint() {
  const s = state.stats || {};
  const parts = [];
  if (s.cost_ms) parts.push(s.cost_ms + ' ms');
  if (s.html_kb) parts.push(s.html_kb + ' KB');
  if (previewMode === 'actual') parts.push('1:1 实际大小');
  else if (previewMode !== 'wide' && state.scale && state.scale < 0.995) {
    parts.push('缩放 ' + Math.round(state.scale * 100) + '%');
  }
  $('previewHint').textContent = parts.join(' · ');
}

// ---------------------------------------------------------------- 初始化

async function loadThemes() {
  const res = await fetch('/api/themes');
  const data = await res.json();
  const fill = (sel, map) => {
    sel.innerHTML = '';
    Object.keys(map).forEach((k) => {
      const o = document.createElement('option');
      o.value = k;
      o.textContent = map[k];
      sel.appendChild(o);
    });
  };
  fill($('theme'), data.articles);
  fill($('codeTheme'), data.codes);
  state.codeOf = data.code_of || {};
  // 默认主题（列表第一项就是它，这里显式设一次更保险），
  // 代码配色取该主题的推荐值而不是全局默认（否则会出现「青竹绿 + 深色代码块」这种不搭的开局）
  const d = data.defaults || {};
  if (d.theme && Array.from($('theme').options).some((o) => o.value === d.theme)) {
    $('theme').value = d.theme;
  }
  const rec = state.codeOf[$('theme').value] || d.code_theme;
  if (rec && Array.from($('codeTheme').options).some((o) => o.value === rec)) {
    $('codeTheme').value = rec;
  }
  state.lastTheme = $('theme').value;
}

async function loadSample() {
  try {
    const res = await fetch('/api/sample');
    const data = await res.json();
    if (!data.ok) return toast('示例加载失败');
    state.source = 'md';
    state.docxName = '';
    state.docxB64 = '';
    $('editor').readOnly = false;
    $('editor').value = data.markdown;
    updateSourceTag();
    runConvert();
    toast('已载入示例文章');
  } catch (e) {
    toast('示例加载失败：' + e.message);
  }
}

function clearAll() {
  state.source = 'md';
  state.docxName = '';
  state.docxB64 = '';
  state.bodyHtml = '';
  const ed = $('editor');
  ed.readOnly = false;
  ed.value = '';
  try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* 忽略 */ }
  updateSourceTag();
  $('mpContent').innerHTML = emptyState('📄', '左侧粘贴或上传文档，这里会实时显示粘贴后的效果',
    '点「载入示例」可以马上看一份完整样板');
  state.check = { ok: true, errors: [], warnings: [] };
  state.stats = {};
  renderStats();
  renderCheck();
  renderHint();
  toast('已清空');
}

function bindEvents() {
  $('editor').addEventListener('input', () => scheduleConvert());

  ['theme', 'codeTheme', 'lineNumbers', 'headingStyle', 'divider', 'fontSize',
    'linkMode', 'codeMode', 'codeChrome', 'flatTags'].forEach((id) => {
    $(id).addEventListener('change', () => { saveSettings(); scheduleConvert(60); });
  });

  // 换文章主题时，如果代码配色还处在「跟着主题走」的状态，就一起换成该主题的推荐配色；
  // 判定方式：当前代码配色 == 上一个文章主题的推荐值（说明用户没手动改过），
  // 手动改过就不再自动覆盖。
  $('theme').addEventListener('change', () => {
    const prev = state.codeOf[state.lastTheme];
    const next = state.codeOf[$('theme').value];
    if (next && $('codeTheme').value === prev) $('codeTheme').value = next;
    state.lastTheme = $('theme').value;
  });
  ['metaTitle', 'metaAuthor', 'metaDate', 'metaFooter'].forEach((id) => {
    $(id).addEventListener('input', () => scheduleConvert(500));
  });

  $('btnMore').addEventListener('click', () => {
    const p = $('morePanel');
    p.hidden = !p.hidden;
    $('btnMore').setAttribute('aria-expanded', String(!p.hidden));
    $('btnMore').textContent = p.hidden ? '更多设置 ▾' : '收起设置 ▴';
  });

  $('fileInput').addEventListener('change', (e) => {
    handleFiles(e.target.files);
    e.target.value = '';
  });
  $('btnSample').addEventListener('click', loadSample);
  $('btnClear').addEventListener('click', clearAll);
  $('btnCopy').addEventListener('click', copyRich);
  $('btnDownloadPreview').addEventListener('click', () => download());

  $('btnCheckDetail').addEventListener('click', () => toggleCheckPanel());
  $('btnCheckClose').addEventListener('click', () => toggleCheckPanel(false));

  $('widthSeg').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    Array.from($('widthSeg').children).forEach((x) => x.classList.toggle('on', x === b));
    // 机身尺寸全部由 CSS 定义（.phone 424×896），缩放由 fitPhone() 计算，
    // 这里只切换模式，避免同一份数字散落在多处
    previewMode = b.dataset.w || 'pro';
    applyPreviewMode();
  });

  // 预览区尺寸变化（改窗口、展开「更多设置」）后重新计算缩放，保证整块屏幕始终可见
  if (window.ResizeObserver) {
    new ResizeObserver(() => fitPhone()).observe($('previewScroll'));
  } else {
    window.addEventListener('resize', fitPhone);
  }
  applyPreviewMode();

  bindDrop($('.pane-editor'));
  document.addEventListener('dragover', (e) => e.preventDefault());
  document.addEventListener('drop', (e) => e.preventDefault());

  document.addEventListener('keydown', (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.shiftKey && (e.key === 'c' || e.key === 'C')) { e.preventDefault(); copyRich(); }
    if (mod && !e.shiftKey && (e.key === 's' || e.key === 'S')) { e.preventDefault(); download(); }
  });
}

async function init() {
  try {
    await loadThemes();
  } catch (e) {
    return toast('服务连接失败，请确认服务仍在运行');
  }
  restoreSettings();
  state.lastTheme = $('theme').value;   // 用户可能存过别的主题
  bindEvents();

  let draft = '';
  try { draft = localStorage.getItem(DRAFT_KEY) || ''; } catch (e) { draft = ''; }
  if (draft.trim()) {
    $('editor').value = draft;
    runConvert();
  } else {
    await loadSample();
  }
}

init();
