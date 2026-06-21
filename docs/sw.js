/* 情报 PWA Service Worker */
const CACHE = "intel-v2";
const SHELL = ["./", "index.html", "manifest.json", "icons/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  if (request.method !== "GET") return;
  const url = new URL(request.url);

  // 数据(.json)与页面(.html / 根):网络优先,回落缓存(离线也有上次内容)
  if (url.pathname.endsWith(".json") || url.pathname.endsWith(".html") || url.pathname.endsWith("/")) {
    e.respondWith(
      fetch(request).then((res) => {
        if (res.ok && url.origin === location.origin) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(request, copy));
        }
        return res;
      }).catch(() => caches.match(request))
    );
    return;
  }

  // 应用外壳:缓存优先,回落网络并写入缓存
  e.respondWith(
    caches.match(request).then((hit) =>
      hit || fetch(request).then((res) => {
        if (res.ok && url.origin === location.origin) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(request, copy));
        }
        return res;
      }).catch(() => hit)
    )
  );
});
