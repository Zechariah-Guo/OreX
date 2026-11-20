/* OreX service worker (served from /sw.js so its scope is the whole site).
 *
 * Deliberately tiny. OreX is live, logged-in data, so NOTHING from the app is
 * cached: no pages, no htmx fragments, no API responses. The only cached files
 * are the offline fallback page and the one image it shows. The worker answers
 * page navigations only when the network request fails, and serves that one
 * image from the cache.
 *
 * Update strategy: the browser re-fetches /sw.js on every navigation (the
 * route sends no-cache). Any byte change installs the new worker, which takes
 * over straight away (skipWaiting + clients.claim) and deletes older caches.
 * Bump CACHE_VERSION whenever offline.html or its image changes.
 */
var CACHE_VERSION = 'v4';
var CACHE_NAME = 'orex-offline-' + CACHE_VERSION;
var OFFLINE_URL = '/static/offline.html';
var PRECACHE_URLS = [
    OFFLINE_URL,
    '/static/images/logo.png'
];

self.addEventListener('install', function (event) {
    event.waitUntil(
        caches.open(CACHE_NAME).then(function (cache) {
            // cache: 'reload' skips the HTTP cache so the fallback is never stale
            return cache.addAll(PRECACHE_URLS.map(function (url) {
                return new Request(url, { cache: 'reload' });
            }));
        }).then(function () {
            return self.skipWaiting();
        })
    );
});

self.addEventListener('activate', function (event) {
    event.waitUntil(
        caches.keys().then(function (names) {
            return Promise.all(names.filter(function (name) {
                return name.indexOf('orex-offline-') === 0 && name !== CACHE_NAME;
            }).map(function (name) {
                return caches.delete(name);
            }));
        }).then(function () {
            return self.clients.claim();
        })
    );
});

// Static images the offline page shows. These are answered from the cache
// (falling back to the network), otherwise the offline page's own <img>
// request would go to the network, fail, and show a broken image.
var CACHED_ASSET_PATHS = PRECACHE_URLS.filter(function (url) {
    return url !== OFFLINE_URL;
});

self.addEventListener('fetch', function (event) {
    var request = event.request;

    if (request.method === 'GET' && request.mode !== 'navigate') {
        var path = new URL(request.url).pathname;
        if (new URL(request.url).origin === self.location.origin &&
                CACHED_ASSET_PATHS.indexOf(path) !== -1) {
            event.respondWith(
                caches.match(path, { cacheName: CACHE_NAME }).then(function (hit) {
                    return hit || fetch(request);
                })
            );
        }
        // Everything else (htmx, JSON, other images, CSS, POSTs) is left alone:
        // no respondWith, so the browser goes straight to the network.
        return;
    }

    // Page navigations only from here.
    if (request.mode !== 'navigate') {
        return;
    }
    event.respondWith(
        fetch(event.request).catch(function () {
            return caches.match(OFFLINE_URL, { cacheName: CACHE_NAME });
        })
    );
});
