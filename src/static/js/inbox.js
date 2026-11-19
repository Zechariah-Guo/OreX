/**
 * Inbox page: list -> select mode -> full-screen detail.
 *
 * One flow at every width. The server renders the list once (#inbox-list, each
 * row a real link to /inbox?selected=<id>); this script adds:
 *   - opening a row into the full-screen detail (history entry, so the browser
 *     and Android Back buttons return to the list)
 *   - select mode: press-and-hold on touch, the hover row checkbox with a
 *     mouse, Space on a focused row with a keyboard
 *   - bulk Mark as read / Delete and the filter menu
 * Nothing here polls: notifications.js polls /inbox/poll for toasts and the
 * navbar dot, and never touches the list, so select mode and the detail view
 * are never refreshed underneath the user.
 */
(function () {
    'use strict';

    var root = document.getElementById('inbox');
    if (!root) {
        return;
    }

    // Press-and-hold: 500 ms matches the Android long-press feel, and 10 px of
    // finger drift is allowed before it counts as a scroll or swipe instead.
    var LONG_PRESS_MS = 500;
    var MOVE_TOLERANCE_PX = 10;
    var REMOVE_ANIM_MS = 300;

    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

    var mode = 'browse';          // 'browse' | 'select'
    var selectEntryPushed = false; // a history entry exists for select mode
    var listScrollY = 0;           // list scroll position while the detail is open
    var lastOpenedId = null;
    var lastTouchAt = 0;
    var suppressClickUntil = 0;
    var busy = false;
    var press = null;

    if ('scrollRestoration' in history) {
        history.scrollRestoration = 'manual';
    }

    function byId(id) {
        return document.getElementById(id);
    }

    function listEl() {
        return byId('inbox-list');
    }

    function rows() {
        return Array.prototype.slice.call(listEl().querySelectorAll('.inbox__list-item[data-id]'));
    }

    function rowInput(row) {
        return row.querySelector('.inbox__check-input');
    }

    function currentFilter() {
        return listEl().getAttribute('data-filter') || 'all';
    }

    function filterQuery() {
        var f = currentFilter();
        return f === 'all' ? '' : '?filter=' + encodeURIComponent(f);
    }

    function focusQuietly(el) {
        if (el && el.focus) {
            el.focus({ preventScroll: true });
        }
    }

    // ─── Network ────────────────────────────────────────────────────────────────

    function csrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : '';
    }

    function updateUnreadDot(hasUnread) {
        var icon = document.querySelector('.nav__dropdown-icon[title="Inbox"]');
        if (!icon) {
            return;
        }
        icon.classList.toggle('nav__dropdown-icon--unread', hasUnread);
        icon.setAttribute('aria-label', hasUnread ? 'Inbox - unread notifications' : 'Inbox');
    }

    function request(url, options) {
        options = options || {};
        options.credentials = 'same-origin';
        options.headers = Object.assign({
            'X-CSRFToken': csrfToken(),
            'X-Requested-With': 'XMLHttpRequest'
        }, options.headers || {});
        return fetch(url, options).then(function (response) {
            if (!response.ok) {
                throw new Error('HTTP ' + response.status);
            }
            var unread = response.headers.get('X-Inbox-Has-Unread');
            if (unread !== null) {
                updateUnreadDot(unread === '1');
            }
            return response.text();
        });
    }

    function parseHtml(html) {
        var tpl = document.createElement('template');
        tpl.innerHTML = html.trim();
        return tpl.content;
    }

    // ─── Filter menu ────────────────────────────────────────────────────────────

    var filterBtn = byId('inbox-filter-btn');
    var filterMenu = byId('inbox-filter-menu');
    var FILTER_LABELS = { all: 'All', unread: 'Unread', read: 'Read' };

    function menuItems() {
        return Array.prototype.slice.call(filterMenu.querySelectorAll('.inbox__filter-item'));
    }

    function openMenu(focusLast) {
        filterMenu.hidden = false;
        filterBtn.setAttribute('aria-expanded', 'true');
        var items = menuItems();
        var active = filterMenu.querySelector('.inbox__filter-item--active') || items[0];
        focusQuietly(focusLast ? items[items.length - 1] : active);
    }

    function closeMenu(returnFocus) {
        if (filterMenu.hidden) {
            return;
        }
        filterMenu.hidden = true;
        filterBtn.setAttribute('aria-expanded', 'false');
        if (returnFocus) {
            focusQuietly(filterBtn);
        }
    }

    function syncFilterUi(filter) {
        var label = FILTER_LABELS[filter] || 'All';
        byId('inbox-filter-label').textContent = label;
        filterBtn.setAttribute('aria-label', 'Filter notifications: ' + label);
        menuItems().forEach(function (item) {
            var on = item.getAttribute('data-filter') === filter;
            item.classList.toggle('inbox__filter-item--active', on);
            item.setAttribute('aria-checked', on ? 'true' : 'false');
        });
        byId('inbox-back').setAttribute('href', '/inbox' + (filter === 'all' ? '' : '?filter=' + filter));
    }

    function swapList(newList) {
        var current = listEl();
        current.replaceWith(newList);
        syncFilterUi(newList.getAttribute('data-filter') || 'all');
        updateSelectUi();
    }

    function applyFilter(filter) {
        closeMenu(true);
        if (filter === currentFilter()) {
            return;
        }
        var url = '/inbox' + (filter === 'all' ? '' : '?filter=' + filter);
        request(url, { method: 'GET' }).then(function (html) {
            var fresh = parseHtml(html).getElementById('inbox-list');
            if (!fresh) {
                throw new Error('no list');
            }
            swapList(fresh);
            // Same screen, different view of it: replace the entry rather than add one
            history.replaceState({ inboxView: 'list' }, '', url);
        }).catch(function () {
            window.location.href = url;
        });
    }

    filterBtn.addEventListener('click', function () {
        if (filterMenu.hidden) {
            openMenu(false);
        } else {
            closeMenu(true);
        }
    });

    filterBtn.addEventListener('keydown', function (event) {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            openMenu(event.key === 'ArrowUp');
        }
    });

    filterMenu.addEventListener('click', function (event) {
        var item = event.target.closest('.inbox__filter-item');
        if (item) {
            event.preventDefault();
            applyFilter(item.getAttribute('data-filter'));
        }
    });

    filterMenu.addEventListener('keydown', function (event) {
        var items = menuItems();
        var index = items.indexOf(document.activeElement);
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            focusQuietly(items[(index + 1) % items.length]);
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            focusQuietly(items[(index - 1 + items.length) % items.length]);
        } else if (event.key === 'Home') {
            event.preventDefault();
            focusQuietly(items[0]);
        } else if (event.key === 'End') {
            event.preventDefault();
            focusQuietly(items[items.length - 1]);
        } else if (event.key === 'Escape') {
            event.preventDefault();
            event.stopPropagation();
            closeMenu(true);
        } else if (event.key === 'Tab') {
            closeMenu(false);
        } else if (event.key === ' ') {
            event.preventDefault();
            if (document.activeElement && document.activeElement.click) {
                document.activeElement.click();
            }
        }
    });

    document.addEventListener('click', function (event) {
        if (!filterMenu.hidden && !event.target.closest('#inbox-filter')) {
            closeMenu(false);
        }
    });

    // ─── Detail screen ──────────────────────────────────────────────────────────

    var detailEl = byId('inbox-detail');
    var detailDeleteBtn = byId('inbox-detail-delete');

    function setView(view) {
        root.setAttribute('data-view', view);
    }

    function markRowRead(id) {
        var row = listEl().querySelector('.inbox__list-item[data-id="' + id + '"]');
        if (!row) {
            return;
        }
        row.classList.remove('inbox__list-item--unread');
        row.classList.add('inbox__list-item--read');
        var label = row.querySelector('.inbox__sr');
        if (label) {
            label.remove();
        }
    }

    function showList() {
        setView('list');
        window.scrollTo(0, listScrollY);
        var link = lastOpenedId && listEl().querySelector('.inbox__list-item[data-id="' + lastOpenedId + '"] .inbox__row-link');
        focusQuietly(link || byId('inbox-title'));
    }

    function openDetail(id, href, fromHistory) {
        if (root.getAttribute('data-view') === 'list') {
            listScrollY = window.scrollY;
        }
        lastOpenedId = id;
        // POST marks it read (as before) and returns the detail card
        return request('/inbox/' + encodeURIComponent(id) + '/read', { method: 'POST' }).then(function (html) {
            detailEl.innerHTML = html;
            detailDeleteBtn.setAttribute('data-id', id);
            markRowRead(id);
            setView('detail');
            window.scrollTo(0, 0);
            if (!fromHistory) {
                history.pushState({ inboxView: 'detail', id: id, pushed: true }, '', href);
            }
            focusQuietly(byId('inbox-back'));
        }).catch(function () {
            if (fromHistory) {
                showList();
            } else {
                window.location.href = href;
            }
        });
    }

    function backToList() {
        var state = history.state || {};
        if (state.inboxView === 'detail' && state.pushed) {
            history.back(); // popstate shows the list
            return;
        }
        // Arrived by deep link: there is no list entry behind us, so make one
        history.replaceState({ inboxView: 'list' }, '', '/inbox' + filterQuery());
        showList();
    }

    byId('inbox-back').addEventListener('click', function (event) {
        event.preventDefault();
        backToList();
    });

    // ─── Select mode ────────────────────────────────────────────────────────────

    var selectAllBtn = byId('inbox-select-all');
    var bulkReadBtn = byId('inbox-bulk-read');
    var bulkDeleteBtn = byId('inbox-bulk-delete');

    function selectedRows() {
        return rows().filter(function (row) {
            return rowInput(row).checked;
        });
    }

    function updateSelectUi() {
        var all = rows();
        var picked = selectedRows();
        var n = picked.length;
        all.forEach(function (row) {
            row.classList.toggle('inbox__list-item--selected', rowInput(row).checked);
        });
        byId('inbox-count-n').textContent = String(n);
        bulkReadBtn.disabled = n === 0;
        bulkDeleteBtn.disabled = n === 0;
        var everything = all.length > 0 && n === all.length;
        var text = everything ? selectAllBtn.getAttribute('data-label-none') : selectAllBtn.getAttribute('data-label-all');
        selectAllBtn.setAttribute('aria-label', text);
        selectAllBtn.querySelector('.inbox__action-label').textContent = text;
    }

    function setLinksFocusable(focusable) {
        rows().forEach(function (row) {
            var link = row.querySelector('.inbox__row-link');
            if (focusable) {
                link.removeAttribute('tabindex');
            } else {
                link.setAttribute('tabindex', '-1');
            }
        });
    }

    function enterSelect(row, focusTarget) {
        if (mode === 'select' || root.getAttribute('data-view') !== 'list' || rows().length === 0) {
            return;
        }
        closeMenu(false);
        mode = 'select';
        root.setAttribute('data-mode', 'select');
        // A history entry, so the Android / browser Back button leaves select mode
        history.pushState({ inboxView: 'select' }, '', location.href);
        selectEntryPushed = true;
        setLinksFocusable(false);
        if (row) {
            rowInput(row).checked = true;
        }
        updateSelectUi();
        focusQuietly(focusTarget || byId('inbox-select-exit'));
    }

    function leaveSelectUi() {
        if (mode !== 'select') {
            return;
        }
        mode = 'browse';
        root.setAttribute('data-mode', 'browse');
        selectEntryPushed = false;
        rows().forEach(function (row) {
            rowInput(row).checked = false;
        });
        setLinksFocusable(true);
        updateSelectUi();
        focusQuietly(byId('inbox-title'));
    }

    function exitSelect() {
        if (mode !== 'select') {
            return;
        }
        var state = history.state || {};
        if (selectEntryPushed && state.inboxView === 'select') {
            history.back(); // popstate runs leaveSelectUi
        } else {
            leaveSelectUi();
        }
    }

    byId('inbox-select-exit').addEventListener('click', exitSelect);

    selectAllBtn.addEventListener('click', function () {
        var all = rows();
        var everything = all.length > 0 && selectedRows().length === all.length;
        all.forEach(function (row) {
            rowInput(row).checked = !everything;
        });
        updateSelectUi();
    });

    // ─── Bulk actions ───────────────────────────────────────────────────────────

    function bulkBody(picked) {
        var params = new URLSearchParams();
        picked.forEach(function (row) {
            params.append('ids', row.getAttribute('data-id'));
        });
        params.append('filter', currentFilter());
        return params;
    }

    function runBulk(url, picked) {
        busy = true;
        return request(url, { method: 'POST', body: bulkBody(picked) }).then(function (html) {
            swapList(parseHtml(html).getElementById('inbox-list'));
            exitSelect();
        }).catch(function () {
            window.location.reload();
        }).then(function () {
            busy = false;
        });
    }

    bulkReadBtn.addEventListener('click', function () {
        var picked = selectedRows();
        if (busy || picked.length === 0) {
            return;
        }
        runBulk(root.getAttribute('data-bulk-read-url'), picked);
    });

    bulkDeleteBtn.addEventListener('click', function () {
        var picked = selectedRows();
        if (busy || picked.length === 0) {
            return;
        }
        // No confirm and no undo, same as deleting on desktop before. The rows slide out first.
        picked.forEach(function (row) {
            row.classList.add('inbox__list-item--removing');
        });
        var wait = reduceMotion.matches ? 0 : REMOVE_ANIM_MS;
        busy = true;
        window.setTimeout(function () {
            busy = false;
            runBulk(root.getAttribute('data-bulk-delete-url'), picked);
        }, wait);
    });

    detailDeleteBtn.addEventListener('click', function () {
        var id = detailDeleteBtn.getAttribute('data-id');
        if (busy || !id) {
            return;
        }
        busy = true;
        request('/inbox/' + encodeURIComponent(id) + filterQuery(), { method: 'DELETE' }).then(function (html) {
            swapList(parseHtml(html).getElementById('inbox-list'));
            lastOpenedId = null;
            backToList();
        }).catch(function () {
            window.location.reload();
        }).then(function () {
            busy = false;
        });
    });

    // ─── Clicks, keys and long-press ────────────────────────────────────────────

    root.addEventListener('click', function (event) {
        var row = event.target.closest('.inbox__list-item[data-id]');
        if (!row) {
            return;
        }
        if (Date.now() < suppressClickUntil) {
            // The click that follows a long press must not open or toggle the row
            event.preventDefault();
            event.stopPropagation();
            return;
        }
        var input = rowInput(row);
        if (mode === 'select') {
            if (event.target === input) {
                updateSelectUi();     // the checkbox already toggled itself
            } else {
                event.preventDefault();
                input.checked = !input.checked;
                updateSelectUi();
            }
            return;
        }
        // Browse mode. A mouse can tick the hover checkbox to start selecting.
        if (event.target === input || event.target.closest('.inbox__check')) {
            enterSelect(row, input);
            return;
        }
        var link = event.target.closest('.inbox__row-link');
        if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button) {
            return; // let the browser open it in a new tab
        }
        event.preventDefault();
        openDetail(row.getAttribute('data-id'), link.href, false);
    });

    root.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && mode === 'select') {
            event.preventDefault();
            exitSelect();
            return;
        }
        // Space on a focused row starts select mode (Enter still opens it)
        if (event.key === ' ' && mode === 'browse' && event.target.classList &&
            event.target.classList.contains('inbox__row-link')) {
            event.preventDefault();
            var row = event.target.closest('.inbox__list-item');
            enterSelect(row, rowInput(row));
        }
    });

    function cancelPress() {
        if (press) {
            window.clearTimeout(press.timer);
        }
        press = null;
    }

    function firePress() {
        if (!press) {
            return;
        }
        press.fired = true;
        enterSelect(press.row, null);
    }

    root.addEventListener('touchstart', function (event) {
        lastTouchAt = Date.now();
        cancelPress();
        if (mode !== 'browse' || root.getAttribute('data-view') !== 'list' || event.touches.length !== 1) {
            return;
        }
        var link = event.target.closest('.inbox__row-link');
        if (!link) {
            return;
        }
        var t = event.touches[0];
        press = {
            x: t.clientX,
            y: t.clientY,
            row: link.closest('.inbox__list-item'),
            fired: false,
            timer: window.setTimeout(firePress, LONG_PRESS_MS)
        };
    }, { passive: true });

    root.addEventListener('touchmove', function (event) {
        if (!press) {
            return;
        }
        if (press.fired) {
            // Held rows must not scroll the page under the finger
            if (event.cancelable) {
                event.preventDefault();
            }
            return;
        }
        var t = event.touches[0];
        if (Math.abs(t.clientX - press.x) > MOVE_TOLERANCE_PX || Math.abs(t.clientY - press.y) > MOVE_TOLERANCE_PX) {
            cancelPress();
        }
    }, { passive: false });

    function endPress(event) {
        if (press && press.fired) {
            suppressClickUntil = Date.now() + 350;
            if (event.cancelable) {
                event.preventDefault();
            }
        }
        cancelPress();
    }

    root.addEventListener('touchend', endPress, { passive: false });
    root.addEventListener('touchcancel', endPress, { passive: false });
    window.addEventListener('scroll', function () {
        if (press && !press.fired) {
            cancelPress();
        }
    }, { passive: true });

    // No browser context menu, link preview or drag on a held row
    root.addEventListener('contextmenu', function (event) {
        if (event.target.closest('.inbox__list-item') && (press || Date.now() - lastTouchAt < 1500)) {
            event.preventDefault();
        }
    });

    root.addEventListener('dragstart', function (event) {
        if (event.target.closest('.inbox__row-link')) {
            event.preventDefault();
        }
    });

    // ─── Back button ────────────────────────────────────────────────────────────

    window.addEventListener('popstate', function (event) {
        var state = event.state || {};
        if (state.inboxView === 'detail' && state.id) {
            if (mode === 'select') {
                leaveSelectUi();
            }
            openDetail(String(state.id), location.href, true);
            return;
        }
        if (mode === 'select') {
            leaveSelectUi();
        }
        if (root.getAttribute('data-view') === 'detail') {
            showList();
        }
    });

    // ─── Start-up ───────────────────────────────────────────────────────────────

    if (root.getAttribute('data-view') === 'detail') {
        // Deep link (toast, advancement): the server already rendered the detail
        var startId = detailDeleteBtn.getAttribute('data-id');
        lastOpenedId = startId;
        history.replaceState({ inboxView: 'detail', id: startId, pushed: false }, '');
        window.scrollTo(0, 0);
    } else {
        history.replaceState({ inboxView: 'list' }, '');
    }
    syncFilterUi(currentFilter());
    updateSelectUi();
})();
