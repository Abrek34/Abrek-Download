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
  let timer = null;

  function send(message) {
    try {
      const result = ext.runtime.sendMessage(message);
      if (result && typeof result.catch === 'function') result.catch(() => {});
    } catch {
      // Eklenti bağlamı kapanmış olabilir.
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
    try {
      for (const entry of performance.getEntriesByType('resource')) {
        if (entry && entry.name && /^https?:/i.test(entry.name) && MEDIA.test(entry.name)) {
          urls.add(entry.name);
        }
      }
    } catch {
      // performance API kısıtlı olabilir.
    }

    const fresh = [...urls].filter((url) => !seen.has(url));
    for (const url of fresh) seen.add(url);
    if (fresh.length) send({ type: 'dom-media', urls: fresh });

    const pageKey = location.href + '\n' + document.title;
    if (pageKey !== lastPage) {
      lastPage = pageKey;
      send({ type: 'page-info', pageUrl: location.href, pageTitle: document.title });
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

  setInterval(collect, 10000);
})();
