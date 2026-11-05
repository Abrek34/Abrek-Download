'use strict';

/*
 * Abrek Download — arka plan yakalayıcı
 * Ağ isteklerini ve DOM'daki <video> kaynaklarını izler, bulduklarını
 * 127.0.0.1:8765 üzerindeki Abrek Download uygulamasına gönderir.
 */

const isFirefox = typeof browser !== 'undefined' && !!browser.runtime;
const ext = isFirefox ? browser : chrome;

const API_BASE = 'http://127.0.0.1:8765';
const API_CAPTURES = API_BASE + '/api/captures';
const MAX_ITEMS_PER_TAB = 30;
const MAX_PENDING = 100;
const MIN_DIRECT_SIZE = 50 * 1024;

const MEDIA_EXT = /\.(mp4|webm|mkv|mov|m4v|avi|flv|ogv|3gp|mp3|m4a|aac|ogg|opus|wav|flac)(?:$|[?#])/i;
const MANIFEST_EXT = /\.(m3u8|mpd)(?:$|[?#])/i;
const SKIP_EXT = /\.(ts|m4s|vtt|srt|jpg|jpeg|png|gif|webp|svg|css|js|json|woff2?|html?)(?:$|[?#])/i;
const SEGMENT_HINT = /(?:^|[\/_.-])(seg|segment|chunk|frag|fragment|part)[-_]?\d+(?:[\/_.-]|$)/i;
const BLOCKED_HOSTS = /(^|\.)googlevideo\.com$/i;

const tabInfoCache = new Map();
const locks = new Map();
let capturePausedCached = false;
let lastCapturePausedCheck = 0;

async function isCapturePaused() {
  const now = Date.now();
  if (now - lastCapturePausedCheck < 10000) return capturePausedCached;
  lastCapturePausedCheck = now;
  try {
    const health = await fetchJson(API_BASE + '/api/health');
    capturePausedCached = !!(health && health.capture_paused);
  } catch {
    // Uygulama kapalıysa yakalama devam etsin.
  }
  return capturePausedCached;
}

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

function withLock(key, fn) {
  const previous = locks.get(key) || Promise.resolve();
  const next = previous.then(fn, fn);
  locks.set(key, next.catch(() => {}));
  return next;
}

function tabKey(tabId) {
  return `tab:${tabId}`;
}

async function storageGet(key) {
  const result = await call(ext.storage.local.get.bind(ext.storage.local), key);
  return result || {};
}

async function storageSet(value) {
  await call(ext.storage.local.set.bind(ext.storage.local), value);
}

async function storageRemove(key) {
  await call(ext.storage.local.remove.bind(ext.storage.local), key);
}

async function readTab(tabId) {
  const key = tabKey(tabId);
  const data = await storageGet(key);
  const record = data[key];
  if (!record || typeof record !== 'object') {
    return { pageUrl: '', pageTitle: '', items: [] };
  }
  return {
    pageUrl: record.pageUrl || '',
    pageTitle: record.pageTitle || '',
    items: Array.isArray(record.items) ? record.items.filter(Boolean) : [],
  };
}

async function writeTab(tabId, record) {
  await storageSet({ [tabKey(tabId)]: record });
}

async function readPending() {
  const data = await storageGet('pending');
  return Array.isArray(data.pending) ? data.pending.filter(Boolean) : [];
}

async function writePending(items) {
  await storageSet({ pending: items.slice(0, MAX_PENDING) });
}

async function readSettings() {
  const data = await storageGet('settings');
  return Object.assign({ autoSend: true, quality: 'best' }, data.settings || {});
}

function normalizeUrl(url) {
  try {
    const parsed = new URL(url);
    parsed.hash = '';
    return parsed.href;
  } catch {
    return url;
  }
}

function shouldIgnore(url) {
  if (!/^https?:/i.test(url)) return true;
  if (url.includes('127.0.0.1:8765') || url.includes('localhost:8765')) return true;
  if (SKIP_EXT.test(url)) return true;
  if (SEGMENT_HINT.test(url)) return true;
  try {
    const host = new URL(url).hostname;
    if (BLOCKED_HOSTS.test(host)) return true;
  } catch {
    return true;
  }
  return false;
}

function isVideoPageUrl(url) {
  if (!url || typeof url !== 'string') return false;
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\./, '');
    if (host === 'youtube.com' || host === 'm.youtube.com') {
      return u.pathname === '/watch' || u.pathname.startsWith('/shorts/') || u.pathname.startsWith('/live/');
    }
    if (host === 'youtu.be') return true;
    if (host === 'vimeo.com') return /^\/\d+/.test(u.pathname);
    if (host === 'dailymotion.com') return u.pathname.startsWith('/video/');
    if (host === 'tiktok.com') return u.pathname.includes('/video/');
    if (host === 'twitter.com' || host === 'x.com') return u.pathname.includes('/status/');
    if (host === 'instagram.com') return u.pathname.startsWith('/reel/') || u.pathname.startsWith('/p/');
  } catch {}
  return false;
}

async function checkAndAddVideoPage(tabId, pageUrl, pageTitle, hasVideo = false) {
  if (await isCapturePaused()) return;
  if (!isVideoPageUrl(pageUrl) && !hasVideo) return;
  await withLock(`tab:${tabId}`, async () => {
    const record = await readTab(tabId);
    record.pageUrl = pageUrl;
    if (pageTitle) record.pageTitle = pageTitle;

    const existing = record.items.find((item) => item.url === pageUrl);
    const cleanTitle = (pageTitle || record.pageTitle || 'YouTube Video').replace(/\s*-\s*YouTube\s*$/i, '').trim();

    if (!existing) {
      const item = {
        url: pageUrl,
        pageUrl: pageUrl,
        pageTitle: cleanTitle,
        title: cleanTitle,
        kind: 'page',
        label: pageUrl.includes('youtu') ? 'YOUTUBE' : 'SAYFA',
        contentType: 'text/html',
        size: 0,
        referer: pageUrl,
        tabId: tabId,
        sent: false,
      };
      record.items.unshift(item);
      record.items = record.items.slice(0, MAX_ITEMS_PER_TAB);
      await writeTab(tabId, record);
      await setBadge(tabId, record.items.length);

      const settings = await readSettings();
      if (settings.autoSend !== false) {
        try {
          await postCapture(item, tabId);
          item.sent = true;
          await writeTab(tabId, record);
        } catch {
          await addPending(item, tabId);
        }
      }
    } else if (cleanTitle && (!existing.title || existing.title === 'YouTube Video')) {
      existing.title = cleanTitle;
      existing.pageTitle = cleanTitle;
      await writeTab(tabId, record);
    }
  });
}

function classify(contentType, url) {
  const ct = String(contentType || '').toLowerCase().split(';')[0].trim();
  if (/\.m3u8(?:$|[?#])/i.test(url) || /\/m3u\//i.test(url) || ct.includes('mpegurl')) return 'hls';
  if (/\.mpd(?:$|[?#])/i.test(url) || ct.includes('dash+xml')) return 'dash';
  if (ct.startsWith('video/') || ct.startsWith('audio/') || MEDIA_EXT.test(url)) return 'direct';
  // Bazı CDN'ler video/mp4 yerine application/octet-stream döner; uzantı varsa yakala.
  if (/\.(mp4|webm|mkv|mov|m4v|avi|flv|ogv|mp3|m4a|aac|ogg|opus|wav|flac)(?:$|[?#])/i.test(url)) return 'direct';
  return null;
}

function mediaLabel(item) {
  const ct = String(item.contentType || '').toLowerCase();
  const url = String(item.url || '');
  if (item.kind === 'hls' || item.kind === 'dash') {
    const m = url.match(/(2160|1440|1080|720|480|360|240)/);
    if (m) return 'AKIŞ ' + m[1] + 'p';
    return item.kind === 'dash' ? 'DASH' : 'AKIŞ';
  }
  if (ct.startsWith('audio/') || /\.(mp3|m4a|aac|ogg|opus|wav|flac)(?:$|[?#])/.test(url.toLowerCase())) return 'SES';
  if (ct.startsWith('video/') || /\.(mp4|webm|mkv|mov|m4v|avi|flv|ogv)(?:$|[?#])/.test(url.toLowerCase())) return 'GÖRÜNTÜ';
  return 'MEDYA';
}

function titleFromUrl(url) {
  try {
    const parsed = new URL(url);
    const name = decodeURIComponent(parsed.pathname.split('/').filter(Boolean).pop() || '');
    return name || parsed.hostname || 'Video';
  } catch {
    return 'Video';
  }
}

async function getTabInfo(tabId, initiator) {
  const now = Date.now();
  const cached = tabInfoCache.get(tabId);
  if (cached && now - cached.at < 5000) return cached.info;
  try {
    const tab = await call(ext.tabs.get.bind(ext.tabs), tabId);
    const info = {
      pageUrl: tab.url || initiator || '',
      pageTitle: tab.title || '',
    };
    tabInfoCache.set(tabId, { at: now, info });
    return info;
  } catch {
    return { pageUrl: initiator || '', pageTitle: '' };
  }
}

async function setBadge(tabId, count) {
  try {
    await call(ext.action.setBadgeText.bind(ext.action), {
      tabId,
      text: count > 0 ? String(Math.min(count, 99)) : '',
    });
    if (count > 0) {
      await call(ext.action.setBadgeBackgroundColor.bind(ext.action), { tabId, color: '#4f8cff' });
    }
  } catch {
    // Sekme kapanmış olabilir.
  }
}

async function fetchJson(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const settings = await readSettings();
    const headers = { ...options.headers };
    if (settings.apiToken) headers['X-Abrek-Token'] = settings.apiToken;
    const response = await fetch(url, {
      ...options,
      headers,
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

async function postCapture(item, tabId) {
  const body = {
    url: item.url,
    page_url: item.pageUrl || '',
    page_title: item.pageTitle || '',
    title: item.title || item.pageTitle || '',
    content_type: item.contentType || '',
    size: Number(item.size) || 0,
    kind: item.kind || 'direct',
    referer: item.referer || item.pageUrl || '',
    tab_id: tabId,
  };
  return fetchJson(API_CAPTURES, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

async function markSent(tabId, url) {
  if (!Number.isInteger(tabId) || tabId < 0) return;
  await withLock(`tab:${tabId}`, async () => {
    const record = await readTab(tabId);
    let changed = false;
    for (const item of record.items) {
      if (item.url === url && !item.sent) {
        item.sent = true;
        changed = true;
      }
    }
    if (changed) await writeTab(tabId, record);
  });
}

async function addPending(item, tabId) {
  await withLock('pending', async () => {
    const pending = await readPending();
    if (!pending.some((entry) => entry.url === item.url)) {
      pending.unshift({ ...item, tabId, addedAt: Date.now() });
    }
    await writePending(pending);
  });
}

async function removePending(url) {
  await withLock('pending', async () => {
    const pending = await readPending();
    const filtered = pending.filter((entry) => entry.url !== url);
    if (filtered.length !== pending.length) await writePending(filtered);
  });
}

async function retryPending() {
  // Kullanıcı yakalamayı duraklattıysa bekleyenler gönderilmesin; sıra
  // korunur ve yakalama yeniden açıldığında sonraki alarmda denenir.
  if (await isCapturePaused()) return;
  const pending = await readPending();
  if (!pending.length) return;
  const remaining = [];
  for (const entry of pending) {
    try {
      await postCapture(entry, Number(entry.tabId));
      await markSent(Number(entry.tabId), entry.url);
    } catch {
      remaining.push(entry);
    }
  }
  await writePending(remaining);
}

async function handleDetection(tabId, rawUrl, contentType, size, source, initiator, requestType, contentRange = '') {
  if (!Number.isInteger(tabId) || tabId < 0) return;
  if (await isCapturePaused()) return;
  const url = normalizeUrl(rawUrl);
  if (shouldIgnore(url)) return;

  let kind = classify(contentType, url);
  // Tarayıcının "media" olarak işaretlediği istekler video/medya kaynağıdır;
  // uzantı veya content-type eksik olsa bile yakala (film siteleri vb.).
  if (!kind && requestType === 'media') kind = 'direct';
  // Film siteleri videoyu octet-stream veya uzantısız URL ile sunabilir.
  if (!kind) {
    const ct = String(contentType || '').toLowerCase();
    if (ct.includes('octet-stream') || ct.includes('binary') || ct === '' || ct.includes('text/plain')) {
      if (/video|stream|play|master|playlist|media|cdn|m3u8|m3u|mpd/i.test(url)) kind = 'direct';
    }
  }
  // /m3u/ yolu manifest (HLS) olarak değerlendir.
  if (!kind && /\/m3u\//i.test(url)) kind = 'hls';
  // vidmixi gibi oynatıcı hostlarından gelen istekleri medya olarak değerlendir.
  if (!kind) {
    try {
      if (/vidmixi\.com/i.test(new URL(url).hostname)) kind = 'direct';
    } catch {}
  }
  if (!kind) return;
  if (kind === 'direct') {
    const isVideoContentType = String(contentType || '').toLowerCase().startsWith('video/');
    if (!isVideoContentType && size > 0 && size < MIN_DIRECT_SIZE && !contentRange) return;
  }

  const info = await getTabInfo(tabId, initiator);
  const pageUrl = info.pageUrl || initiator || '';
  const pageTitle = info.pageTitle || '';

  // Instagram tek bir Reels sayfasında onlarca varyant/prefetch medya isteği
  // üretir. Aynı sayfa için daha önce yakalama varsa yenilerini ekleme; böylece
  // "Yakalananlar" listesi onlarca aynı sayfa girdisiyle dolmaz.
  const pageUrlNorm = String(pageUrl || '').toLowerCase();
  let isInstagramSingleMedia = false;
  try {
    isInstagramSingleMedia =
      /(^|\.)instagram\.com$/.test(new URL(pageUrl || 'http://x').hostname.replace(/^www\./, '')) &&
      (/\/reels?\//.test(pageUrlNorm) || /\/p\//.test(pageUrlNorm));
  } catch {
    isInstagramSingleMedia = false;
  }
  const item = {
    url,
    kind,
    contentType: contentType || '',
    size: Number(size) || 0,
    pageUrl,
    pageTitle,
    title: pageTitle || titleFromUrl(url),
    referer: pageUrl,
    source: source || 'network',
    time: Date.now(),
    sent: false,
  };

  let autoSend = true;
  let skipCapture = false;
  await withLock(`tab:${tabId}`, async () => {
    const record = await readTab(tabId);
    if (record.pageUrl && pageUrl && record.pageUrl !== pageUrl) {
      record.items = [];
    }
    if (pageUrl) record.pageUrl = pageUrl;
    if (pageTitle) record.pageTitle = pageTitle;

    const existing = record.items.find((entry) => entry.url === url);
    if (existing) {
      if (size) existing.size = Number(size);
      if (contentType) existing.contentType = contentType;
      if (kind) existing.kind = kind;
      if (pageTitle) {
        existing.pageTitle = pageTitle;
        existing.title = pageTitle;
      }
      autoSend = !existing.sent;
    } else {
      // Instagram tekil medya sayfalarında aynı sayfa için ikinci yakalamayı engelle.
      if (isInstagramSingleMedia && record.items.some((entry) => entry.pageUrl === pageUrl)) {
        skipCapture = true;
        return;
      }
      record.items.unshift(item);
      record.items = record.items.slice(0, MAX_ITEMS_PER_TAB);
    }
    await writeTab(tabId, record);
    await setBadge(tabId, record.items.length);
    const settings = await readSettings();
    autoSend = autoSend && settings.autoSend !== false;
  });

  if (skipCapture) return;

  if (autoSend) {
    try {
      await postCapture(item, tabId);
      await markSent(tabId, url);
      await removePending(url);
    } catch {
      await addPending(item, tabId);
    }
  }
}

function headerValue(headers, name) {
  if (!Array.isArray(headers)) return '';
  const wanted = name.toLowerCase();
  const found = headers.find((header) => String(header.name || '').toLowerCase() === wanted);
  return found ? String(found.value || '') : '';
}

// ------------------------------------------------------------------ network hooks
ext.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (details.tabId < 0) return;
    const isManifest = MANIFEST_EXT.test(details.url) || /\/m3u\//i.test(details.url);
    if (!isManifest && details.type !== 'media') return;
    handleDetection(
      details.tabId,
      details.url,
      '',
      0,
      'request',
      details.initiator || '',
      details.type,
    ).catch(() => {});
  },
  {
    urls: ['<all_urls>'],
    types: ['media', 'xmlhttprequest', 'other', 'object', 'sub_frame'],
  },
);

ext.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (details.tabId < 0) return;
    const headers = details.responseHeaders || [];
    const contentType = headerValue(headers, 'content-type');
    const contentRange = headerValue(headers, 'content-range');
    const size = parseInt(headerValue(headers, 'content-length'), 10) || 0;
    const purpose = headerValue(headers, 'sec-purpose') || headerValue(headers, 'purpose') || headerValue(headers, 'x-purpose');
    if (/prefetch/i.test(purpose)) return;
    const isManifestUrl = MANIFEST_EXT.test(details.url) || /\/m3u\//i.test(details.url);
    const isMediaUrl = MEDIA_EXT.test(details.url);
    const looksLikeVideoPath = /video|stream|play|master|playlist|media|cdn|m3u8|m3u|mpd/i.test(details.url);
    const ctLower = String(contentType || '').toLowerCase();
    const isVideoCt = ctLower.startsWith('video/') || ctLower.startsWith('audio/') ||
      ctLower.includes('mpegurl') || ctLower.includes('dash+xml') ||
      ctLower.includes('octet-stream') || ctLower.includes('binary');
    // HTML/JS/CSS/görsel yanıtlarını atla.
    if (ctLower.includes('text/html') || ctLower.includes('application/xhtml') ||
        ctLower.includes('javascript') || ctLower.includes('css') ||
        ctLower.includes('image/')) return;
    // Çok küçük ve video olmayan yanıtları atla.
    if (size > 0 && size < MIN_DIRECT_SIZE && !isVideoCt && !isManifestUrl && !contentRange) return;
    if (!isManifestUrl && !isMediaUrl && !isVideoCt && !looksLikeVideoPath && !/vidmixi\.com/i.test(details.url)) return;
    handleDetection(
      details.tabId,
      details.url,
      contentType,
      size,
      'headers',
      details.initiator || '',
      details.type,
      contentRange,
    ).catch(() => {});
  },
  {
    urls: ['<all_urls>'],
    types: ['media', 'xmlhttprequest', 'other', 'object', 'sub_frame'],
  },
  ['responseHeaders'],
);

// ------------------------------------------------------------------- tab events
ext.tabs.onRemoved.addListener((tabId) => {
  tabInfoCache.delete(tabId);
  call(ext.storage.local.remove.bind(ext.storage.local), tabKey(tabId)).catch(() => {});
});

ext.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url) {
    tabInfoCache.delete(tabId);
    withLock(`tab:${tabId}`, async () => {
      const record = await readTab(tabId);
      record.pageUrl = changeInfo.url;
      record.pageTitle = changeInfo.title || (tab && tab.title) || '';
      record.items = [];
      await writeTab(tabId, record);
      await setBadge(tabId, 0);
    }).then(() => {
      checkAndAddVideoPage(tabId, changeInfo.url, changeInfo.title || (tab && tab.title) || '').catch(() => {});
    }).catch(() => {});
  } else if (changeInfo.title) {
    tabInfoCache.delete(tabId);
    withLock(`tab:${tabId}`, async () => {
      const record = await readTab(tabId);
      record.pageTitle = changeInfo.title;
      await writeTab(tabId, record);
    }).then(() => {
      const url = (tab && tab.url) || '';
      if (url) checkAndAddVideoPage(tabId, url, changeInfo.title).catch(() => {});
    }).catch(() => {});
  }
});

// --------------------------------------------------------------------- messages
ext.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message !== 'object') return false;
  const tab = sender.tab;
  const tabId = tab && Number.isInteger(tab.id) ? tab.id : -1;

  if (message.type === 'dom-media' && tabId >= 0 && Array.isArray(message.urls)) {
    (async () => {
      for (const url of message.urls.slice(0, 50)) {
        await handleDetection(tabId, url, '', 0, 'dom', tab.url || sender.url || '', 'dom');
      }
      sendResponse({ ok: true });
    })().catch(() => sendResponse({ ok: false }));
    return true;
  }

  if (message.type === 'page-info' && tabId >= 0) {
    const topUrl = (tab && tab.url) || message.pageUrl || '';
    withLock(`tab:${tabId}`, async () => {
      const record = await readTab(tabId);
      if (record.pageUrl && topUrl && record.pageUrl !== topUrl) {
        record.items = [];
      }
      if (topUrl) record.pageUrl = topUrl;
      if (message.pageTitle || (tab && tab.title)) {
        record.pageTitle = message.pageTitle || tab.title || record.pageTitle;
      }
      await writeTab(tabId, record);
      await setBadge(tabId, record.items.length);
    })
      .then(() => {
        checkAndAddVideoPage(
          tabId,
          topUrl,
          message.pageTitle || (tab && tab.title) || '',
          !!message.hasVideo,
        ).catch(() => {});
        sendResponse({ ok: true });
      })
      .catch(() => sendResponse({ ok: false }));
    return true;
  }

  if (message.type === 'get-media' && tabId >= 0) {
    (async () => {
      const record = await readTab(tabId);
      let appLabels = {};
      try {
        const caps = await fetchJson(API_BASE + '/api/captures');
        for (const c of (caps.captures || [])) {
          if (c && c.url) appLabels[c.url] = c.media_label || c.kind_label || mediaLabel(c);
        }
      } catch {
        // Uygulama kapalıysa yerel etiket kullan.
      }
      const items = (record.items || []).map((item) => ({
        url: item.url,
        title: item.title || item.pageTitle || titleFromUrl(item.url),
        kind: item.kind || 'direct',
        contentType: item.contentType || '',
        size: Number(item.size) || 0,
        label: appLabels[item.url] || mediaLabel(item),
      }));
      sendResponse({ ok: true, items });
    })().catch(() => sendResponse({ ok: false, items: [] }));
    return true;
  }

  if (message.type === 'download-url' && tabId >= 0) {
    const url = String(message.url || '').trim();
    if (!url) {
      sendResponse({ ok: false, error: 'URL yok' });
      return false;
    }
    (async () => {
      const record = await readTab(tabId);
      const item = (record.items || []).find((entry) => entry.url === url) || {};
      const body = {
        url,
        kind: item.kind || 'direct',
        title: item.title || item.pageTitle || '',
        page_url: item.pageUrl || record.pageUrl || '',
        referer: item.referer || record.pageUrl || '',
        content_type: item.contentType || '',
        size: Number(item.size) || 0,
        quality: message.quality || 'best',
      };
      const result = await fetchJson(API_BASE + '/api/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      sendResponse({ ok: true, result });
    })().catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (message.type === 'retry-pending') {
    retryPending()
      .then(() => sendResponse({ ok: true }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }

  if (message.type === 'clear-tab' && tabId >= 0) {
    withLock(`tab:${tabId}`, async () => {
      const record = await readTab(tabId);
      record.items = [];
      await writeTab(tabId, record);
      await setBadge(tabId, 0);
    })
      .then(() => sendResponse({ ok: true }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }

  return false;
});

// ------------------------------------------------------------------------ alarm
function ensureAlarm() {
  try {
    const result = ext.alarms.create('va-retry', { periodInMinutes: 1 });
    if (result && typeof result.catch === 'function') result.catch(() => {});
  } catch {
    // Bazı tarayıcılarda alarms API'si farklı davranabilir.
  }
}

ext.runtime.onInstalled.addListener(() => {
  ensureAlarm();
  call(ext.storage.local.get.bind(ext.storage.local), 'settings')
    .then((data) => {
      if (!data || !data.settings) {
        return call(ext.storage.local.set.bind(ext.storage.local), { settings: { autoSend: true, quality: 'best' } });
      }
      return null;
    })
    .catch(() => {});
});

ext.runtime.onStartup.addListener(() => {
  ensureAlarm();
  retryPending().catch(() => {});
});

ext.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'va-retry') retryPending().catch(() => {});
});

ensureAlarm();
retryPending().catch(() => {});
