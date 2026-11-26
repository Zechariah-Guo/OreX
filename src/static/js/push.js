/**
 * Web Push controls for the Settings "Notifications" card, plus the logout
 * clean-up. Nothing here asks for permission by itself: the permission prompt
 * and the push subscription happen only inside the device switch's change.
 */
(function () {
    'use strict';

    var supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

    function csrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function postJson(url, body, extra) {
        var options = {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
            body: JSON.stringify(body)
        };
        if (extra) {
            Object.keys(extra).forEach(function (k) { options[k] = extra[k]; });
        }
        return fetch(url, options);
    }

    function keyToBytes(base64Url) {
        var padding = '='.repeat((4 - base64Url.length % 4) % 4);
        var raw = atob((base64Url + padding).replace(/-/g, '+').replace(/_/g, '/'));
        var out = new Uint8Array(raw.length);
        for (var i = 0; i < raw.length; i++) { out[i] = raw.charCodeAt(i); }
        return out;
    }

    function currentSubscription() {
        return navigator.serviceWorker.getRegistration('/').then(function (reg) {
            return reg ? reg.pushManager.getSubscription() : null;
        });
    }

    function sameKey(sub, bytes) {
        var current = sub.options && sub.options.applicationServerKey;
        if (!current) { return true; }
        var a = new Uint8Array(current);
        if (a.length !== bytes.length) { return false; }
        for (var i = 0; i < a.length; i++) {
            if (a[i] !== bytes[i]) { return false; }
        }
        return true;
    }

    // The account that turned notifications on in this browser (its user id as a
    // string). A subscription can outlive its account's session (expired, signed
    // out from another device, deleted); the owner stops the self-heal from
    // handing it to whoever signs in next.
    var OWNER_KEY = 'orex-push-owner';
    function getOwner() {
        try { return localStorage.getItem(OWNER_KEY) || ''; } catch (e) { return ''; }
    }
    function setOwner(account) {
        try { if (account) { localStorage.setItem(OWNER_KEY, account); } } catch (e) {}
    }
    function clearOwner() {
        try { localStorage.removeItem(OWNER_KEY); } catch (e) {}
    }

    // Whether this browser's subscription belongs to the signed-in account. With
    // no owner recorded, the server decides: it is ours only if it has the row.
    function ownedBy(sub, account) {
        var owner = getOwner();
        if (owner) { return Promise.resolve(owner === account); }
        return fetch('/push/status?endpoint=' + encodeURIComponent(sub.endpoint), { credentials: 'same-origin' })
            .then(parse)
            .then(function (r) { return !!(r.ok && r.json && r.json.subscribed === true); });
    }

    // Self-heal: make sure the server has a row for this browser's existing
    // subscription (idempotent upsert). A subscription made with another VAPID
    // key is replaced first; no prompt, permission is already granted. A
    // subscription another account left behind is dropped instead.
    // Resolves to the fetch Response of /push/subscribe (or /push/status when dropped).
    function registerExisting(sub, publicKey, account) {
        return ownedBy(sub, account).then(function (mine) {
            if (!mine) {
                return sub.unsubscribe().catch(function () {}).then(function () {
                    clearOwner();
                    return fetch('/push/status', { credentials: 'same-origin' });
                });
            }
            setOwner(account);
            var bytes = keyToBytes(publicKey);
            var current = sameKey(sub, bytes) ? Promise.resolve(sub) :
                sub.unsubscribe().then(function () {
                    return navigator.serviceWorker.ready;
                }).then(function (reg) {
                    return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: bytes });
                });
            return current.then(function (active) {
                return postJson('/push/subscribe', active.toJSON());
            });
        });
    }

    // Response -> {status, ok, json}. json is null when the body is not JSON
    // (an expired session or CSRF failure answers with an HTML page).
    function parse(resp) {
        var type = resp.headers.get('content-type') || '';
        var body = type.indexOf('application/json') !== -1 ?
            resp.json().catch(function () { return null; }) : Promise.resolve(null);
        return body.then(function (json) { return { status: resp.status, ok: resp.ok, json: json }; });
    }

    // On any other page: once per browser session, re-register an existing subscription
    document.addEventListener('DOMContentLoaded', function () {
        if (!supported || document.getElementById('push-card')) { return; }
        if (Notification.permission !== 'granted') { return; }
        try { if (sessionStorage.getItem('orex-push-healed')) { return; } } catch (e) { return; }
        currentSubscription().then(function (sub) {
            if (!sub) { return null; }
            return fetch('/push/config', { credentials: 'same-origin' }).then(parse).then(function (r) {
                var config = r.json;
                // Signed out (no csrf) or not configured: try again on a later page
                if (!config || !config.configured || !config.csrf || !config.key || !config.account) { return null; }
                sessionStorage.setItem('orex-push-healed', '1');
                return registerExisting(sub, config.key, config.account);
            });
        }).catch(function () {});
    });

    // ─── Logout: drop this browser's subscription first (best effort) ────────
    // A subscription belongs to the account that created it, so signing out of
    // this browser stops pushes to it.
    if (supported) {
        document.addEventListener('click', function (event) {
            var link = event.target.closest ? event.target.closest('a[href$="/logout"]') : null;
            if (!link || event.defaultPrevented || event.button !== 0 ||
                    event.metaKey || event.ctrlKey || event.shiftKey) {
                return;
            }
            event.preventDefault();
            var go = function () { window.location.href = link.href; };
            var cleanup = currentSubscription().then(function (sub) {
                if (!sub) { return null; }
                // Both at once: a failed server call must not skip the local unsubscribe
                clearOwner();
                return Promise.all([
                    postJson('/push/unsubscribe', { endpoint: sub.endpoint }).catch(function () {}),
                    sub.unsubscribe().catch(function () {})
                ]);
            }).catch(function () {});
            var timeout = new Promise(function (resolve) { setTimeout(resolve, 1500); });
            Promise.race([cleanup, timeout]).then(go, go);
        });

        // Deleting the account: the server row goes with the account, but the
        // browser would keep its subscription and the self-heal would attach it to
        // the next account that signs in here. Drop it locally before submitting.
        // Only when the typed username matches, so a rejected attempt keeps it.
        document.addEventListener('submit', function (event) {
            var form = event.target;
            if (!form || !form.hasAttribute || !form.hasAttribute('data-push-drop-on-submit') ||
                    event.defaultPrevented || form.dataset.pushDropped) {
                return;
            }
            var input = form.querySelector('[name="confirmation"]');
            if (!input || input.value.trim() !== form.dataset.username) {
                return;
            }
            event.preventDefault();
            form.dataset.pushDropped = '1';
            var go = function () { form.submit(); };
            clearOwner();
            var cleanup = currentSubscription().then(function (sub) {
                return sub ? sub.unsubscribe() : null;
            }).catch(function () {});
            var timeout = new Promise(function (resolve) { setTimeout(resolve, 1500); });
            Promise.race([cleanup, timeout]).then(go, go);
        });
    }

    // ─── Settings card ──────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', function () {
        var card = document.getElementById('push-card');
        if (!card) { return; }

        var controls = document.getElementById('push-controls');
        var deviceSwitch = document.getElementById('push-device-switch');
        var prefsEl = document.getElementById('push-prefs');
        var noteEl = document.getElementById('push-note');
        var testBtn = document.getElementById('push-test-btn');
        var statusEl = document.getElementById('push-status');
        var testStatusEl = document.getElementById('push-test-status');
        var footerStateEl = document.getElementById('push-footer-state');
        var iosHint = document.getElementById('push-ios-hint');
        var deniedEl = document.getElementById('push-denied');
        var unconfiguredEl = document.getElementById('push-unconfigured');
        var switches = card.querySelectorAll('[data-push-group]');
        var publicKey = card.getAttribute('data-public-key') || '';
        var account = card.getAttribute('data-account') || '';
        var configured = card.getAttribute('data-configured') === 'true';
        var subscribed = false;   // true only when the server confirms this device
        var devices = null;       // devices with notifications on for the account (server count)
        var checkFailed = false;
        var busy = false;         // the device switch is working

        // say: feedback next to the category list; note: message under the device switch
        function say(text) { statusEl.textContent = text || ''; }
        function testSay(text) { testStatusEl.textContent = text || ''; }
        function note(text) { noteEl.textContent = text || ''; noteEl.hidden = !text; }

        var ua = navigator.userAgent;
        var isIos = /iPad|iPhone|iPod/.test(ua) ||
            (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
        var standalone = (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
            navigator.standalone === true;

        if (!configured) {
            controls.hidden = true;
            unconfiguredEl.hidden = false;
            return;
        }

        // The card is always shown. The switch starts disabled; without Web Push
        // it stays that way, with a short reason under it.
        if (!supported) {
            // iPhone and iPad Safari only get push inside the installed app
            if (isIos && !standalone) {
                iosHint.hidden = false;
            } else {
                document.getElementById('push-unsupported').hidden = false;
            }
            return;
        }

        deviceSwitch.disabled = false;
        deviceSwitch.parentNode.removeAttribute('data-unavailable');

        function render() {
            var denied = Notification.permission === 'denied';
            deniedEl.hidden = !denied || subscribed;
            if (!busy) { deviceSwitch.checked = subscribed; }
            deviceSwitch.disabled = busy || (denied && !subscribed);
            deviceSwitch.setAttribute('aria-busy', busy ? 'true' : 'false');
            prefsEl.hidden = !subscribed;
            // One line: "this device" when it is the only one (or the count is unknown),
            // otherwise the account's total
            footerStateEl.textContent = (devices !== null && devices > 1)
                ? 'Notifications are on for ' + devices + ' devices'
                : 'Notifications are on for this device';
            if (checkFailed) {
                note('Could not check notifications with the server. Reload the page to try again.');
            }
        }

        // Ask the server, not just the browser. A browser subscription is
        // re-registered first, so a missing server row is restored.
        function refresh() {
            checkFailed = false;
            return currentSubscription().then(function (sub) {
                var request = sub ? registerExisting(sub, publicKey, account) : fetch('/push/status', { credentials: 'same-origin' });
                return request.then(parse).then(function (r) {
                    if (!r.ok || !r.json) { throw new Error('status'); }
                    subscribed = !!sub && r.json.subscribed === true;
                    devices = typeof r.json.devices === 'number' ? r.json.devices : null;
                });
            }).catch(function () {
                subscribed = false;
                devices = null;
                checkFailed = true;
            }).then(render);
        }

        function subscribeDevice() {
            return navigator.serviceWorker.ready.then(function (reg) {
                var options = { userVisibleOnly: true, applicationServerKey: keyToBytes(publicKey) };
                return reg.pushManager.subscribe(options).catch(function (err) {
                    // A subscription made with another server key blocks a new one
                    if (err && err.name === 'InvalidStateError') {
                        return reg.pushManager.getSubscription().then(function (old) {
                            return old ? old.unsubscribe() : null;
                        }).then(function () { return reg.pushManager.subscribe(options); });
                    }
                    throw err;
                });
            }).then(function (sub) {
                return postJson('/push/subscribe', sub.toJSON()).then(function (resp) {
                    if (!resp.ok) {
                        return sub.unsubscribe().then(function () { throw new Error('save'); });
                    }
                    setOwner(account);
                });
            });
        }

        deviceSwitch.addEventListener('change', function () {
            var turnOn = deviceSwitch.checked;
            var work;
            note('');
            say('');
            if (turnOn) {
                // The one place permission is requested, called straight from the user's change
                var asked;
                try { asked = Promise.resolve(Notification.requestPermission()); } catch (e) { asked = Promise.reject(e); }
                work = asked.then(function (permission) {
                    if (permission !== 'granted') { throw new Error('permission'); }
                    return subscribeDevice();
                });
            } else {
                work = currentSubscription().then(function (sub) {
                    if (!sub) { return null; }
                    return postJson('/push/unsubscribe', { endpoint: sub.endpoint })
                        .catch(function () {})
                        .then(function () { return sub.unsubscribe(); })
                        .then(function (result) { clearOwner(); return result; });
                });
            }
            busy = true;
            render();
            work.catch(function () {
                // A denied permission shows its own help text from render()
                if (!turnOn) {
                    note('Could not turn off notifications. Try again.');
                } else if (Notification.permission !== 'denied') {
                    note('Could not turn on notifications. Try again.');
                }
            }).then(function () {
                busy = false;
                return refresh();
            });
        });

        Array.prototype.forEach.call(switches, function (input) {
            input.addEventListener('change', function () {
                var body = {};
                body[input.getAttribute('data-push-group')] = input.checked;
                postJson('/push/preferences', body).then(function (resp) {
                    if (!resp.ok) { throw new Error('save'); }
                    say('Saved');
                }).catch(function () {
                    input.checked = !input.checked;
                    say('Could not save. Please try again.');
                });
            });
        });

        // Sends to this device only. If the server does not know the device,
        // register it again once and retry.
        function sendTest(retried) {
            return currentSubscription().then(function (sub) {
                if (!sub) { return { status: 400, ok: false, json: { error: 'no_subscription' } }; }
                return postJson('/push/test', { endpoint: sub.endpoint }).then(parse);
            }).then(function (r) {
                if (!r.json) {
                    testSay('Your session has expired or the page is out of date. Reload the page and try again.');
                } else if (r.ok) {
                    testSay('Test notification sent to this device.');
                } else if (r.status === 503) {
                    testSay('Notifications are not configured on this server.');
                } else if (r.status === 429) {
                    testSay('Please wait a few seconds before sending another test.');
                } else if (r.status === 400 && r.json.error === 'no_subscription') {
                    if (retried) {
                        testSay('This device is not registered for notifications. Turn them off and on again.');
                        return refresh();
                    }
                    return refresh().then(function () {
                        if (subscribed) { return sendTest(true); }
                        testSay('This device is not registered for notifications. Turn them off and on again.');
                    });
                } else {
                    testSay('Could not send the test notification.');
                }
            });
        }

        testBtn.addEventListener('click', function () {
            testBtn.disabled = true;
            sendTest(false).catch(function () {
                testSay('Could not reach the server. Check your connection and try again.');
            }).then(function () {
                testBtn.disabled = false;
            });
        });

        refresh();
    });
})();
