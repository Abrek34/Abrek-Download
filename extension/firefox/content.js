'use strict';

/*
 * Sayfadaki <video>/<audio> etiketlerini ve performans kayıtlarını tarar.
 * Ağ isteklerini arka plan zaten izliyor; bu betik DOM'da kalan kaynakları yakalar.
 */

(() => {
  const isFirefox = typeof browser !== 'undefined' && !!browser.runtime;
  const ext = isFirefox ? browser : chrome;
  const MEDIA = /\.(mp4|webm|mkv|mov|m4v|m3u8|mpd|mp3|m4a|aac|ogg|opus)(?:$|[?#])/i;
  const seen = new Set();
  let lastPage = '';
  let lastHref = location.href;
  let pageInfoSent = false;
  let timer = null;
  const isInstagram = /(^|\\.)instagram\\.com$/i.test(location.hostname);

  function send(message) {
    try {
      const result = ext.runtime.sendMessage(message);
      if (result && typeof result.catch === 'function') result.catch(() => {});
    } catch {
      // Eklenti bağlamı kapanmış olabilir.
    }
  }

  function request(message) {
    // Firefox ve Chrome'da geri çağırma yerine Promise kullan. Firefox'ta
    // callback verilmezse Promise döner; callback'e bağlı kalmak menünün
    // "Yükleniyor…" durumunda kalmasına yol açıyordu.
    try {
      const result = ext.runtime.sendMessage(message);
      return result && typeof result.then === 'function'
        ? result
        : Promise.resolve(result);
    } catch (error) {
      return Promise.reject(error);
    }
  }

  function collect() {
    const urls = new Set();
    for (const element of document.querySelectorAll('video, audio, source')) {
      for (const value of [element.currentSrc, element.src, element.getAttribute('src')]) {
        if (!value || !/^https?:/i.test(value)) continue;
        if (MEDIA.test(value)) urls.add(value);
      }
    }
    // Instagram'da performance kayıtları onlarca varyant/prefetch medya URL'si
    // içerir ve "Yakalananlar" listesini doldurur. Burada yalnızca DOM'daki
    // <video> kaynaklarını kullanıyoruz; ağ istekleri arka plan tarafından
    // ayrıca filtrelenir.
    if (!isInstagram) {
      try {
        for (const entry of performance.getEntriesByType('resource')) {
          if (entry && entry.name && /^https?:/i.test(entry.name) && MEDIA.test(entry.name)) {
            urls.add(entry.name);
          }
        }
      } catch {
        // performance API kısıtlı olabilir.
      }
    }

    const fresh = [...urls].filter((url) => !seen.has(url));
    for (const url of fresh) seen.add(url);
    if (fresh.length) send({ type: 'dom-media', urls: fresh });

    const hasVideo = !!document.querySelector('video');
    const pageKey = location.href + '\n' + document.title;
    const pageChanged = pageKey !== lastPage;
    if (pageChanged) {
      lastPage = pageKey;
      pageInfoSent = false;
      send({
        type: 'page-info',
        pageUrl: location.href,
        pageTitle: document.title,
        hasVideo: hasVideo,
      });
    }
    if (hasVideo && !pageInfoSent) {
      pageInfoSent = true;
      send({
        type: 'page-info',
        pageUrl: location.href,
        pageTitle: document.title,
        hasVideo: true,
      });
    }
  }

  collect();

  const observer = new MutationObserver(() => {
    if (timer) return;
    timer = setTimeout(() => {
      timer = null;
      collect();
    }, 1500);
  });
  try {
    observer.observe(document.documentElement, { childList: true, subtree: true });
  } catch {
    // Belge henüz hazır değilse sessizce geç.
  }

  setInterval(() => {
    if (location.href !== lastHref) {
      seen.clear();
      pageInfoSent = false;
      lastPage = '';
      lastHref = location.href;
    }
    collect();
  }, 10000);

  // ------------------------------------------------------------------ video üstü indir düğmesi
  const MENU_ID = 'va-dl-menu';
  function ensureStyles() {
    if (document.getElementById('va-styles')) return;
    const style = document.createElement('style');
    style.id = 'va-styles';
    style.textContent = `
      .va-dl-btn { position:absolute; top:8px; right:8px; z-index:2147483647; background:rgba(0,0,0,.72); color:#fff; border:1px solid rgba(255,255,255,.15); border-radius:6px; padding:4px 8px; font-size:12px; cursor:pointer; opacity:0; transition:opacity .18s; }
      .va-dl-wrap { position:relative; display:inline-block; }
      .va-dl-wrap:hover .va-dl-btn, .va-dl-btn:hover { opacity:1; }
      .va-dl-menu { position:fixed; z-index:2147483647; background:#151a24; color:#edf1f8; border:1px solid #242c3b; border-radius:8px; padding:6px; min-width:220px; max-width:320px; box-shadow:0 6px 18px rgba(0,0,0,.45); font-family:sans-serif; font-size:12px; }
      .va-dl-menu button { display:block; width:100%; text-align:left; background:transparent; color:#edf1f8; border:none; padding:6px 8px; cursor:pointer; border-radius:4px; }
      .va-dl-menu button:hover { background:#1f2737; }
      .va-dl-menu .va-empty { padding:6px 8px; color:#77829a; }
    `;
    (document.head || document.documentElement).appendChild(style);
  }

  function removeMenu() {
    const m = document.getElementById(MENU_ID);
    if (m) m.remove();
  }

  function showMenu(anchor) {
    removeMenu();
    const menu = document.createElement('div');
    menu.className = 'va-dl-menu';
    menu.id = MENU_ID;
    const rect = anchor.getBoundingClientRect();
    menu.style.left = Math.max(8, rect.right - 228) + 'px';
    menu.style.top = (rect.bottom + 6) + 'px';

    const loading = document.createElement('div');
    loading.className = 'va-empty';
    loading.textContent = 'Yükleniyor…';
    menu.appendChild(loading);
    document.body.appendChild(menu);

    const render = (resp) => {
      menu.innerHTML = '';
      let items = (resp && Array.isArray(resp.items)) ? resp.items : [];
      // Medya bağlantılarını (HLS/direct) sayfa bağlantısının önüne koy.
      items.sort((a, b) => {
        const rank = (x) => (['direct', 'hls', 'dash'].includes(String(x.kind || '')) ? 0 : 1);
        return rank(a) - rank(b);
      });
      if (!items.length) {
        if (location.href.includes('youtube.com') || location.href.includes('youtu.be')) {
          const cleanTitle = document.title.replace(/\s*-\s*YouTube\s*$/i, '').trim();
          items = [{
            url: location.href,
            label: 'YOUTUBE',
            title: cleanTitle || 'YouTube Video',
          }];
        }
      }
      // Henüz yakalama yoksa video kaynaklarını yeniden topla ve tekrar dene.
      if (!items.length) {
        const srcs = [];
        const seenSrc = new Set();
        for (const element of document.querySelectorAll('video, audio, source')) {
          for (const value of [element.currentSrc, element.src, element.getAttribute('src')]) {
            if (value && /^https?:/i.test(value) && !seenSrc.has(value)) {
              seenSrc.add(value);
              srcs.push(value);
            }
          }
        }
        if (srcs.length) {
          const loading = document.createElement('div');
          loading.className = 'va-empty';
          loading.textContent = 'Yükleniyor…';
          menu.appendChild(loading);
          request({ type: 'dom-media', urls: srcs }).catch(() => {});
          request({ type: 'page-info', pageUrl: location.href, pageTitle: document.title, hasVideo: true }).catch(() => {});

          let retries = 0;
          const retry = () => {
            retries += 1;
            request({ type: 'get-media' }).then((resp) => {
              const items = (resp && Array.isArray(resp.items)) ? resp.items : [];
              if (items.length || retries >= 4) {
                render(resp);
              } else {
                setTimeout(retry, 1500);
              }
            }).catch(() => {
              if (retries >= 4) render(null);
              else setTimeout(retry, 1500);
            });
          };
          setTimeout(retry, 1500);
          return;
        }
      }
      if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'va-empty';
        empty.textContent = 'Yakalanan medya yok — videoyu oynatıp tekrar deneyin';
        menu.appendChild(empty);
        return;
      }
      for (const item of items) {
        const row = document.createElement('div');
        row.style.padding = '6px 4px';
        row.style.borderBottom = '1px solid #242c3b';

        const title = document.createElement('div');
        title.style.fontWeight = 'bold';
        title.style.marginBottom = '4px';
        title.style.fontSize = '11px';
        title.style.color = '#c7d2fe';
        title.textContent = (item.label || 'MEDYA') + ' · ' + (item.title || 'Video').slice(0, 40);
        row.appendChild(title);

        const actions = document.createElement('div');
        actions.style.display = 'flex';
        actions.style.gap = '4px';

        const qOptions = [
          { label: '⚡ En İyi', q: 'best' },
          { label: '720p', q: '720' },
          { label: '🎵 MP3', q: 'audio' },
          { label: '🔀 Ses+Görüntü', q: 'merge' }
        ];

        for (const opt of qOptions) {
          const btn = document.createElement('button');
          btn.textContent = opt.label;
          btn.style.flex = '1';
          btn.style.padding = '4px 6px';
          btn.style.textAlign = 'center';
          btn.style.fontSize = '10px';
          btn.style.background = '#20293a';
          btn.style.borderRadius = '4px';
          btn.addEventListener('click', () => {
            removeMenu();
            request({ type: 'download-url', url: item.url, quality: opt.q }).catch(() => {});
          });
          actions.appendChild(btn);
        }
        row.appendChild(actions);
        menu.appendChild(row);
      }
    };
    request({ type: 'get-media' }).then(render).catch(() => render(null));
  }

  function wrapVideo(video) {
    // Geçici eklenti yeniden yüklendiğinde DOM'daki eski işaretleyici kalabilir;
    // buton kayıpsa yeniden sar.
    if (video.dataset.vaWrapped === '1') {
      const parent = video.closest('#movie_player') || video.parentElement;
      if (parent && parent.querySelector('.va-dl-btn')) return;
    }
    video.dataset.vaWrapped = '1';
    let parent = video.closest('#movie_player') || video.parentElement;
    if (!parent) return;
    try {
      const pos = getComputedStyle(parent).position;
      if (pos === 'static') parent.style.position = 'relative';
    } catch {
      parent.style.position = 'relative';
    }

    const btn = document.createElement('button');
    btn.className = 'va-dl-btn';
    btn.textContent = '⬇';
    btn.title = 'Abrek Download ile indir';
    btn.style.zIndex = '2147483647';
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      showMenu(btn);
    });
    parent.appendChild(btn);

    const show = () => { btn.style.opacity = '1'; };
    const hide = () => { btn.style.opacity = '0'; };
    video.addEventListener('mouseenter', show);
    video.addEventListener('mouseleave', hide);
    parent.addEventListener('mouseenter', show);
    parent.addEventListener('mouseleave', hide);
    btn.addEventListener('mouseenter', show);
    btn.addEventListener('mouseleave', hide);
  }

  function scanVideos() {
    ensureStyles();
    for (const v of document.querySelectorAll('video')) wrapVideo(v);
  }

  scanVideos();
  const vObserver = new MutationObserver(() => scanVideos());
  try {
    vObserver.observe(document.documentElement, { childList: true, subtree: true });
  } catch {
    // sessizce geç
  }
  setInterval(scanVideos, 4000);

  // YouTube ve SPA sayfa geçişleri dinleyicisi
  window.addEventListener('yt-navigate-finish', () => {
    seen.clear();
    pageInfoSent = false;
    lastPage = '';
    setTimeout(() => {
      collect();
      scanVideos();
    }, 700);
  });
  window.addEventListener('popstate', () => {
    seen.clear();
    pageInfoSent = false;
    lastPage = '';
    setTimeout(() => {
      collect();
      scanVideos();
    }, 700);
  });

  document.addEventListener('click', (e) => {
    const m = document.getElementById(MENU_ID);
    if (m && (!e.target || !m.contains(e.target))) removeMenu();
  }, true);
})();
