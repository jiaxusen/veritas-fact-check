/* ===== 查证台 · 前端交互（增强版） =====
 * 新增能力：逐句拆解核查、原文疑点高亮、置信度构成明细、来源筛选、
 *          多格式导出（图片 / Markdown / JSON / 打印）、辟谣话术、
 *          历史搜索与筛选、重复查证提示、明暗主题切换、核查模式。
 */
const API_BASE = (location.protocol === 'file:') ? 'http://127.0.0.1:8000' : '';
/* ---------- 门禁校验 ---------- */
if (!sessionStorage.getItem('vc_access_token')) {
  location.replace('access.html');
}
const $ = (sel) => document.querySelector(sel);
const claimInput = $('#claimInput');
const charCount = $('#charCount');
const verifyBtn = $('#verifyBtn');
const scanStage = $('#scanStage');
const resultArea = $('#resultArea');
const toastEl = $('#toast');

let currentCard = null;
let currentSegments = null;
let currentEngine = 'auto';
let sourceFilter = 'all';
const FAV_KEY = 'vc_favs';
const THEME_KEY = 'vc_theme';

/* ---------- 工具 ---------- */
function toast(msg, ms = 2200) {
  toastEl.textContent = msg;
  toastEl.classList.add('show');
  clearTimeout(toastEl._t);
  toastEl._t = setTimeout(() => toastEl.classList.remove('show'), ms);
}
function esc(str) {
  return String(str ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}
function download(filename, content, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}
function clockTick() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  $('#clock').textContent = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
setInterval(clockTick, 1000); clockTick();

/* ---------- 主题 ---------- */
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  document.body.setAttribute('data-theme', theme);
  $('#themeBtn').innerHTML = theme === 'light'
    ? '<span class="th-ico">◐</span>暗色'
    : '<span class="th-ico">◑</span>亮色';
  try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* 忽略 */ }
}
function initTheme() {
  let saved = 'dark';
  try { saved = localStorage.getItem(THEME_KEY) || 'dark'; } catch (e) { /* 忽略 */ }
  applyTheme(saved);
}
$('#themeBtn').addEventListener('click', () => {
  const now = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  applyTheme(now);
});

/* ---------- 引擎状态 ---------- */
async function loadHealth() {
  try {
    const r = await fetch(`${API_BASE}/api/health`);
    const d = await r.json();
    const rm = d.remote || {};
    if (!rm.enabled) {
      // 后端为接入在线融合之前的旧版本，屏蔽引擎选择以免误以为已生效
      $('#engineLabel').textContent = d.engine === 'llm' ? '大模型引擎 · 在线' : '本地查证引擎 · 在线';
      const sel = $('#engineSelect');
      if (sel) {
        sel.title = '当前端口运行的后端尚未接入在线融合引擎，请启动新版后端后使用';
        sel.disabled = true;
      }
      return;
    }
    $('#engineLabel').textContent = rm.reachable ? '融合引擎 · 本地+在线' : '融合引擎 · 在线待命';
  } catch (e) {
    $('#engineLabel').textContent = '服务未连接';
  }
}
loadHealth();

/* ---------- 输入交互 ---------- */
claimInput.addEventListener('input', () => {
  charCount.textContent = claimInput.value.length;
});
document.querySelectorAll('.sample-chip').forEach((chip) => {
  chip.addEventListener('click', () => {
    claimInput.value = chip.dataset.text;
    charCount.textContent = claimInput.value.length;
    claimInput.focus();
  });
});

/* ---------- 附件导入：截图 / 图片 / 文件 ---------- */
let extractBusy = false;
function setAttachTip(msg, kind = '') {
  const el = $('#attachTip');
  if (!el) return;
  el.textContent = msg || '';
  el.className = 'attach-tip' + (kind ? ' ' + kind : '');
}
async function extractViaServer(file) {
  const fd = new FormData();
  fd.append('file', file, file.name);
  const r = await fetch(`${API_BASE}/api/input/extract`, { method: 'POST', body: fd });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || d.ok === false) throw new Error(d.error || d.detail || `${file.name} 提取失败`);
  return d;
}
async function ocrViaServer(name, dataUrl) {
  const r = await postJSON('/api/input/ocr', { name, data: dataUrl });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || d.ok === false) throw new Error(d.error || d.detail || '图片识别失败');
  return d;
}
function appendExtractedText(text) {
  const cur = claimInput.value.trim();
  claimInput.value = cur ? `${cur}\n${text}` : text;
  if (claimInput.value.length > 2000) {
    claimInput.value = claimInput.value.slice(0, 2000);
    toast('内容已超过 2000 字，自动截取前 2000 字', 3000);
  }
  charCount.textContent = claimInput.value.length;
  claimInput.focus();
}
async function handleFiles(files) {
  if (extractBusy) { toast('正在识别中，请稍候'); return; }
  const list = Array.from(files || []).slice(0, 5);
  if (!list.length) return;
  extractBusy = true;
  setAttachTip('识别中…', 'busy');
  let okCount = 0;
  try {
    for (const f of list) {
      try {
        const isImg = /^image\//.test(f.type) || /\.(png|jpe?g|webp|bmp|gif|tiff?)$/i.test(f.name);
        const limit = isImg ? 12 : 25;
        if (f.size > limit * 1024 * 1024) throw new Error(`文件超过 ${limit}MB`);
        const d = await extractViaServer(f);
        appendExtractedText(d.text);
        okCount += 1;
        setAttachTip(`已识别：${d.name}（${d.text.length} 字）`, 'ok');
        if (d.warnings && d.warnings.length) toast(d.warnings[0], 3000);
      } catch (e) {
        toast(`${f.name}：${e.message}`, 3600);
      }
    }
    if (!okCount) setAttachTip('导入失败', 'err');
  } finally {
    extractBusy = false;
  }
}
/* ---------- 截图识别：抓取屏幕画面并识别其中的文字 ---------- */
async function captureScreenshot() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
    toast('当前浏览器不支持屏幕截图，请改用「图片识别」', 3200);
    return;
  }
  let stream = null;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 1 }, audio: false });
    const video = document.createElement('video');
    video.srcObject = stream;
    video.muted = true;
    await video.play();
    await new Promise((r) => setTimeout(r, 300));
    const w = video.videoWidth || window.innerWidth;
    const h = video.videoHeight || window.innerHeight;
    const canvas = document.createElement('canvas');
    canvas.width = w; canvas.height = h;
    canvas.getContext('2d').drawImage(video, 0, 0, w, h);
    setAttachTip('识别中…', 'busy');
    const d = await ocrViaServer('screenshot.png', canvas.toDataURL('image/png'));
    appendExtractedText(d.text);
    setAttachTip(`截图识别完成 · ${d.text.length} 字`, 'ok');
  } catch (e) {
    if (e && e.name === 'NotAllowedError') { setAttachTip('已取消截图', ''); return; }
    toast(e.message || '截图识别失败', 3200);
    setAttachTip('截图失败', 'err');
  } finally {
    if (stream) stream.getTracks().forEach((t) => t.stop());
  }
}
$('#shotBtn')?.addEventListener('click', captureScreenshot);
$('#imgBtn')?.addEventListener('click', () => $('#imgInput')?.click());
$('#fileBtn')?.addEventListener('click', () => $('#fileInput')?.click());
$('#imgInput')?.addEventListener('change', (e) => { handleFiles(e.target.files); e.target.value = ''; });
$('#fileInput')?.addEventListener('change', (e) => { handleFiles(e.target.files); e.target.value = ''; });
if (!window.isSecureContext) {
  const b = $('#shotBtn');
  if (b) { b.disabled = true; b.title = '截图功能需要 https 或 localhost 环境，当前为不安全来源'; }
}
/* 拖拽导入 */
const dropZone = $('#dropZone');
if (dropZone) {
  ['dragenter', 'dragover'].forEach((ev) => dropZone.addEventListener(ev, (e) => {
    e.preventDefault(); dropZone.classList.add('dragover');
  }));
  ['dragleave', 'drop'].forEach((ev) => dropZone.addEventListener(ev, (e) => {
    e.preventDefault();
    if (ev === 'dragleave' && e.relatedTarget && dropZone.contains(e.relatedTarget)) return;
    dropZone.classList.remove('dragover');
  }));
  dropZone.addEventListener('drop', (e) => {
    const files = e.dataTransfer && e.dataTransfer.files;
    if (files && files.length) { handleFiles(files); return; }
    const txt = e.dataTransfer && e.dataTransfer.getData('text/plain');
    if (txt && txt.trim().length >= 4) appendExtractedText(txt.trim());
  });
}
// 防止浏览器接管拖拽文件导致整页跳转
['dragover', 'drop'].forEach((ev) => window.addEventListener(ev, (e) => e.preventDefault()));
/* 粘贴截图识别 */
claimInput.addEventListener('paste', (e) => {
  const items = (e.clipboardData && e.clipboardData.items) || [];
  for (const it of items) {
    if (it.type && it.type.indexOf('image') === 0) {
      const file = it.getAsFile();
      if (file) { e.preventDefault(); handleFiles([file]); return; }
    }
  }
});

/* ---------- 事实点拆分（前端版，与后端 split_module 同策略） ---------- */
function splitClaims(text) {
  const raw = (text || '').trim();
  if (!raw) return [];
  const pieces = raw.split(/([。！？；!?;]+)/);
  const bufOut = [];
  let buf = '';
  for (const p of pieces) {
    if (/[。！？；!?;]+/.test(p)) { buf += p; bufOut.push(buf); buf = ''; }
    else buf += p;
  }
  if (buf.trim()) bufOut.push(buf);
  let items = bufOut.map((s) => s.trim()).filter((s) => s.length >= 6);
  if (items.length < 2) {
    const byComma = raw.split(/[，,]/).map((s) => s.trim()).filter((s) => s.length >= 6);
    if (byComma.length >= 2) items = byComma;
  }
  const out = [];
  let cursor = 0;
  for (const s of items.slice(0, 6)) {
    let idx = raw.indexOf(s, cursor);
    if (idx < 0) idx = cursor;
    out.push({ text: s, start: idx, end: idx + s.length });
    cursor = idx + s.length;
  }
  return out;
}

/* ---------- 扫描动画 ---------- */
function runScanAnimation() {
  const steps = document.querySelectorAll('.scan-step');
  steps.forEach((s) => s.classList.remove('doing', 'done'));
  scanStage.classList.add('active');
  return new Promise((resolve) => {
    let i = 0;
    const timer = setInterval(() => {
      if (i > 0) steps[i - 1].classList.replace('doing', 'done');
      if (i >= steps.length) {
        clearInterval(timer);
        setTimeout(resolve, 220);
        return;
      }
      steps[i].classList.add('doing');
      i++;
    }, 260);
  });
}

/* ---------- 重复查证检测 ---------- */
const historyCache = [];
function findDuplicate(text) {
  const key = text.trim().slice(0, 60);
  return historyCache.find((r) => (r.input_text || '').trim().slice(0, 60) === key);
}

/* ---------- 请求封装 ---------- */
function getJSON(path) {
  return fetch(`${API_BASE}${path}`, { method: 'GET' });
}
function postJSON(path, body) {
  return fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
}
function engineValue() {
  return ($('#engineSelect') && $('#engineSelect').value) || 'auto';
}
async function fetchCard(text, mode, useLLM, engine) {
  // 老版本后端不识别 engine 字段会自动忽略，不影响调用
  const body = { text, mode, engine: engine || 'auto' };
  const resp = await postJSON(useLLM ? '/api/verify/llm' : '/api/verify', body);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `请求失败（${resp.status}）`);
  }
  return resp.json();
}

/* ---------- 分段核查：优先服务端拆句，失败则前端拆句 + 并发请求 ---------- */
async function fetchSegmentsServer(text, mode, engine) {
  try {
    const r = await postJSON('/api/verify/segment', { text, mode, engine: engine || 'auto' });
    if (!r.ok) return null;
    const d = await r.json();
    if (d && d.segmented && d.segments && d.segments.length >= 2) return d;
    return null;
  } catch (e) { return null; }
}
async function fetchSegmentsClient(segs, mode, useLLM, engine) {
  const tasks = segs.map((s) => fetchCard(s.text, mode, useLLM, engine).catch(() => null));
  const cards = await Promise.all(tasks);
  return segs.map((s, i) => {
    const c = cards[i];
    if (!c) return {
      ...s,
      verdict: { level: 'uncertain', label: '存疑', color: '#FFB020', confidence: 0, summary: '该句查证失败' },
      source_count: 0, top_source: '', card: null,
    };
    return {
      ...s,
      verdict: {
        level: c.verdict.level, label: c.verdict.label, color: c.verdict.color,
        confidence: c.verdict.confidence, summary: c.verdict.summary,
      },
      source_count: c.evidence_stats.source_count,
      top_source: c.sources && c.sources[0] ? c.sources[0].domain : '',
      card: c,
    };
  });
}

/* ---------- 主流程 ---------- */
const LEVEL_ORDER = { false: 0, uncertain: 1, partly_true: 2, mostly_true: 3, true: 4 };
function pickWeakest(segments) {
  return segments.slice().sort((a, b) =>
    (LEVEL_ORDER[a.verdict.level] ?? 1) - (LEVEL_ORDER[b.verdict.level] ?? 1))[0];
}

async function doVerify() {
  const text = claimInput.value.trim();
  if (!text) { toast('请先输入需要核实的内容'); claimInput.focus(); return; }
  if (text.length < 4) { toast('内容过短，请补充完整后再查证'); return; }
  verifyBtn.disabled = true;
  verifyBtn.textContent = '查证中…';
  resultArea.classList.remove('active');
  const anim = runScanAnimation();
  const mode = $('#modeSelect').value;
  const wantSplit = $('#splitMode').checked;
  const useLLM = !!($('#llmMode') && $('#llmMode').checked);
  const engine = engineValue();
  try {
    if (wantSplit) {
      let segments = null, aggregate = null;
      const serverData = useLLM ? null : await fetchSegmentsServer(text, mode, engine);
      if (serverData) {
        segments = serverData.segments;
        aggregate = serverData.aggregate;
      } else {
        const segs = splitClaims(text);
        if (segs.length >= 2) segments = await fetchSegmentsClient(segs, mode, useLLM, engine);
      }
      if (segments && segments.length >= 2) {
        const worst = pickWeakest(segments);
        let card = worst.card || null;
        if (!card) card = await fetchCard(worst.text, mode, useLLM, engine).catch(() => null);
        currentSegments = segments;
        currentCard = card;
        currentEngine = engine;
        sourceFilter = 'all';
        await Promise.resolve(anim);
        renderSegmentReport(text, segments, card, aggregate);
        loadHistory();
        toast(`逐句核查完成 · ${segments.length} 个事实点`);
        return;
      }
      toast('未拆出多个事实点，已按整段查证');
    }
    const [card] = await Promise.all([fetchCard(text, mode, useLLM, engine), anim]);
    currentCard = card;
    currentSegments = null;
    currentEngine = engine;
    sourceFilter = 'all';
    renderCard(card);
    loadHistory();
    toast(card.remote_used ? '融合查证完成 · 已并入在线证据' : (engine === 'local' ? '查证完成 · 本地引擎' : '查证完成 · 在线未参与，已用本地引擎'));
  } catch (e) {
    toast(e.message || '查证失败，请稍后重试', 3200);
  } finally {
    verifyBtn.disabled = false;
    verifyBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="10.5" cy="10.5" r="6.5"></circle><path d="M15.5 15.5 L21 21"></path></svg>开始查证';
    scanStage.classList.remove('active');
  }
}

verifyBtn.addEventListener('click', doVerify);
claimInput.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') doVerify();
});

/* ---------- 渲染工具 ---------- */
const HL_CLASS = { '属实': 'hl-true', '基本属实': 'hl-true', '部分属实': 'hl-partly', '存疑': 'hl-uncertain', '不实': 'hl-false' };

function highlight(text, segs) {
  if (!segs || !segs.length) return esc(text);
  let html = '', cur = 0;
  segs.slice().sort((a, b) => a.start - b.start).forEach((s) => {
    if (s.start > cur) html += esc(text.slice(cur, s.start));
    const cls = HL_CLASS[s.verdict.label] || 'hl-uncertain';
    html += `<mark class="${cls}">${esc(text.slice(s.start, s.end))}</mark>`;
    cur = s.end;
  });
  html += esc(text.slice(cur));
  return html;
}

function moduleHead(idx, title, sub) {
  return `<div class="module-head"><span class="m-idx">${idx}</span><h3>${title}</h3><span class="m-sub">${esc(sub || '')}</span></div>`;
}

function renderTone(tone) {
  if (!tone) return '';
  const tags = [];
  tone.rumor_markers.slice(0, 4).forEach((m) => tags.push(`<span class="tone-tag tone-bad">煽动句式 · ${esc(m)}</span>`));
  tone.absolute_markers.slice(0, 3).forEach((m) => tags.push(`<span class="tone-tag tone-warn">绝对化表述 · ${esc(m)}</span>`));
  tone.scientific_markers.slice(0, 3).forEach((m) => tags.push(`<span class="tone-tag tone-good">严谨表述 · ${esc(m)}</span>`));
  if (!tags.length) tags.push('<span class="tone-tag">未检出明显修辞风险</span>');
  return `<div class="tone-box">
    <div class="tone-head">语言特征画像：<b>${esc(tone.tone_label)}</b><span class="tone-risk">风险分 ${tone.risk}</span></div>
    <div class="tone-tags">${tags.join('')}</div>
  </div>`;
}

/* ---------- 置信度构成：后端给出则用后端，否则按本次数据反推影响因子 ---------- */
function deriveBreakdown(card) {
  const st = card.evidence_stats || {};
  const src = card.sources || [];
  const tone = card.tone || {};
  const sup = (card.evidence && card.evidence.support) || [];
  const ref = (card.evidence && card.evidence.refute) || [];
  const sumStrength = (arr) => arr.reduce((a, b) => a + (b.strength || 0), 0);
  const credAvg = src.length ? src.reduce((a, b) => a + (b.credibility_score || 0), 0) / src.length : 0;
  const aCount = src.filter((s) => s.credibility === 'A').length;
  const bCount = src.filter((s) => s.credibility === 'B').length;
  const mode = card.mode || 'balanced';
  const items = [];
  items.push({
    label: `已核验来源 ${st.source_count} 条（权威级 ${aCount} / 可靠级 ${bCount}）`,
    delta: Math.round(Math.min(26, st.source_count * 3 + aCount * 6 + bCount * 2)),
  });
  items.push({
    label: `支持依据 ${sup.length} 条，累计强度 ${sumStrength(sup).toFixed(2)}`,
    delta: Math.round(Math.min(32, sumStrength(sup) * 6)),
  });
  items.push({
    label: `矛盾依据 ${ref.length} 条，累计强度 ${sumStrength(ref).toFixed(2)}`,
    delta: -Math.round(Math.min(36, sumStrength(ref) * 7)),
  });
  items.push({
    label: `来源平均可信度 ${Math.round(credAvg)} 分`,
    delta: Math.round((credAvg - 62) * 0.3),
  });
  if (tone.risk) {
    items.push({ label: `表述风险分 ${tone.risk}（夸张 / 绝对化修辞）`, delta: -Math.round(Math.min(14, tone.risk * 0.6)) });
  }
  items.push({
    label: { strict: '严谨模式：抬高证据门槛', loose: '宽松模式：降低证据门槛', balanced: '均衡模式：未额外偏置' }[mode],
    delta: mode === 'strict' ? -4 : mode === 'loose' ? 4 : 0,
  });
  return items.filter((i) => i.delta !== 0);
}

function renderBreakdown(v, card) {
  let bd = v.breakdown;
  let note = '';
  if (!bd || !bd.length) {
    if (!card) return `<div class="bd-empty">本次结论依据：${esc(v.reason || '')}</div>`;
    bd = deriveBreakdown(card);
    note = '<div class="bd-note">以下为按本次查证数据反推的相对影响权重，最终置信度由查证引擎综合加权给出。</div>';
  }
  if (!bd.length) return `<div class="bd-empty">本次结论依据：${esc(v.reason || '')}</div>`;
  const maxAbs = Math.max(1, ...bd.map((b) => Math.abs(b.delta)));
  const rows = bd.map((b) => {
    const pos = b.delta >= 0;
    const w = Math.max(3, Math.abs(b.delta) / maxAbs * 100);
    return `<div class="bd-row">
      <div class="bd-label">${esc(b.label)}</div>
      <div class="bd-bar ${pos ? 'pos' : 'neg'}"><i style="width:${w}%"></i></div>
      <div class="bd-val ${pos ? 'pos' : 'neg'}">${pos ? '+' : ''}${b.delta}</div>
    </div>`;
  }).join('');
  return `<div class="bd-box">${rows}
    <div class="bd-total"><span>综合置信度</span><b>${v.confidence}%</b></div>
    ${note}</div>`;
}

/* ---------- 疑点定位：把检出的问题表述标在原文上 ---------- */
function renderSpotlight(text, tone) {
  const markers = [].concat(
    (tone && tone.rumor_markers) || [],
    (tone && tone.absolute_markers) || []
  ).filter(Boolean).sort((a, b) => b.length - a.length);
  if (!markers.length) return '';
  let html = esc(text), hit = 0;
  markers.forEach((m) => {
    const safe = esc(m);
    if (html.indexOf(safe) >= 0) {
      hit++;
      const cls = ((tone.rumor_markers || []).indexOf(m) >= 0) ? 'hl-false' : 'hl-partly';
      html = html.split(safe).join(`<mark class="${cls}" title="${cls === 'hl-false' ? '煽动 / 疑似谣言句式' : '绝对化表述'}">${safe}</mark>`);
    }
  });
  if (!hit) return '';
  return `<div class="spot-box">
    <div class="spot-head">疑点定位 · 在原文中检出 ${hit} 处需注意的表述
      <span class="spot-legend"><i class="lg hl-false"></i>煽动句式 <i class="lg hl-partly"></i>绝对化表述</span>
    </div>
    <div class="spot-text">${html}</div>
  </div>`;
}

/* ---------- 来源冲突可视化 ---------- */
function renderConflict(stats) {
  const s = stats.support_count || 0, r = stats.refute_count || 0;
  const total = s + r;
  if (!total) return '';
  const sp = Math.round(s / total * 100);
  return `<div class="conflict-meter">
    <div class="cm-label"><span class="cm-s">支持 ${s} 条依据</span><span class="cm-r">矛盾 ${r} 条依据</span></div>
    <div class="cm-track">
      <div class="cm-side support" style="width:${sp}%"><span>${sp}%</span></div>
      <div class="cm-side refute" style="width:${100 - sp}%"><span>${100 - sp}%</span></div>
    </div>
    <div class="cm-tip">${r === 0 ? '本次未发现与原文冲突的来源，结论一侧指向。'
      : s === 0 ? '所有有效来源均与原文冲突，判为不实的风险较高。'
      : (Math.abs(sp - 50) < 18 ? '正反两侧来源强度接近，属于典型的分歧场景，建议人工复核。' : '冲突来源占比悬殊，冲突结构清晰。')}</div>
  </div>`;
}

function engineLabel(card) {
  if (card.engine === 'llm') return '大模型引擎';
  if (card.engine === 'fusion') return card.remote ? '本地 + 在线融合' : '融合模式（在线未参与）';
  return '本地查证引擎';
}

function sourceFilterBar(sources) {
  const counts = { A: 0, B: 0, C: 0 };
  sources.forEach((s) => { if (counts[s.credibility] !== undefined) counts[s.credibility]++; });
  const opts = [
    ['all', `全部 ${sources.length}`],
    ['A', `权威 ${counts.A}`],
    ['B', `可靠 ${counts.B}`],
    ['C', `一般 ${counts.C}`],
  ];
  return `<div class="src-filter">${opts.map(([k, label]) =>
    `<button class="sf-btn ${sourceFilter === k ? 'on' : ''}" data-k="${k}">${label}</button>`).join('')}</div>`;
}

function sourceCardHtml(sources) {
  const list = sourceFilter === 'all' ? sources : sources.filter((s) => s.credibility === sourceFilter);
  if (!list.length) return '<div class="empty-hint">当前筛选条件下没有来源</div>';
  return list.map((s) => `
    <div class="source-card">
      <div class="source-rank">${esc(s.id)}</div>
      <div class="source-main">
        <div class="source-title"><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a></div>
        <div class="source-meta">
          <span class="cred-tag cred-${esc(s.credibility)}">${esc(s.credibility_label)} ${s.credibility_score}</span>
          <span>${esc(s.source_type_label || '')}</span>
          <span>${esc(s.domain)}</span>
          <span>${esc(s.published_at)}</span>
        </div>
        <div class="source-snippet">${esc(s.snippet)}</div>
      </div>
    </div>`).join('');
}

function exportBar() {
  return `<div class="export-bar">
    <button class="btn-ghost" id="copyBtn">复制查证卡</button>
    <button class="btn-ghost" id="exportBtn">导出图片</button>
    <button class="btn-ghost" id="mdBtn">导出 Markdown</button>
    <button class="btn-ghost" id="jsonBtn">导出 JSON</button>
    <button class="btn-ghost" id="printBtn">打印 / PDF</button>
    <button class="btn-ghost" id="scriptBtn">生成辟谣话术</button>
  </div>`;
}

/* ---------- 渲染：在线核查面板（融合模式） ---------- */
const RV_LEVEL_COLOR = { true: '#22D39A', mostly_true: '#3DDC97', partly_true: '#7ED957', uncertain: '#FFB020', false: '#FF4D6D' };

function renderRemoteClaimRow(c, fallbackText) {
  return `<div class="rv-claim ${esc(c.level)}">
    <span class="rv-claim-badge" style="color:${RV_LEVEL_COLOR[c.level] || '#8FA3BF'};border-color:${RV_LEVEL_COLOR[c.level] || '#8FA3BF'}55;background:${RV_LEVEL_COLOR[c.level] || '#8FA3BF'}14">${esc(c.label)}</span>
    <div class="rv-claim-body">
      <div class="rv-claim-text">${esc(c.text || fallbackText)}</div>
      ${c.note ? `<div class="rv-claim-note">${esc(c.note)}</div>` : ''}
      ${c.source_title ? `<div class="rv-claim-src">↗ <a href="${esc(c.source_url)}" target="_blank" rel="noopener">${esc(c.source_title)}</a>${c.source_domain ? ` · ${esc(c.source_domain)}` : ''}</div>` : ''}
    </div>
  </div>`;
}

function renderRemoteEvidenceRow(e) {
  return `<div class="rv-ev">
    <div class="rv-ev-head">
      <span class="rv-type">${esc(e.type || '在线来源')}</span>
      <span class="rv-site">${esc(e.site || e.domain || '')}</span>
      ${e.exact ? '<span class="rv-badge exact">原样命中</span>' : ''}
      <span class="rv-score">证据分 ${Math.round(e.score || 0)}</span>
      ${e.locator ? `<span class="rv-badge loc">${esc(e.locator)}</span>` : ''}
    </div>
    <div class="rv-ev-title"><a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.title)}</a></div>
    ${e.quote ? `<div class="rv-quote">“${esc(e.quote)}”</div>` : ''}
    <div class="rv-ev-meta">${esc(e.date)}${e.query ? ` · 检索式「${esc(e.query)}」` : ''}${e.source_id ? ` · 已并入来源清单 ${esc(e.source_id)}` : '<span class="rv-dim"> · 未进入最终来源清单</span>'}</div>
  </div>`;
}

function renderRemotePanel(card) {
  const rv = card.remote;
  if (!rv) return '';
  const p = rv.pipeline || {};
  const metrics = [
    p.claims ? `拆出事实点 ${p.claims}` : '',
    p.queries ? `检索式 ${p.queries}` : '',
    p.sources ? `抓取来源 ${p.sources}` : '',
    p.pages ? `读取正文 ${p.pages} 页` : '',
    p.verified ? `原样校验通过 ${p.verified}` : '',
    (rv.elapsed_ms || p.ms) ? `耗时 ${rv.elapsed_ms || p.ms} ms` : '',
  ].filter(Boolean).join(' · ');
  const arb = card.arbitration || {};
  const arbTip = arb.applied
    ? `<div class="rv-arb">裁决逻辑：${esc(arb.reason || '')}${arb.note ? `<span class="rv-arb-note">${esc(arb.note)}</span>` : ''}</div>`
    : '';
  return `<div class="rv-box">
    <div class="rv-head">
      <span class="rv-verdict" style="color:${RV_LEVEL_COLOR[rv.level] || '#8FA3BF'};border-color:${RV_LEVEL_COLOR[rv.level] || '#8FA3BF'}55;background:${RV_LEVEL_COLOR[rv.level] || '#8FA3BF'}14">${esc(rv.label)} ${rv.confidence}%</span>
      <span class="rv-provider">在线查证引擎 · ${esc(rv.provider)}</span>
      <span class="rv-src">共核到 ${rv.src_count || (rv.evidences || []).length} 条来源</span>
    </div>
    ${rv.title ? `<div class="rv-title">${esc(rv.title)}</div>` : ''}
    ${rv.conclusion ? `<div class="rv-block"><b>核查结论</b><span>${esc(rv.conclusion)}</span></div>` : ''}
    ${rv.accurate ? `<div class="rv-block accurate"><b>准确表述</b><span>${esc(rv.accurate)}</span></div>` : ''}
    ${arbTip}
    ${(rv.claims || []).length ? `<div class="rv-sub">逐条事实点判定</div><div class="rv-claims">${rv.claims.map((c) => renderRemoteClaimRow(c, card.input_text)).join('')}</div>` : ''}
    ${(rv.evidences || []).length ? `<div class="rv-sub">在线证据清单（含命中方式与原文定位）</div><div class="rv-evs">${rv.evidences.map(renderRemoteEvidenceRow).join('')}</div>` : ''}
    ${rv.limitation ? `<div class="rv-limit"><b>局限说明</b><span>${esc(rv.limitation)}</span></div>` : ''}
    ${rv.reasoning ? `<details class="rv-reason"><summary>查看在线侧判定推演</summary><div>${esc(rv.reasoning)}</div></details>` : ''}
    ${metrics ? `<div class="rv-metrics">${esc(metrics)}</div>` : ''}
    ${rv.share ? `<div class="rv-share-bar"><button class="btn-ghost tiny" id="copyShare">复制在线转发话术</button></div>` : ''}
  </div>`;
}

/* ---------- 渲染：逐句拆解核查 ---------- */
function renderSegmentReport(text, segments, card, aggregate) {
  const dist = {};
  segments.forEach((s) => { dist[s.verdict.label] = (dist[s.verdict.label] || 0) + 1; });
  const distText = Object.entries(dist).map(([k, v]) => `${k} ${v} 句`).join(' · ');
  const agg = aggregate || pickWeakest(segments).verdict;
  let html = '';
  let idx = 2;
  html += `<div class="module">
    ${moduleHead(String(idx++).padStart(2, '0'), '逐句拆解核算', `SEGMENTS · ${segments.length} 个事实点`)}
    <div class="seg-verdict">
      <span class="seg-verdict-label">整段结论</span>
      <span class="verdict-badge tiny ${esc(agg.level || '')}">${esc(agg.label)}</span>
      <span class="seg-verdict-tip">整段结论取决于最薄弱的一句，不以各句平均分为准</span>
    </div>
    <div class="seg-claim">${highlight(text, segments)}</div>
    <div class="seg-list">
      ${segments.map((s) => `
        <div class="seg-item ${esc(s.verdict.level)}">
          <span class="seg-badge">${esc(s.verdict.label)}</span>
          <span class="seg-text">${esc(s.text)}</span>
          <span class="seg-meta">${s.verdict.confidence}% · 来源 ${s.source_count}${s.top_source ? ' · ' + esc(s.top_source) : ''}</span>
        </div>`).join('')}
    </div>
    <div class="seg-summary">共拆出 ${segments.length} 个事实点：${esc(distText)}${agg.weakest ? `。最薄弱的一句是「${esc(agg.weakest)}」，下方查证卡针对该句展开。` : '。'}。</div>
  </div>`;
  if (card) {
    html += `<div class="seg-card-tip">以下为<b>最薄弱一句</b>的完整查证卡：${esc(card.input_text)}</div>`;
    html += renderCardModules(card, 3);
  } else {
    html += '<div class="empty-hint">该句未返回完整查证结果，请取消勾选后按整段重新核查。</div>';
  }
  resultArea.innerHTML = html;
  resultArea.classList.add('active');
  bindResultEvents();
  resultArea.scrollIntoView({ behavior: 'smooth', block: 'start' });
  renderState = { type: 'seg', text, segments, card, aggregate };
}

/* ---------- 渲染：单张查证卡 ---------- */
function renderCard(card) {
  const dup = findDuplicate(card.input_text);
  resultArea.innerHTML = `${dup ? dupNotice(dup) : ''}${renderCardModules(card, 2)}`;
  resultArea.classList.add('active');
  bindResultEvents();
  resultArea.scrollIntoView({ behavior: 'smooth', block: 'start' });
  renderState = { type: 'card', card };
}

/* ---------- 重绘（来源筛选等局部状态变化后保持整体结构） ---------- */
let renderState = null;
function rerender() {
  if (!renderState) return;
  if (renderState.type === 'seg') {
    renderSegmentReport(renderState.text, renderState.segments, renderState.card, renderState.aggregate);
  } else {
    renderCard(renderState.card);
  }
}

function dupNotice(rec) {
  return `<div class="dup-tip">⚠ 这条内容你此前核查过：${esc(rec.created_at)} 的结论是【${esc(rec.label)} · ${rec.confidence}%】。
    <span class="dup-hint">结论变化可能来自来源更新或核查模式差异，建议对比两次的来源清单。</span></div>`;
}

function renderCardModules(card, startIdx) {
  const v = card.verdict;
  const ev = card.evidence;
  const stats = card.evidence_stats;
  const ringR = 34, ringC = 2 * Math.PI * ringR;
  const dash = (v.confidence / 100) * ringC;
  let idx = startIdx;
  return `
  <div class="module">
    ${moduleHead(String(idx++).padStart(2, '0'), '查证结论', 'VERDICT')}
    <div class="verdict-body">
      <div class="verdict-badge ${esc(v.level)}">${esc(v.label)}</div>
      <div class="confidence-box">
        <div class="ring">
          <svg width="82" height="82">
            <circle cx="41" cy="41" r="${ringR}" stroke="rgba(255,255,255,.07)" stroke-width="7" fill="none"></circle>
            <circle cx="41" cy="41" r="${ringR}" stroke="${esc(v.color)}" stroke-width="7" fill="none"
              stroke-linecap="round" stroke-dasharray="${dash} ${ringC}"></circle>
          </svg>
          <div class="ring-text" style="color:${esc(v.color)}">${v.confidence}%</div>
        </div>
        <div class="ring-label">置信度<b>CONFIDENCE</b></div>
      </div>
    </div>
    <div class="verdict-summary"><b>结论说明：</b>${esc(v.summary)}</div>
    ${renderSpotlight(card.input_text, card.tone)}
    <div class="bd-title">置信度怎么来的</div>
    ${renderBreakdown(v, card)}
    ${renderTone(card.tone)}
  </div>
  <div class="module">
    ${moduleHead(String(idx++).padStart(2, '0'), '核对依据', `EVIDENCE · 支持 ${stats.support_count} / 矛盾 ${stats.refute_count}`)}
    ${renderConflict(stats)}
    <div class="evidence-grid">
      <div class="evidence-col support">
        <h4>✓ 支持原文的依据 <span class="count">${stats.support_count}</span></h4>
        ${ev.support.length ? ev.support.map((i) => `
          <div class="evidence-item">
            <div class="ev-point">${esc(i.point)}${i.weak_support ? '<span class="weak-tag">弱支持 · 仅语义相关</span>' : ''}</div>
            <div class="ev-src">
              <span>↗</span>
              <a href="${esc(i.source_url)}" target="_blank" rel="noopener">${esc(i.source_title)}</a>
              <span>· ${esc(i.source_domain)}</span>
            </div>
            <div class="strength-bar"><div class="strength-fill" style="width:${Math.round(i.strength * 100)}%"></div></div>
          </div>`).join('') : '<div class="empty-hint">未发现支持原文的证据</div>'}
      </div>
      <div class="evidence-col refute">
        <h4>✕ 与原文矛盾的证据 <span class="count">${stats.refute_count}</span></h4>
        ${ev.refute.length ? ev.refute.map((i) => `
          <div class="evidence-item">
            <div class="ev-point">${esc(i.point)}</div>
            <div class="ev-src">
              <span>↗</span>
              <a href="${esc(i.source_url)}" target="_blank" rel="noopener">${esc(i.source_title)}</a>
              <span>· ${esc(i.source_domain)}</span>
            </div>
            <div class="strength-bar"><div class="strength-fill" style="width:${Math.round(i.strength * 100)}%"></div></div>
          </div>`).join('') : '<div class="empty-hint">未发现与原文矛盾的证据</div>'}
      </div>
    </div>
  </div>
  ${card.remote ? `
  <div class="module">
    ${moduleHead(String(idx++).padStart(2, '0'), '在线核查详情', `REMOTE · ${card.remote.label} ${card.remote.confidence}% · ${card.remote.evidences.length} 条证据`)}
    ${renderRemotePanel(card)}
  </div>` : ''}
  <div class="module">
    ${moduleHead(String(idx++).padStart(2, '0'), '来源清单', `SOURCES · ${stats.source_count} 条可追溯`)}
    ${sourceFilterBar(card.sources)}
    <div class="source-list">${sourceCardHtml(card.sources)}</div>
  </div>
  ${card.disputes && card.disputes.length ? `
  <div class="module">
    ${moduleHead(String(idx++).padStart(2, '0'), '分歧说明', 'DISPUTE')}
    <div class="dispute-list">${card.disputes.map((d) => `<div class="dispute-item">${esc(d)}</div>`).join('')}</div>
  </div>` : ''}
  <div class="module">
    ${moduleHead(String(idx++).padStart(2, '0'), '风险与局限', 'RISK NOTES')}
    <div class="risk-list">${card.risk_notes.map((r) => `<div class="risk-item"><span class="ri-icon">⚠</span><span>${esc(r)}</span></div>`).join('')}</div>
  </div>
  <div class="module">
    ${moduleHead(String(idx++).padStart(2, '0'), '核查元信息', 'METADATA')}
    <div class="meta-grid">
      <div class="meta-cell"><div class="mk">卡片编号</div><div class="mv">${esc(card.card_id)}</div></div>
      <div class="meta-cell"><div class="mk">核查时间</div><div class="mv">${esc(card.created_at_display)}</div></div>
      <div class="meta-cell"><div class="mk">查证引擎</div><div class="mv">${esc(engineLabel(card))}</div></div>
      <div class="meta-cell"><div class="mk">核查模式</div><div class="mv">${esc({ balanced: '均衡', strict: '严谨', loose: '宽松' }[card.mode || $('#modeSelect').value] || '均衡')}</div></div>
      <div class="meta-cell"><div class="mk">处理耗时</div><div class="mv">${card.elapsed_ms} ms</div></div>
      <div class="meta-cell"><div class="mk">原文长度</div><div class="mv">${card.input_text.length} 字</div></div>
      <div class="meta-cell"><div class="mk">判定依据</div><div class="mv" style="font-family:var(--sans);font-size:12px">${esc(v.reason)}</div></div>
    </div>
    <div class="kw-list">${card.keywords.map((k) => `<span class="kw-chip"># ${esc(k)}</span>`).join('')}</div>
    ${exportBar()}
    <div id="scriptBox"></div>
    <div id="printArea" class="print-area">
      <div class="pa-title">查证卡 ${esc(card.card_id)}</div>
      <div class="pa-row"><b>原文</b><span>${esc(card.input_text)}</span></div>
      <div class="pa-row"><b>结论</b><span>${esc(v.label)}（置信度 ${v.confidence}%）</span></div>
      <div class="pa-row"><b>说明</b><span>${esc(v.summary)}</span></div>
      <div class="pa-src"><b>来源清单</b>${card.sources.map((s) => `<div>· ${esc(s.title)} — ${esc(s.url)}</div>`).join('')}</div>
    </div>
  </div>`;
}

function bindResultEvents() {
  const cb = $('#copyBtn'); if (cb) cb.addEventListener('click', copyCard);
  const eb = $('#exportBtn'); if (eb) eb.addEventListener('click', exportCard);
  const mb = $('#mdBtn'); if (mb) mb.addEventListener('click', exportMarkdown);
  const jb = $('#jsonBtn'); if (jb) jb.addEventListener('click', exportJSON);
  const pb = $('#printBtn'); if (pb) pb.addEventListener('click', () => window.print());
  const sb = $('#scriptBtn'); if (sb) sb.addEventListener('click', renderScript);
  const cs = $('#copyShare');
  if (cs) cs.addEventListener('click', () => {
    const text = (currentCard && currentCard.remote && currentCard.remote.share) || '';
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => toast('转发话术已复制')).catch(() => toast('复制失败，请手动选择'));
  });
  document.querySelectorAll('.sf-btn').forEach((b) => {
    b.addEventListener('click', () => {
      sourceFilter = b.dataset.k;
      rerender();
    });
  });
}

/* ---------- 辟谣话术（前端模板） ---------- */
function renderScript() {
  if (!currentCard) return;
  const c = currentCard, v = c.verdict;
  const top = c.sources[0];
  const refute = c.evidence.refute;
  const support = c.evidence.support;
  let body = '', action = '';
  if (v.level === 'false') {
    body = `关于「${c.input_text}」的说法，核查结论为【${v.label}】（置信度 ${v.confidence}%）。` +
      `${refute.length ? refute[0].point : v.summary}` +
      `${top ? `依据来源：${top.domain}。` : ''}请勿轻信或转发。`;
    action = '可直接转发本条澄清，或附上查证卡编号供对方核对。';
  } else if (v.level === 'uncertain') {
    body = `关于「${c.input_text}」的说法，目前核查结论为【${v.label}】（置信度 ${v.confidence}%），` +
      `即现有公开资料不足以证实或证伪。${v.summary}建议补充更具体的时间、地点、机构信息后再查证。`;
    action = '暂不定性，等待更多可核验来源。';
  } else if (v.level === 'partly_true' || v.level === 'mostly_true') {
    body = `关于「${c.input_text}」的说法，核查结论为【${v.label}】（置信度 ${v.confidence}%）：主体成立但表述存在偏差。${v.summary}`;
    action = '引用时建议附上原始出处，避免二次传播中被进一步简化。';
  } else {
    body = `关于「${c.input_text}」的说法，核查结论为【${v.label}】（置信度 ${v.confidence}%）。` +
      `${support.length ? support[0].point : v.summary}${top ? `来源：${top.domain}。` : ''}`;
    action = '可正常传播，建议同时附上来源链接便于他人复核。';
  }
  const MODE_TIP = {
    balanced: '建议以权威来源发布的原文为准。',
    strict: '当前为严谨模式，缺少权威来源时不轻易采信。',
    loose: '当前为宽松模式，证据门槛较低，结论仅供参考。',
  };
  const tip = MODE_TIP[$('#modeSelect').value] || MODE_TIP.balanced;
  body += tip;
  $('#scriptBox').innerHTML = `<div class="script-box">
    <div class="sb-head">一键辟谣话术<button class="btn-ghost tiny" id="copyScript">复制</button></div>
    <div class="sb-body">${esc(body)}</div>
    <div class="sb-action">使用建议：${esc(action)}</div>
    ${support.length || refute.length ? `<div class="sb-points">${(refute[0] ? `<div><b>关键反证：</b>${esc(refute[0].point)}</div>` : '')}${support[0] ? `<div><b>首选依据：</b>${esc(support[0].point)}</div>` : ''}${top ? `<div><b>首选来源：</b>${esc(top.title)}（${esc(top.domain)}）</div>` : ''}</div>` : ''}
  </div>`;
  $('#copyScript').addEventListener('click', () => {
    navigator.clipboard.writeText(body).then(() => toast('话术已复制')).catch(() => toast('复制失败，请手动选择'));
  });
}

/* ---------- 复制 ---------- */
function copyCard() {
  if (!currentCard) return;
  const c = currentCard;
  const lines = [
    `【查证卡 ${c.card_id}】`,
    `原文：${c.input_text}`,
    `结论：${c.verdict.label}（置信度 ${c.verdict.confidence}%）`,
    `说明：${c.verdict.summary}`,
    '',
    '— 支持依据 —',
    ...(c.evidence.support.length ? c.evidence.support.map((i, n) => `${n + 1}. ${i.point}（来源：${i.source_title} · ${i.source_domain}）`) : ['无']),
    '',
    '— 矛盾证据 —',
    ...(c.evidence.refute.length ? c.evidence.refute.map((i, n) => `${n + 1}. ${i.point}（来源：${i.source_title} · ${i.source_domain}）`) : ['无']),
    '',
    '— 来源清单 —',
    ...c.sources.map((s) => `[${s.id}] ${s.title} | ${s.domain} | ${s.published_at} | ${s.credibility_label} | ${s.url}`),
    '',
    `核查时间：${c.created_at_display}`
  ];
  navigator.clipboard.writeText(lines.join('\n'))
    .then(() => toast('查证卡已复制到剪贴板'))
    .catch(() => toast('复制失败，请手动选择文本'));
}

/* ---------- 导出 Markdown ---------- */
function buildMarkdown() {
  const c = currentCard;
  if (!c) return '';
  const L = [];
  L.push(`# 查证卡 ${c.card_id}`, '');
  L.push(`- 核查时间：${c.created_at_display}`);
  L.push(`- 查证引擎：${engineLabel(c)}`);
  L.push(`- 结论：**${c.verdict.label}**（置信度 ${c.verdict.confidence}%）`, '');
  L.push('## 待核实原文', '', c.input_text, '');
  L.push('## 结论说明', '', c.verdict.summary, '');
  if (c.arbitration && c.arbitration.applied) {
    L.push('## 本地 / 在线裁决', '', `- 裁决动作：${c.arbitration.action}`, `- 说明：${c.arbitration.reason}`, '');
  }
  if (c.verdict.breakdown && c.verdict.breakdown.length) {
    L.push('## 置信度构成', '', '| 项目 | 增减 |', '| --- | --- |');
    c.verdict.breakdown.forEach((b) => L.push(`| ${b.label} | ${b.delta >= 0 ? '+' : ''}${b.delta} |`));
    L.push('');
  }
  if (c.remote) {
    const rv = c.remote;
    L.push('', '## 在线核查详情', '');
    L.push(`- 在线结论：${rv.label}（置信度 ${rv.confidence}%） · ${rv.provider}`);
    if (rv.conclusion) L.push(`- 核查结论：${rv.conclusion}`);
    if (rv.accurate) L.push(`- 准确表述：${rv.accurate}`);
    if (rv.claims && rv.claims.length) {
      L.push('', `### 逐条事实点（${rv.claims.length}）`, '');
      rv.claims.forEach((x, n) => L.push(`${n + 1}. 【${x.label}】${x.text || ''}${x.note ? ` —— ${x.note}` : ''}`));
    }
    if (rv.evidences && rv.evidences.length) {
      L.push('', `### 在线证据（${rv.evidences.length}）`, '');
      rv.evidences.forEach((e, n) => L.push(
        `${n + 1}. [${e.title}](${e.url}) · ${e.type} · 证据分 ${Math.round(e.score)}${e.exact ? ' · 原样命中' : ''}${e.locator ? ` · ${e.locator}` : ''}`
      ));
    }
    if (rv.limitation) L.push('', `- 局限说明：${rv.limitation}`);
  }
  L.push(`## 支持依据（${c.evidence.support.length}）`, '');
  c.evidence.support.forEach((i, n) => L.push(`${n + 1}. ${i.point}（来源：[${i.source_title}](${i.source_url})）`));
  if (!c.evidence.support.length) L.push('无');
  L.push('');
  L.push(`## 矛盾证据（${c.evidence.refute.length}）`, '');
  c.evidence.refute.forEach((i, n) => L.push(`${n + 1}. ${i.point}（来源：[${i.source_title}](${i.source_url})）`));
  if (!c.evidence.refute.length) L.push('无');
  L.push('');
  L.push('## 来源清单', '');
  c.sources.forEach((s) => L.push(`- [${s.title}](${s.url}) · ${s.domain} · ${s.credibility_label} ${s.credibility_score} · ${s.published_at}`));
  L.push('', '## 风险与局限', '');
  c.risk_notes.forEach((r) => L.push(`- ${r}`));
  return L.join('\n');
}
function exportMarkdown() {
  if (!currentCard) return;
  download(`${currentCard.card_id}.md`, buildMarkdown(), 'text/markdown;charset=utf-8');
  toast('Markdown 报告已导出');
}
function exportJSON() {
  if (!currentCard) return;
  download(`${currentCard.card_id}.json`, JSON.stringify(currentCard, null, 2), 'application/json');
  toast('JSON 数据已导出');
}

/* ---------- 导出图片 ---------- */
async function exportCard() {
  if (!currentCard) return;
  const c = currentCard;
  const canvas = document.createElement('canvas');
  const W = 900, pad = 40;
  const ctx = canvas.getContext('2d');
  const wrap = (text, maxW, font) => {
    ctx.font = font;
    const out = []; let line = '';
    for (const ch of String(text)) {
      if (ctx.measureText(line + ch).width > maxW) { out.push(line); line = ch; }
      else line += ch;
    }
    if (line) out.push(line);
    return out;
  };
  const blocks = [];
  const F = '15px "Microsoft YaHei", sans-serif';
  blocks.push({ type: 'title', text: `查证卡 ${c.card_id}` });
  blocks.push({ type: 'verdict', text: `${c.verdict.label} · 置信度 ${c.verdict.confidence}%`, color: c.verdict.color });
  blocks.push({ type: 'label', text: '原文' });
  wrap(c.input_text, W - pad * 2, F).forEach((l) => blocks.push({ type: 'text', text: l }));
  blocks.push({ type: 'label', text: '结论说明' });
  wrap(c.verdict.summary, W - pad * 2, F).forEach((l) => blocks.push({ type: 'text', text: l }));
  blocks.push({ type: 'label', text: `支持依据（${c.evidence.support.length}）` });
  (c.evidence.support.length ? c.evidence.support : [{ point: '未发现支持证据', source_title: '', source_domain: '' }])
    .forEach((i) => {
      wrap(`• ${i.point}`, W - pad * 2, F).forEach((l) => blocks.push({ type: 'text', text: l }));
      if (i.source_title) blocks.push({ type: 'sub', text: `  来源：${i.source_title} · ${i.source_domain}` });
    });
  blocks.push({ type: 'label', text: `矛盾证据（${c.evidence.refute.length}）` });
  (c.evidence.refute.length ? c.evidence.refute : [{ point: '未发现矛盾证据', source_title: '', source_domain: '' }])
    .forEach((i) => {
      wrap(`• ${i.point}`, W - pad * 2, F).forEach((l) => blocks.push({ type: 'text', text: l }));
      if (i.source_title) blocks.push({ type: 'sub', text: `  来源：${i.source_title} · ${i.source_domain}` });
    });
  blocks.push({ type: 'label', text: '来源清单' });
  c.sources.forEach((s) => {
    wrap(`[${s.id}] ${s.title}`, W - pad * 2, F).forEach((l) => blocks.push({ type: 'text', text: l }));
    blocks.push({ type: 'sub', text: `  ${s.domain} · ${s.published_at} · ${s.credibility_label}` });
  });
  blocks.push({ type: 'sub', text: `核查时间：${c.created_at_display} · 查证台 VERITAS` });
  let y = pad;
  const heights = blocks.map((b) => {
    if (b.type === 'title') return 40;
    if (b.type === 'verdict') return 52;
    if (b.type === 'label') return 34;
    if (b.type === 'sub') return 24;
    return 26;
  });
  const H = heights.reduce((a, b) => a + b, 0) + pad;
  canvas.width = W; canvas.height = H;
  const light = document.documentElement.getAttribute('data-theme') === 'light';
  ctx.fillStyle = light ? '#FFFFFF' : '#070B14'; ctx.fillRect(0, 0, W, H);
  ctx.strokeStyle = light ? 'rgba(20,60,120,.35)' : 'rgba(0,229,192,.35)'; ctx.lineWidth = 2;
  ctx.strokeRect(12, 12, W - 24, H - 24);
  blocks.forEach((b, i) => {
    if (b.type === 'title') { ctx.fillStyle = light ? '#0B5FFF' : '#00E5C0'; ctx.font = 'bold 22px "Microsoft YaHei"'; }
    else if (b.type === 'verdict') { ctx.fillStyle = light ? '#111827' : b.color; ctx.font = 'bold 26px "Microsoft YaHei"'; }
    else if (b.type === 'label') { ctx.fillStyle = light ? '#0B5FFF' : '#00E5C0'; ctx.font = 'bold 14px "Microsoft YaHei"'; }
    else if (b.type === 'sub') { ctx.fillStyle = light ? '#6B7280' : '#7A8CA6'; ctx.font = '12px "Microsoft YaHei"'; }
    else { ctx.fillStyle = light ? '#111827' : '#E6F1FF'; ctx.font = '15px "Microsoft YaHei"'; }
    y += heights[i];
    ctx.fillText(b.text, pad, y - 8);
  });
  canvas.toBlob((blob) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `${c.card_id}.png`; a.click();
    URL.revokeObjectURL(url);
    toast('查证卡图片已导出');
  });
}

/* ---------- 历史记录 ---------- */
let historyLevelFilter = 'all';
async function loadHistory() {
  try {
    const r = await fetch(`${API_BASE}/api/history`);
    const d = await r.json();
    const recs = d.records || [];
    historyCache.length = 0;
    historyCache.push(...recs);
    if (!recs.length) { $('#historyPanel').style.display = 'none'; return; }
    $('#historyPanel').style.display = 'block';
    renderHistory();
  } catch (e) { /* 静默失败 */ }
}

function readFavs() {
  try { return JSON.parse(localStorage.getItem(FAV_KEY) || '[]'); } catch (e) { return []; }
}
function renderHistory() {
  const kw = ($('#historySearch')?.value || '').trim();
  let recs = historyCache;
  if (kw) recs = recs.filter((r) => (r.input_text || '').includes(kw));
  if (historyLevelFilter !== 'all') recs = recs.filter((r) => r.label === historyLevelFilter);
  $('#historyCount').textContent = `${recs.length} / ${historyCache.length} 条`;
  const labelColor = { '属实': '#22D39A', '不实': '#FF4D6D', '存疑': '#FFB020', '基本属实': '#3DDC97', '部分属实': '#7ED957' };
  const favs = readFavs();
  recs.sort((a, b) => (favs.includes(b.card_id) ? 1 : 0) - (favs.includes(a.card_id) ? 1 : 0));
  $('#historyList').innerHTML = recs.slice(0, 20).map((r) => `
    <div class="history-item" data-text="${esc(r.input_text)}" data-id="${esc(r.card_id)}">
      <span class="h-label" style="color:${labelColor[r.label] || '#8FA3BF'};background:${(labelColor[r.label] || '#8FA3BF')}22">${esc(r.label)}</span>
      <span class="h-text">${esc(r.input_text)}</span>
      <span class="h-time">${esc(r.created_at)}</span>
      <span class="h-fav ${favs.includes(r.card_id) ? 'on' : ''}" data-fav="${esc(r.card_id)}">${favs.includes(r.card_id) ? '★' : '☆'}</span>
    </div>`).join('') || '<div class="empty-hint">没有匹配的记录</div>';
  document.querySelectorAll('.history-item').forEach((el) => {
    el.addEventListener('click', (e) => {
      if (e.target.classList.contains('h-fav')) {
        const id = e.target.dataset.fav;
        const list = readFavs();
        const pos = list.indexOf(id);
        if (pos >= 0) list.splice(pos, 1); else list.unshift(id);
        try { localStorage.setItem(FAV_KEY, JSON.stringify(list.slice(0, 50))); } catch (err) { /* 忽略 */ }
        renderHistory();
        return;
      }
      claimInput.value = el.dataset.text;
      charCount.textContent = claimInput.value.length;
      claimInput.focus();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  });
}
$('#historySearch')?.addEventListener('input', renderHistory);
document.querySelectorAll('.hl-filter').forEach((b) => {
  b.addEventListener('click', () => {
    document.querySelectorAll('.hl-filter').forEach((x) => x.classList.remove('on'));
    b.classList.add('on');
    historyLevelFilter = b.dataset.level;
    renderHistory();
  });
});
initTheme();
loadHistory();
