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
var CACHE_VERSION = 'v7';
var CACHE_NAME = 'orex-offline-' + CACHE_VERSION;
var OFFLINE_URL = '/static/offline.html';
var PRECACHE_URLS = [
    OFFLINE_URL,
    '/static/images/logo.webp'
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

// ─── Web Push (opt-in) ───────────────────────────────────────────────────────
// The server decides whether a push is sent (only when the player is away), so
// every push that arrives here is shown: browsers require a visible
// notification for each push. Nothing in this section touches the fetch path.

self.addEventListener('push', function (event) {
    // Always show something: a missing or non-JSON payload still gets a notification
    var data = {};
    try {
        data = (event.data && event.data.json()) || {};
    } catch (e) {
        data = {};
    }
    if (typeof data !== 'object') { data = {}; }
    var title = data.title || 'OreX';
    var options = {
        body: data.body || '',
        icon: '/static/images/pwa/icon-192x192.png',
        data: { url: data.url || '/inbox' }
    };
    if (data.tag) {
        options.tag = data.tag;
        // Without renotify a repeat with the same tag replaces the old one silently
        options.renotify = true;
    }
    event.waitUntil(self.registration.showNotification(title, options));
});

// Only ever open or focus a page on this site, whatever the payload says.
function sameOriginUrl(url) {
    try {
        var target = new URL(url, self.location.origin);
        return target.origin === self.location.origin ? target.href : self.location.origin + '/inbox';
    } catch (e) {
        return self.location.origin + '/inbox';
    }
}

self.addEventListener('notificationclick', function (event) {
    event.notification.close();
    var target = sameOriginUrl(event.notification.data && event.notification.data.url);
    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (windows) {
            for (var i = 0; i < windows.length; i++) {
                var client = windows[i];
                if (new URL(client.url).origin === self.location.origin && 'focus' in client) {
                    return client.focus().then(function (focused) {
                        return 'navigate' in focused ? focused.navigate(target) : focused;
                    });
                }
            }
            return self.clients.openWindow(target);
        })
    );
});

// Best effort: if the browser rotates the subscription, subscribe again and tell
// the server. Needs the signed-in session cookie; silently gives up otherwise.
self.addEventListener('pushsubscriptionchange', function (event) {
    event.waitUntil(
        fetch('/push/config', { credentials: 'same-origin' }).then(function (resp) {
            return resp.json();
        }).then(function (config) {
            if (!config.configured || !config.csrf || !config.key) { return null; }
            var padding = '='.repeat((4 - config.key.length % 4) % 4);
            var raw = atob((config.key + padding).replace(/-/g, '+').replace(/_/g, '/'));
            var key = new Uint8Array(raw.length);
            for (var i = 0; i < raw.length; i++) { key[i] = raw.charCodeAt(i); }
            return self.registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: key
            }).then(function (sub) {
                return fetch('/push/subscribe', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': config.csrf },
                    body: JSON.stringify(sub.toJSON())
                });
            });
        }).catch(function () {})
    );
});
