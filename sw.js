/* Service worker : app disponible hors ligne */
const CACHE = 'prompteur-v4';
const ASSETS = ['./', './index.html', './manifest.json', './icon-180.png', './icon-192.png', './icon-512.png'];

/* GitHub Pages sert tout avec Cache-Control: max-age=600. Sans `cache:'reload'` /
   `'no-cache'`, le "reseau d'abord" ci-dessous tombait sur le cache HTTP du telephone
   et relancait la version d'il y a jusqu'a 10 min (constate le 2026-10-27 : Louis a
   rouvert l'app une minute apres une mise en ligne et a eu l'ancienne). */
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE)
    .then(c => c.addAll(ASSETS.map(u => new Request(u, {cache: 'reload'}))))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

/* index.html : reseau d'abord (pour recevoir les mises a jour), cache en secours.
   Le reste : cache d'abord. */
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;

  if (e.request.mode === 'navigate' || url.pathname.endsWith('index.html')) {
    e.respondWith(
      fetch(new Request(e.request, {cache: 'no-cache'}))   /* revalide aupres du serveur a chaque lancement */
        .then(r => { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); return r; })
        .catch(() => caches.match(e.request).then(r => r || caches.match('./index.html')))
    );
    return;
  }
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request).then(resp => {
      const copy = resp.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); return resp;
    }))
  );
});
