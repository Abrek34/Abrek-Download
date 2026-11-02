'use strict';

const isFirefox = typeof browser !== 'undefined' && !!browser.runtime;
const ext = isFirefox ? browser : chrome;
const API = 'http://127.0.0.1:8765';

const state = {
  tab: null,
  record: { pageUrl: '', pageTitle: '', items: [] },
  settings: { autoSend: true, quality: 'best' },
  online: false,
  busy: false,
};

const el = (id) => document.getElementById(id);

function call(fn, ...args) {
  if (isFirefox) {
    try {
      return Promise.resolve(fn(...args));
    } catch (error) {
      return Promise.reject(error);
    }
  }
  return new Promise((resolve, reject) => {
    try {
      fn(...args, (result) => {
        const error = chrome.runtime.lastError;
        if (error) reject(new Error(error.message));
        else resolve(result);
      });
    } catch (error) {
      reject(error);
    }
  });
}

async function fetchJson(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      cache: 'no-store',
      credentials: 'omit',
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

function postJson(path, body) {
  return fetchJson(API + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

function isHttp(url) {
  return typeof url === 'string' && /^https?:\/\//i.test(url);
}

function hostname(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}

function fileName(url) {
  try {
    const parsed = new URL(url);
    return decodeURIComponent(parsed.pathname.split('/').filter(Boolean).pop() || '');
  } catch {
    return '';
  }
}

function formatSize(bytes) {
  const value = Number(bytes) || 0;
  if (value <= 0) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let index = 0;
  let amount = value;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  return `${amount >= 10 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
}

function kindLabel(kind) {
  return { hls: 'HLS', dash: 'DASH', page: 'SAYFA', direct: 'MEDYA' }[kind] || 'MEDYA';
}

function setStatus(mode, text) {
  const status = el('status');
  status.className = `status ${mode}`;
  el('statusText').textContent = text;
}

function toast(message, error = false) {
  const node = el('toast');
  node.textContent = message;
  node.className = `toast show${error ? ' error' : ''}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {
    node.className = 'toast';
  }, 3800);
}

function updateButtons() {
  const restricted = !state.tab || !isHttp(state.tab.url);
  el('downloadPage').disabled = !state.online || restricted || state.busy;
  el('sendAll').disabled = !state.online || state.busy || state.record.items.length === 0;
  el('clear').disabled = state.busy || state.record.items.length === 0;
  document.querySelectorAll('.item-actions button[data-action="download"], .item-actions button[data-action="send"]').forEach((button) => {
    button.disabled = !state.online || state.busy;
  });
}

async function saveRecord() {
  if (!state.tab) return;
  await call(ext.storage.local.set.bind(ext.storage.local), { [`tab:${state.tab.id}`]: state.record });
}

async function saveSettings() {
  await call(ext.storage.local.set.bind(ext.storage.local), { settings: state.settings });
}

async function markSent(url) {
  for (const item of state.record.items) {
    if (item.url === url) item.sent = true;
  }
  await saveRecord();
  render();
}

function notifyBackground(message) {
  try {
    const result = ext.runtime.sendMessage(message);
    if (result && typeof result.catch === 'function') result.catch(() => {});
  } catch {
    // Arka plan yoksa sessizce geç.
  }
}

async function checkHealth() {
  try {
    const health = await fetchJson(`${API}/api/health`);
    state.online = true;
    setStatus('online', `Bağlı · v${health.version || ''}`.trim());
  } catch {
    state.online = false;
    setStatus('offline', 'Uygulama kapalı');
  }
  updateButtons();
}

function createButton(label, className, action, handler) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = className;
  button.textContent = label;
  if (action) button.dataset.action = action;
  button.addEventListener('click', handler);
  return button;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast('Bağlantı kopyalandı.');
  } catch {
    const area = document.createElement('textarea');
    area.value = text;
    document.body.appendChild(area);
    area.select();
    try {
      document.execCommand('copy');
      toast('Bağlantı kopyalandı.');
    } catch {
      toast('Bağlantı kopyalanamadı.', true);
    }
    area.remove();
  }
}

function renderItem(item) {
  const article = document.createElement('article');
  article.className = 'item';

  const top = document.createElement('div');
  top.className = 'item-top';
  const kind = document.createElement('span');
  kind.className = `kind ${item.kind || 'direct'}`;
  kind.textContent = kindLabel(item.kind);
  const size = document.createElement('span');
  size.className = 'size';
  size.textContent = formatSize(item.size);
  top.append(kind, size);

  const title = document.createElement('div');
  title.className = 'item-title';
  title.textContent = item.title || item.pageTitle || fileName(item.url) || 'Video';
  title.title = item.url;

  const meta = document.createElement('div');
  meta.className = 'item-meta';
  const name = fileName(item.url);
  const pieces = [hostname(item.pageUrl || item.url)];
  if (name && name.length < 55) pieces.push(name);
  if (item.sent) pieces.push('✓ gönderildi');
  meta.textContent = pieces.filter(Boolean).join(' · ');

  const actions = document.createElement('div');
  actions.className = 'item-actions';
  const download = createButton('İndir', 'download', 'download', () => downloadItem(item));
  const send = createButton('Gönder', 'secondary', 'send', () => sendItem(item));
  const copy = createButton('Kopyala', 'link copy', '', () => copyText(item.url));
  actions.append(download, send, copy);

  article.append(top, title, meta, actions);
  return article;
}

function render() {
  const tab = state.tab;
  const pageTitle = state.record.pageTitle || (tab && tab.title) || 'Başlıksız sayfa';
  el('pageTitle').textContent = pageTitle;
  el('pageUrl').textContent = (tab && tab.url) || state.record.pageUrl || '';
  el('count').textContent = String(state.record.items.length);

  const list = el('list');
  list.textContent = '';
  for (const item of state.record.items) {
    list.appendChild(renderItem(item));
  }

  const empty = el('empty');
  empty.classList.toggle('hidden', state.record.items.length > 0);
  if (state.record.items.length === 0) {
    const text = empty.querySelector('p');
    const sub = empty.querySelector('span');
    if (tab && !isHttp(tab.url)) {
      text.textContent = 'Bu sayfada video yakalanamaz.';
      sub.textContent = 'Normal bir web sayfası açıp videoyu oynatın.';
    } else {
      text.textContent = 'Bu sekmede henüz video yakalanmadı.';
      sub.textContent = 'Videoyu oynatın; ağdan gelen medya burada görünecek.';
    }
  }

  el('quality').value = state.settings.quality || 'best';
  el('autoSend').checked = state.settings.autoSend !== false;
  updateButtons();
}

async function downloadPage() {
  if (!state.tab || !isHttp(state.tab.url)) {
    toast('Bu sayfa indirilemez.', true);
    return;
  }
  if (!state.online) {
    toast('Önce Abrek Download uygulamasını açın.', true);
    return;
  }
  state.busy = true;
  updateButtons();
  try {
    const result = await postJson('/api/download', {
      url: state.tab.url,
      page_url: state.tab.url,
      title: state.tab.title || '',
      kind: 'page',
      quality: state.settings.quality || 'best',
    });
    toast(result.duplicate ? 'Bu sayfa zaten kuyrukta.' : 'İndirme kuyruğuna eklendi.');
  } catch {
    state.online = false;
    setStatus('offline', 'Uygulama kapalı');
    toast('Abrek Download’ya ulaşılamadı. Uygulama açık mı?', true);
  } finally {
    state.busy = false;
    updateButtons();
  }
}

async function downloadItem(item) {
  if (!state.online) {
    toast('Önce Abrek Download uygulamasını açın.', true);
    return;
  }
  state.busy = true;
  updateButtons();
  try {
    const result = await postJson('/api/download', {
      url: item.url,
      page_url: item.pageUrl || '',
      title: item.title || item.pageTitle || '',
      kind: item.kind || 'direct',
      referer: item.referer || item.pageUrl || '',
      quality: state.settings.quality || 'best',
    });
    await markSent(item.url);
    toast(result.duplicate ? 'Bu video zaten kuyrukta.' : 'İndirme kuyruğuna eklendi.');
  } catch {
    state.online = false;
    setStatus('offline', 'Uygulama kapalı');
    toast('Abrek Download’ya ulaşılamadı. Uygulama açık mı?', true);
  } finally {
    state.busy = false;
    updateButtons();
  }
}

async function sendItem(item) {
  if (!state.online) {
    toast('Önce Abrek Download uygulamasını açın.', true);
    return;
  }
  state.busy = true;
  updateButtons();
  try {
    await postJson('/api/captures', {
      url: item.url,
      page_url: item.pageUrl || '',
      page_title: item.pageTitle || '',
      title: item.title || item.pageTitle || '',
      content_type: item.contentType || '',
      size: Number(item.size) || 0,
      kind: item.kind || 'direct',
      referer: item.referer || item.pageUrl || '',
      tab_id: state.tab ? state.tab.id : -1,
    });
    await markSent(item.url);
    toast('Video uygulamaya gönderildi.');
  } catch {
    state.online = false;
    setStatus('offline', 'Uygulama kapalı');
    toast('Abrek Download’ya ulaşılamadı. Uygulama açık mı?', true);
  } finally {
    state.busy = false;
    updateButtons();
  }
}

async function sendAll() {
  if (!state.online) {
    toast('Önce Abrek Download uygulamasını açın.', true);
    return;
  }
  if (!state.record.items.length) {
    toast('Gönderilecek video yok.');
    return;
  }
  state.busy = true;
  updateButtons();
  let sent = 0;
  for (const item of state.record.items) {
    try {
      await postJson('/api/captures', {
        url: item.url,
        page_url: item.pageUrl || '',
        page_title: item.pageTitle || '',
        title: item.title || item.pageTitle || '',
        content_type: item.contentType || '',
        size: Number(item.size) || 0,
        kind: item.kind || 'direct',
        referer: item.referer || item.pageUrl || '',
        tab_id: state.tab ? state.tab.id : -1,
      });
      item.sent = true;
      sent += 1;
    } catch {
      state.online = false;
      break;
    }
  }
  await saveRecord();
  state.busy = false;
  render();
  if (sent) {
    toast(`${sent} video uygulamaya gönderildi.`);
  } else {
    setStatus('offline', 'Uygulama kapalı');
    toast('Abrek Download’ya ulaşılamadı. Uygulama açık mı?', true);
  }
}

async function clearList() {
  state.record.items = [];
  await saveRecord();
  if (state.tab) {
    try {
      await call(ext.action.setBadgeText.bind(ext.action), { tabId: state.tab.id, text: '' });
    } catch {
      // Sekme kapanmış olabilir.
    }
  }
  render();
  toast('Liste temizlendi.');
}

async function init() {
  const tabs = await call(ext.tabs.query.bind(ext.tabs), { active: true, currentWindow: true });
  state.tab = (tabs && tabs[0]) || null;
  if (!state.tab) {
    setStatus('offline', 'Sekme bulunamadı');
    render();
    return;
  }

  const key = `tab:${state.tab.id}`;
  const data = await call(ext.storage.local.get.bind(ext.storage.local), ['settings', key]);
  state.settings = Object.assign({ autoSend: true, quality: 'best' }, data.settings || {});
  const stored = data[key];
  state.record = stored && typeof stored === 'object'
    ? {
        pageUrl: stored.pageUrl || state.tab.url || '',
        pageTitle: stored.pageTitle || state.tab.title || '',
        items: Array.isArray(stored.items) ? stored.items : [],
      }
    : { pageUrl: state.tab.url || '', pageTitle: state.tab.title || '', items: [] };

  if (state.record.pageUrl && state.tab.url && state.record.pageUrl !== state.tab.url) {
    state.record = { pageUrl: state.tab.url, pageTitle: state.tab.title || '', items: [] };
    await saveRecord();
  }

  render();
  checkHealth();
  notifyBackground({ type: 'retry-pending' });
  setInterval(checkHealth, 5000);
}

el('downloadPage').addEventListener('click', downloadPage);
el('sendAll').addEventListener('click', sendAll);
el('clear').addEventListener('click', clearList);

el('quality').addEventListener('change', async (event) => {
  state.settings.quality = event.target.value;
  await saveSettings();
  const labels = { best: 'En iyi kalite', '1080': '1080p', '720': '720p', '480': '480p', audio: 'Ses (MP3)' };
  toast(`Kalite: ${labels[state.settings.quality] || state.settings.quality}`);
});

el('autoSend').addEventListener('change', async (event) => {
  state.settings.autoSend = event.target.checked;
  await saveSettings();
  if (state.settings.autoSend) {
    toast('Otomatik gönderim açıldı.');
    if (state.record.items.length && state.online) await sendAll();
  } else {
    toast('Otomatik gönderim kapatıldı.');
  }
});

ext.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local' || !state.tab) return;
  const key = `tab:${state.tab.id}`;
  if (changes[key]) {
    const record = changes[key].newValue;
    state.record = record && typeof record === 'object'
      ? {
          pageUrl: record.pageUrl || state.record.pageUrl,
          pageTitle: record.pageTitle || state.record.pageTitle,
          items: Array.isArray(record.items) ? record.items : [],
        }
      : { pageUrl: state.record.pageUrl, pageTitle: state.record.pageTitle, items: [] };
    render();
  }
  if (changes.settings) {
    state.settings = Object.assign({ autoSend: true, quality: 'best' }, changes.settings.newValue || {});
    render();
  }
});

init().catch(() => {
  setStatus('offline', 'Başlatılamadı');
  toast('Eklenti başlatılamadı. Sayfayı yenileyip tekrar deneyin.', true);
});
