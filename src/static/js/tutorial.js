/**
 * OreX tutorial system: Alpine.js component + pure helper logic.
 *
 * Model (Option A): a guided slideshow laid over the real pages. While the
 * overlay is open it is modal — a click or tap ANYWHERE advances to the next
 * step (same as pressing Next), except on the card's own Back/Next/Skip
 * controls. The highlighted element is shown and explained but is NOT
 * interactive during the tour. Steps may live on different pages; pressing
 * Next navigates there as needed.
 *
 * LOAD ORDER: this file must load BEFORE the Alpine.js script (both deferred),
 * because it registers the component on `alpine:init`.
 *
 * The overlay root (partials/tutorial_overlay.html) provides:
 *   data-active-track   in-progress track id, or empty
 *   data-active-step    saved step index of that track
 *   data-auto-track     track to auto-start, or empty
 *   data-padding        TUTORIAL_HIGHLIGHT_PADDING
 *   data-transition-ms  TUTORIAL_TRANSITION_DURATION
 *   data-resume-ms      TUTORIAL_RESUME_TOAST_MS
 * The page must also provide <meta name="csrf-token"> for the POST requests.
 *
 * Resume: when a page loads with a tutorial paused (in_progress) and the player
 * did NOT arrive by pressing Next, a resume prompt is shown as a standard
 * .flash--toast (notifications.js gives it swipe + timer + styling). Tapping it
 * resumes at the saved step; letting it time out or swiping it away leaves the
 * tutorial paused, still replayable from the Help page.
 *
 * Steps may set "reveal": "menu" to force the avatar dropdown open (and keep it
 * open) while that step is shown — used for the nav-menu steps.
 */
(function (root) {
    'use strict';

    // ------------------------------------------------------------------
    // Pure logic (no DOM access; unit-testable under Node)
    // ------------------------------------------------------------------

    /** Strip query/hash and trailing slashes so routes compare reliably. */
    function normalizeRoute(route) {
        if (typeof route !== 'string') return '';
        var r = route.split('#')[0].split('?')[0];
        if (r.length > 1) r = r.replace(/\/+$/, '');
        return r || '/';
    }

    /** True when showing a step on targetRoute requires a page change. */
    function needsPageNavigation(currentRoute, targetRoute) {
        return normalizeRoute(currentRoute) !== normalizeRoute(targetRoute);
    }

    /** Button state for the step at `index` in a track of `length` steps. */
    function navState(index, length) {
        var isLast = index >= length - 1;
        return {
            backDisabled: index <= 0,
            isLast: isLast,
            forwardLabel: isLast ? 'Finish' : 'Next'
        };
    }

    function stepCounterText(index, length) {
        return 'Step ' + (index + 1) + ' of ' + length;
    }

    /** Highlight box = target rect grown by `padding` on every side. */
    function computeHighlight(rect, padding) {
        return {
            top: rect.top - padding,
            left: rect.left - padding,
            width: rect.width + 2 * padding,
            height: rect.height + 2 * padding
        };
    }

    function clamp(value, lo, hi) {
        return Math.min(Math.max(value, lo), hi);
    }

    /**
     * Place the step card next to the highlight box on the requested side,
     * flipping to the opposite side when it does not fit, and always keeping
     * the card inside the viewport (when the card fits at all).
     *
     * @param {string} position  'top'|'bottom'|'left'|'right'|'center'
     * @param {{top,left,width,height}} hl   highlight box (viewport coords)
     * @param {{width,height}} card          card size
     * @param {{width,height}} vp            viewport size
     * @returns {{top:number,left:number,side:string}}
     */
    function computeCardPosition(position, hl, card, vp, gap, margin) {
        gap = gap == null ? 16 : gap;
        margin = margin == null ? 12 : margin;

        var maxLeft = Math.max(0, vp.width - card.width);
        var maxTop = Math.max(0, vp.height - card.height);

        function clampAxis(value, max) {
            var lo = margin;
            var hi = max - margin;
            if (hi < lo) return max / 2;
            return clamp(value, lo, hi);
        }

        var fits = {
            top: hl.top - gap - card.height >= margin,
            bottom: hl.top + hl.height + gap + card.height <= vp.height - margin,
            left: hl.left - gap - card.width >= margin,
            right: hl.left + hl.width + gap + card.width <= vp.width - margin
        };
        var opposite = { top: 'bottom', bottom: 'top', left: 'right', right: 'left' };

        var side = position;
        if (opposite[side] && !fits[side] && fits[opposite[side]]) {
            side = opposite[side];
        }

        var centerX = hl.left + hl.width / 2 - card.width / 2;
        var centerY = hl.top + hl.height / 2 - card.height / 2;
        var top, left;
        switch (side) {
            case 'top':
                top = hl.top - gap - card.height; left = centerX; break;
            case 'bottom':
                top = hl.top + hl.height + gap; left = centerX; break;
            case 'left':
                left = hl.left - gap - card.width; top = centerY; break;
            case 'right':
                left = hl.left + hl.width + gap; top = centerY; break;
            default:
                side = 'center';
                top = (vp.height - card.height) / 2;
                left = (vp.width - card.width) / 2;
        }
        return { top: clampAxis(top, maxTop), left: clampAxis(left, maxLeft), side: side };
    }

    // ------------------------------------------------------------------
    // Phone layout (below 640px). The fixed top/bottom bars take screen
    // space, so the card is docked in one of two bands: just below the top
    // bar (plus the open avatar menu), or just above the bottom bar. The
    // target is scrolled into the part of the screen the card leaves free.
    // ------------------------------------------------------------------

    var PHONE_GAP = 12;

    /**
     * Decide how far to scroll the page (delta, +ve = scroll down) so the
     * target box `rect` (viewport coords, already padded) sits in the free area
     * left by the bars and the card, and which band the card should take.
     *
     * @param {{top,bottom,height}} rect
     * @param {{vh,topInset,bottomInset,cardHeight,pref,fixedTarget}} o
     *        pref: 'top' = card above the target, anything else = card below it
     * @returns {{delta:number, zone:'top'|'bottom'}}
     */
    function planPhoneLayout(rect, o) {
        var gap = PHONE_GAP;
        var safeTop = o.topInset + gap;
        var safeBottom = o.vh - o.bottomInset - gap;
        var order = o.pref === 'top' ? ['top', 'bottom'] : ['bottom', 'top'];
        function freeArea(zone) {
            return zone === 'bottom'
                ? [safeTop, safeBottom - o.cardHeight - gap]
                : [safeTop + o.cardHeight + gap, safeBottom];
        }
        var i, a, b, area;
        if (o.fixedTarget) {
            // Part of a bar: never scrolled, just pick the band it does not cover
            return { delta: 0, zone: pickPhoneZone(rect, o, order) };
        }
        for (i = 0; i < order.length; i++) {           // already well placed?
            area = freeArea(order[i]); a = area[0]; b = area[1];
            if (rect.top >= a && rect.bottom <= b) return { delta: 0, zone: order[i] };
        }
        for (i = 0; i < order.length; i++) {           // fits after a minimal scroll
            area = freeArea(order[i]); a = area[0]; b = area[1];
            if (rect.height <= b - a) {
                return { delta: rect.top < a ? rect.top - a : rect.bottom - b, zone: order[i] };
            }
        }
        // Taller than the free area: show its start and let the card overlap its end
        return { delta: rect.top - safeTop, zone: 'bottom' };
    }

    function phoneCardTop(zone, card, vp, topInset, bottomInset) {
        var gap = PHONE_GAP;
        if (zone === 'center') {
            return topInset + (vp.height - topInset - bottomInset - card.height) / 2;
        }
        if (zone === 'top') return topInset + gap;
        return vp.height - bottomInset - gap - card.height;
    }

    function pickPhoneZone(hl, o, order) {
        var card = { height: o.cardHeight };
        var vp = { height: o.vh };
        var best = order[0], bestOverlap = Infinity;
        for (var i = 0; i < order.length; i++) {
            var top = phoneCardTop(order[i], card, vp, o.topInset, o.bottomInset);
            var hlTop = hl.top, hlBottom = hl.top + (hl.height != null ? hl.height : hl.bottom - hl.top);
            var overlap = Math.max(0, Math.min(top + card.height, hlBottom) - Math.max(top, hlTop));
            if (overlap < bestOverlap) { best = order[i]; bestOverlap = overlap; }
        }
        return best;
    }

    /**
     * Phone card placement: horizontally centred, vertically in the band that
     * overlaps the highlight least (the requested side first).
     * @returns {{top:number,left:number,side:string}}
     */
    function computePhoneCardPosition(position, hl, card, vp, topInset, bottomInset, centered) {
        var left = Math.max(0, (vp.width - card.width) / 2);
        if (centered) {
            return { top: phoneCardTop('center', card, vp, topInset, bottomInset), left: left, side: 'center' };
        }
        var order = position === 'top' ? ['top', 'bottom'] : ['bottom', 'top'];
        var zone = pickPhoneZone(hl, {
            cardHeight: card.height, vh: vp.height, topInset: topInset, bottomInset: bottomInset
        }, order);
        var top = phoneCardTop(zone, card, vp, topInset, bottomInset);
        return { top: Math.max(top, topInset + PHONE_GAP), left: left, side: zone };
    }

    var Logic = {
        planPhoneLayout: planPhoneLayout,
        computePhoneCardPosition: computePhoneCardPosition,
        normalizeRoute: normalizeRoute,
        needsPageNavigation: needsPageNavigation,
        navState: navState,
        stepCounterText: stepCounterText,
        computeHighlight: computeHighlight,
        computeCardPosition: computeCardPosition
    };
    root.OreXTutorialLogic = Logic;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = Logic;
    }

    // Everything below needs a browser
    if (typeof document === 'undefined') return;

    // ------------------------------------------------------------------
    // Browser helpers
    // ------------------------------------------------------------------

    var NAV_KEY = 'orex-tutorial-nav';              // marks a Next-driven page change
    var RESUME_DISMISSED_KEY = 'orex-tutorial-resume-dismissed';
    var NAV_FLAG_MAX_AGE_MS = 60000;
    var SELECTOR_WAIT_MS = 1500;
    var SETTLE_DEBOUNCE_MS = 100;
    var FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), ' +
        'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    function storageGet(key) {
        try { return root.sessionStorage.getItem(key); } catch (e) { return null; }
    }
    function storageSet(key, value) {
        try { root.sessionStorage.setItem(key, value); } catch (e) { /* ignore */ }
    }
    function storageRemove(key) {
        try { root.sessionStorage.removeItem(key); } catch (e) { /* ignore */ }
    }

    function numberOr(value, fallback) {
        var n = parseFloat(value);
        return isNaN(n) ? fallback : n;
    }

    function csrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    /** First element matching selector that is actually rendered, or null. */
    function queryVisible(selector) {
        // A list of selectors spotlights the box around all of them (every one
        // must be rendered). Used for phone menu rows whose wrapper has no box.
        if (Array.isArray(selector)) {
            var els = [];
            for (var i = 0; i < selector.length; i++) {
                var found = queryVisible(selector[i]);
                if (!found) return null;
                els.push(found);
            }
            return els.length === 1 ? els[0] : unionTarget(els);
        }
        var el;
        try { el = document.querySelector(selector); } catch (e) { return null; }
        if (!el || el.getClientRects().length === 0) return null;
        return el;
    }

    /** Element-like wrapper whose rect is the union of several elements. */
    function unionTarget(els) {
        return {
            getClientRects: function () { return els[0].getClientRects(); },
            closest: function (sel) { return els[0].closest(sel); },
            scrollIntoView: function (opts) { els[0].scrollIntoView(opts); },
            getBoundingClientRect: function () {
                var top = Infinity, left = Infinity, right = -Infinity, bottom = -Infinity;
                els.forEach(function (e) {
                    var r = e.getBoundingClientRect();
                    top = Math.min(top, r.top); left = Math.min(left, r.left);
                    right = Math.max(right, r.right); bottom = Math.max(bottom, r.bottom);
                });
                return { top: top, left: left, right: right, bottom: bottom,
                         width: right - left, height: bottom - top };
            }
        };
    }

    /** Same breakpoint as the phone navbar (global.css, nav.js). */
    function isPhone() {
        return !!(root.matchMedia && root.matchMedia('(max-width: 640px)').matches);
    }

    /** A step with its phone overrides applied when on a phone (data stays desktop-first). */
    function effectiveStep(step) {
        if (!step || !step.phone || !isPhone()) return step || null;
        return Object.assign({}, step, step.phone);
    }

    /** Heights taken by the fixed bars (and the open avatar menu) on a phone. */
    function phoneInsets() {
        var top = 0, bottom = 0;
        if (document.querySelector('.main-nav--auth')) {
            top = parseFloat(getComputedStyle(document.body).getPropertyValue('--nav-top-h')) || 0;
            var bar = document.querySelector('.main-nav--auth .nav__links');
            if (bar) bottom = Math.max(0, root.innerHeight - bar.getBoundingClientRect().top);
            var menu = document.getElementById('nav-dropdown');
            if (menu && menu.classList.contains('nav__dropdown--open')) {
                top = Math.max(top, menu.getBoundingClientRect().bottom);
            }
        }
        return { top: top, bottom: bottom };
    }

    /** True when the target is part of the fixed phone navbar (never scrolled or clipped). */
    function isNavTarget(el) {
        return !!(el && el.closest && el.closest('.main-nav--auth'));
    }

    function sleep(ms) {
        return new Promise(function (resolve) { setTimeout(resolve, ms); });
    }

    function nextFrame() {
        return new Promise(function (resolve) { root.requestAnimationFrame(function () { resolve(); }); });
    }

    function prefersReducedMotion() {
        return !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);
    }

    // --- avatar dropdown (shared with nav.js) ---
    function setMenuOpen(open) {
        var dropdown = document.getElementById('nav-dropdown');
        var button = document.getElementById('nav-avatar-btn');
        if (!dropdown) return;
        dropdown.classList.toggle('nav__dropdown--open', open);
        if (button) button.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    // ------------------------------------------------------------------
    // Alpine component
    // ------------------------------------------------------------------

    function tutorialComponent() {
        return {
            // --- reactive state ---
            active: false,
            trackId: null,
            trackName: '',
            steps: [],
            currentIndex: 0,
            showOverlay: false,
            showCard: false,
            showConfirmSkip: false,
            busy: false,
            tracking: false,        // true while scrolling (disables the highlight transition)

            highlightTop: 0,
            highlightLeft: 0,
            highlightWidth: 0,
            highlightHeight: 0,
            highlightVisible: false,
            padding: 8,
            transitionMs: 400,
            resumeMs: 10000,

            cardTop: 0,
            cardLeft: 0,
            cardSide: 'center',

            vw: 0,
            vh: 0,

            // --- internals ---
            _stepToken: 0,
            _settleTimer: null,
            _scrollTimer: null,
            _revealTimer: null,
            _rafPending: false,
            _prevFocus: null,
            _demoShortOpened: false,   // demo short opened once this tour run
            _positioning: false,       // easing the spotlight after a programmatic scroll
            _positioningTimer: null,

            // --- derived values for the template ---
            get currentStep() {
                return effectiveStep(this.steps[this.currentIndex]);
            },
            get stepCounter() {
                return stepCounterText(this.currentIndex, this.steps.length);
            },
            get backDisabled() {
                return navState(this.currentIndex, this.steps.length).backDisabled;
            },
            get forwardLabel() {
                return navState(this.currentIndex, this.steps.length).forwardLabel;
            },
            get isLast() {
                return navState(this.currentIndex, this.steps.length).isLast;
            },
            get highlightStyle() {
                return {
                    transform: 'translate(' + this.highlightLeft + 'px, ' + this.highlightTop + 'px)',
                    width: this.highlightWidth + 'px',
                    height: this.highlightHeight + 'px',
                    opacity: (this.highlightVisible && !this.hideHighlight) ? 1 : 0
                };
            },
            /** True when the current step spotlights a target (vs. a plain dimmed screen). */
            get hideHighlight() {
                return !!(this.currentStep && this.currentStep.highlight === 'none');
            },

            /**
             * Four dim panels (top/left/right/bottom of the highlight box) that
             * together leave a transparent, undimmed hole over the target. When
             * the step has no highlight, the panels collapse so the whole screen
             * is dimmed. The whole screen still catches clicks (see the template).
             */
            get panelStyles() {
                var t = this.highlightTop, l = this.highlightLeft;
                var w = this.highlightWidth, h = this.highlightHeight;
                var vw = this.vw, vh = this.vh;
                // No spotlight: collapse the hole to a zero-size point at the screen
                // centre. The four panels still tile the whole screen (so it reads as
                // fully dimmed), and because the hole is centred rather than at a
                // corner, transitioning to/from a real spotlight animates the hole
                // opening or closing smoothly instead of sweeping panels across
                // each other.
                if (this.hideHighlight) {
                    t = vh / 2; l = vw / 2; w = 0; h = 0;
                }
                return {
                    top: { top: '0px', left: '0px', width: vw + 'px', height: Math.max(t, 0) + 'px' },
                    bottom: { top: (t + h) + 'px', left: '0px', width: vw + 'px', height: Math.max(vh - t - h, 0) + 'px' },
                    left: { top: t + 'px', left: '0px', width: Math.max(l, 0) + 'px', height: h + 'px' },
                    right: { top: t + 'px', left: (l + w) + 'px', width: Math.max(vw - l - w, 0) + 'px', height: h + 'px' }
                };
            },
            get cardStyle() {
                return { top: this.cardTop + 'px', left: this.cardLeft + 'px' };
            },

            // --- lifecycle ---
            init() {
                var ds = this.$el.dataset;
                this.padding = numberOr(ds.padding, 8);
                this.transitionMs = numberOr(ds.transitionMs, 400);
                this.resumeMs = numberOr(ds.resumeMs, 10000);
                this.updateViewport();
                this.bindGlobalListeners();

                var activeTrack = ds.activeTrack || '';
                var activeStep = parseInt(ds.activeStep, 10);
                var autoTrack = ds.autoTrack || '';

                if (activeTrack) {
                    this.handleInProgress(activeTrack, isNaN(activeStep) ? 0 : activeStep);
                } else if (autoTrack) {
                    this.autoStart(autoTrack);
                }
            },

            bindGlobalListeners() {
                var self = this;
                document.addEventListener('keydown', function (e) { self.onKeydown(e); }, true);
                root.addEventListener('resize', function () { self.onViewportChange(); });
                root.addEventListener('scroll', function () { self.onScroll(); }, { passive: true });
                document.addEventListener('htmx:afterSettle', function () { self.onHtmxSettle(); });
                // Leaving the page (close tab, navigate away, URL bar) while the
                // Advanced tour's demo short is open must clear it — the tour is no
                // longer on screen. A tour-driven page hop sets the nav flag, so we
                // skip the clear in that case (the next page re-opens it). pagehide
                // fires on normal tab close (X / Ctrl+W / Alt+F4) and navigation;
                // sendBeacon survives the unload. A hard process crash is the only
                // gap, caught by the server backstop on the next render.
                root.addEventListener('pagehide', function () { self.clearDemoShortOnExit(); });
            },

            /** Best-effort demo-short clear when leaving the page outside a tour hop. */
            clearDemoShortOnExit() {
                if (this.trackId !== 'advanced' || !this._demoShortOpened) return;
                if (storageGet(NAV_KEY)) return;   // tour's own page hop: the next page re-opens it
                try {
                    var body = new Blob([JSON.stringify({})], { type: 'application/json' });
                    if (root.navigator && typeof root.navigator.sendBeacon === 'function') {
                        root.navigator.sendBeacon('/tutorial/advanced/demo-clear', body);
                    }
                } catch (e) { /* unload: nothing more we can do */ }
            },

            /** Page loaded with a tutorial already in progress. */
            async handleInProgress(trackId, stepIndex) {
                var flag = this.consumeNavFlag();
                this.trackId = trackId;
                this.currentIndex = stepIndex;

                if (flag && flag.track_id === trackId && flag.step_index === stepIndex) {
                    // Arrived via a Next-driven navigation: carry straight on. The
                    // fresh-open path zooms the spotlight onto the target.
                    await this.resumeAt(trackId, stepIndex, false);
                    return;
                }
                // Offer the resume prompt once per browsing session. Once the player
                // has dismissed it (swiped, or let it time out) or seen it, we stop
                // re-offering on every page load / reload / navigation.
                if (storageGet(RESUME_DISMISSED_KEY) === trackId) return;
                this.offerResume();
            },

            /** A track should auto-start (first login / first advanced activation). */
            async autoStart(trackId) {
                var track = await this.fetchTrack(trackId);
                if (!track || !track.steps.length) return;
                // Only start once the first step's target exists here; otherwise do
                // nothing (no record created), so it can trigger again later.
                if (!queryVisible(track.steps[0].selector)) return;
                var res = await this.post('/tutorial/start', { track_id: trackId });
                if (!res.ok) return;
                this.loadTrack(track);
                await this.goTo(0, 1, { skipPersist: true, ignoreRoute: true });
            },

            // --- server communication ---
            async fetchTrack(trackId) {
                try {
                    var resp = await fetch('/tutorial/track/' + encodeURIComponent(trackId), {
                        credentials: 'same-origin',
                        headers: { 'Accept': 'application/json' }
                    });
                    if (!resp.ok) return null;
                    var data = await resp.json();
                    return data && Array.isArray(data.steps) ? data : null;
                } catch (e) {
                    console.warn('[tutorial] could not load track', trackId, e);
                    return null;
                }
            },

            /** POST JSON; ok is true only for a 2xx response whose body says ok:true. */
            async post(url, body) {
                try {
                    var resp = await fetch(url, {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: {
                            'Content-Type': 'application/json',
                            'Accept': 'application/json',
                            'X-CSRFToken': csrfToken()
                        },
                        body: JSON.stringify(body)
                    });
                    var data = null;
                    try { data = await resp.json(); } catch (e) { /* non-JSON (e.g. a login redirect) */ }
                    return { ok: resp.ok && !!data && data.ok === true, status: resp.status, data: data };
                } catch (e) {
                    console.warn('[tutorial] request failed', url, e);
                    return { ok: false, status: 0, data: null };
                }
            },

            loadTrack(track) {
                this.trackId = track.id;
                this.trackName = track.name || '';
                this.steps = track.steps;
                this.active = true;
            },

            async persistStep(index) {
                var res = await this.post('/tutorial/advance', { track_id: this.trackId, step_index: index });
                return res.ok;
            },

            // --- navigation ---

            /** A tap/click on the backdrop (anywhere but the card controls) advances. */
            advanceFromBackdrop() {
                this.next();
            },

            async next() {
                if (this.busy || !this.showOverlay) return;
                this.busy = true;
                try {
                    if (this.isLast) await this.finish();
                    else await this.goTo(this.currentIndex + 1, 1);
                } finally {
                    this.busy = false;
                }
            },

            async back() {
                if (this.busy || this.backDisabled || !this.showOverlay) return;
                this.busy = true;
                try {
                    await this.goTo(this.currentIndex - 1, -1);
                } finally {
                    this.busy = false;
                }
            },

            /**
             * Move to a step: persist progress, then either navigate to the
             * step's page or show it here. `direction` is the way to keep
             * skipping when a step's target element is missing.
             */
            async goTo(index, direction, opts) {
                opts = opts || {};
                if (index < 0) return this.goTo(0, 1, opts);
                if (index >= this.steps.length) return this.finish();
                if (!opts.skipPersist && !(await this.persistStep(index))) {
                    return; // server rejected or unreachable: stay put
                }
                var step = this.steps[index];
                // Run any server-side side effect this step needs (e.g. open the
                // demo short) BEFORE navigating, so the page it lands on already
                // reflects the new state. Failure is non-fatal: the tour goes on
                // and simply describes the feature instead of showing live data.
                await this.runStepAction(step);
                if (!opts.ignoreRoute && needsPageNavigation(root.location.pathname, step.route)) {
                    this.navigateTo(step.route, index);
                    return;
                }
                await this.showStep(index, direction);
            },

            navigateTo(route, index) {
                storageSet(NAV_KEY, JSON.stringify({
                    track_id: this.trackId, step_index: index, ts: Date.now()
                }));
                root.location.assign(route);
            },

            consumeNavFlag() {
                var raw = storageGet(NAV_KEY);
                if (!raw) return null;
                storageRemove(NAV_KEY);
                try {
                    var flag = JSON.parse(raw);
                    if (!flag || typeof flag.ts !== 'number' || Date.now() - flag.ts > NAV_FLAG_MAX_AGE_MS) {
                        return null;
                    }
                    return flag;
                } catch (e) {
                    return null;
                }
            },

            // --- showing a step ---
            async showStep(index, direction) {
                var token = ++this._stepToken;
                var step = effectiveStep(this.steps[index]);

                this.applyReveal(step);
                var el = await this.waitForElement(step.selector, SELECTOR_WAIT_MS);
                if (token !== this._stepToken) return; // superseded

                if (!el) {
                    console.warn('[tutorial] target not found, skipping step', this.trackId, index, step.selector);
                    return this.goTo(index + direction, direction);
                }

                this.currentIndex = index;
                this.showConfirmSkip = false;

                if (!this.showOverlay) {
                    this._prevFocus = document.activeElement;
                    this.updateViewport();
                    this.setHighlight({ top: 0, left: 0, width: this.vw, height: this.vh });
                    this.highlightVisible = true;
                    this.showOverlay = true;
                    // nav.js keeps the phone bars visible while a tutorial runs
                    document.documentElement.classList.add('tutorial-active');
                    // ...and bring back bars that were auto-hidden before it opened
                    document.documentElement.classList.remove('nav-hidden');
                    await nextFrame();
                    await nextFrame();
                    if (token !== this._stepToken) return;
                }

                // A no-highlight step spotlights nothing, so there is nothing to
                // scroll to; scrolling #main-content (the whole page) just jolts it.
                if (step.highlight !== 'none') {
                    this._positioning = true;
                    // Phone: let the card text update first so scrolling can
                    // leave room for the card's real height
                    if (isPhone()) await this.$nextTick();

                    // A SAME-PAGE step whose target must be SCROLLED into view is the
                    // only case that breaks: easing from the previous element's box to
                    // a target brought in by scrolling reconciles the old position AND
                    // the scroll in viewport space, giving the "move halfway, pause,
                    // then finish + reshape" artifact. For exactly that case, mimic a
                    // fresh page: snap the box to full screen (no transition, via
                    // tracking) before scrolling, then ease full-screen -> target — a
                    // scroll-independent anchor, like the first step on a page.
                    //
                    // Same-page steps that DON'T scroll (target already in view) keep
                    // the nicer ease straight from the previous element. Fresh opens
                    // already start full screen. Beginner is unaffected.
                    if (this.showOverlay && this.needsScroll(el)) {
                        this.tracking = true;   // .tutorial-no-transition: snap, don't ease
                        this.setHighlight({ top: 0, left: 0, width: this.vw, height: this.vh });
                        await nextFrame();
                        if (token !== this._stepToken) { this._positioning = false; return; }
                    }

                    // Suppress scroll-driven repositioning during our programmatic
                    // scroll: the box stays put while the page scrolls, then eases to
                    // the target afterwards (rather than creeping to it 1:1 with no
                    // animation left).
                    this.tracking = false;
                    clearTimeout(this._scrollTimer);
                    await this.scrollToTarget(el);
                    if (token !== this._stepToken) { this._positioning = false; return; }
                    // Make sure tracking didn't get left on, then paint one frame of
                    // the pre-move box with transitions enabled before the ease.
                    this.tracking = false;
                    clearTimeout(this._scrollTimer);
                    await nextFrame();
                    if (token !== this._stepToken) { this._positioning = false; return; }
                }

                // Wait until the target's rect is stable across frames before
                // positioning. On pages whose content is still laying out (a tab
                // just revealed; the finances/dashboard "live" partials filling in
                // their shorts table and cash-flow sections under {% if has_shorts %};
                // the chart sizing), an early read gives a transient position. The
                // spotlight would ease to that stale spot, then the content settles
                // and shifts the target, producing a two-stage "halfway then finish"
                // move. Waiting for a stable rect makes the ease land in one motion.
                // Resolves immediately (next frame) when already stable, so it is
                // free for steps that don't need it.
                if (step.highlight !== 'none') {
                    await this.waitForStableRect(step.selector);
                    if (token !== this._stepToken) { this._positioning = false; return; }
                }

                // Place the spotlight on the target. The single CSS transition eases
                // the box from wherever it currently is (full screen on a fresh page
                // -> a zoom-in; the previous target on a same-page step -> a slide).
                // Both tracks use this one path; the earlier per-track animation
                // special-casing caused the entry flicker, so it is gone.
                this.positionHighlight();

                // Keep ignoring trailing scroll events until the ease has run, then
                // restore normal live-scroll tracking.
                if (this._positioning) {
                    var selfPos = this;
                    clearTimeout(this._positioningTimer);
                    this._positioningTimer = setTimeout(function () {
                        selfPos._positioning = false;
                    }, this.transitionMs + 60);
                }

                this.showCard = false;
                await this.$nextTick();
                this.showCard = true;
                await this.$nextTick();
                this.positionCard();
                this.focusCard();
            },

            /**
             * Reveal UI a step needs to spotlight but that is normally hidden:
             *   reveal: "menu"       -> open (and keep open) the avatar dropdown
             *   reveal: "short-tab"  -> switch the ore-detail trade panel to the Short tab
             * The target is re-asserted on a short interval because page scripts
             * (nav.js closing the menu, an htmx swap) can undo it mid-step.
             */
            /**
             * Run a step's declarative server-side side effect, if any.
             *   action: "demo-short-open" -> open the Advanced tutorial's demo
             *       short so the position-dependent pages (portfolio, finances,
             *       dashboard, leaderboard) show live data for the rest of the
             *       tour. Idempotent and net-zero server-side; we additionally
             *       fire it at most once per tour run so back/forward navigation
             *       does not churn the position. It is cleared server-side when
             *       the track completes or is dismissed.
             * Any failure is swallowed: the tour continues regardless.
             */
            async runStepAction(step) {
                var action = step && step.action;
                if (!action) return;
                if (action === 'demo-short-open') {
                    if (this._demoShortOpened) return;
                    this._demoShortOpened = true;
                    await this.post('/tutorial/advanced/demo-short', {});
                }
            },

            /** Fire the side effects of every step from 0..index (resume path). */
            async replayActionsUpTo(index) {
                for (var i = 0; i <= index && i < this.steps.length; i++) {
                    await this.runStepAction(this.steps[i]);
                }
            },

            applyReveal(step) {
                clearInterval(this._revealTimer);
                var reveal = step && step.reveal;
                this.assertReveal(reveal);  // apply once immediately
                if (!reveal) return;
                var self = this;
                this._revealTimer = setInterval(function () {
                    if (self.showOverlay && self.currentStep && self.currentStep.reveal === reveal) {
                        self.assertReveal(reveal);
                    } else {
                        clearInterval(self._revealTimer);
                    }
                }, 200);
            },

            assertReveal(reveal) {
                // The avatar menu is a global; the trade/portfolio tab helpers
                // live only on their respective pages, so guard each call.
                setMenuOpen(reveal === 'menu');
                if (typeof root.switchTradeTab === 'function') {
                    // "long-tab" keeps the ore page on its default Long view (used by
                    // the step that points at the Short tab button without opening it,
                    // so returning to that step via Back restores the Long content).
                    if (reveal === 'short-tab') root.switchTradeTab('short');
                    else if (reveal === 'long-tab') root.switchTradeTab('long');
                }
                if (reveal === 'portfolio-shorts' && typeof root.switchPortfolioTab === 'function') {
                    root.switchPortfolioTab('shorts');
                }
            },

            /**
             * Resolve once the element's bounding rect is the SAME across two
             * consecutive animation frames (its layout has settled), or after a
             * short timeout. Used before positioning so the spotlight is placed
             * against the target's final geometry, not a mid-reflow one.
             */
            waitForStableRect(selector, timeoutMs) {
                timeoutMs = timeoutMs == null ? 500 : timeoutMs;
                var start = performance.now();
                return new Promise(function (resolve) {
                    var lastKey = null;
                    function key(el) {
                        var r = el.getBoundingClientRect();
                        return r.top + ',' + r.left + ',' + r.width + ',' + r.height;
                    }
                    (function check() {
                        var el = queryVisible(selector);
                        if (el) {
                            var k = key(el);
                            if (k === lastKey) return resolve(el);   // stable two frames running
                            lastKey = k;
                        }
                        if (performance.now() - start >= timeoutMs) return resolve(el || null);
                        root.requestAnimationFrame(check);
                    })();
                });
            },

            waitForElement(selector, timeoutMs) {
                var start = performance.now();
                return new Promise(function (resolve) {
                    (function check() {
                        var el = queryVisible(selector);
                        if (el) return resolve(el);
                        if (performance.now() - start >= timeoutMs) return resolve(null);
                        setTimeout(check, 100);
                    })();
                });
            },

            // --- positioning ---
            updateViewport() {
                this.vw = root.innerWidth;
                this.vh = root.innerHeight;
            },

            setHighlight(box) {
                this.highlightTop = box.top;
                this.highlightLeft = box.left;
                this.highlightWidth = box.width;
                this.highlightHeight = box.height;
            },

            positionHighlight() {
                var step = this.currentStep;
                if (!step) return false;
                var el = queryVisible(step.selector);
                if (!el) return false;
                var box = computeHighlight(el.getBoundingClientRect(), this.padding);
                if (isPhone() && !isNavTarget(el)) {
                    // Keep the frame out from under the fixed bars (a tall target
                    // would otherwise run behind them)
                    var ins = phoneInsets();
                    var lo = ins.top, hi = root.innerHeight - ins.bottom;
                    var top = Math.max(box.top, lo), bottom = Math.min(box.top + box.height, hi);
                    if (bottom > top) { box.top = top; box.height = bottom - top; }
                }
                this.setHighlight(box);
                return true;
            },

            /** Phone: card height to plan around (real height once shown, else an estimate). */
            phoneCardHeight(ins) {
                var card = this.$refs.card;
                var maxH = Math.max(120, root.innerHeight - ins.top - ins.bottom - 2 * PHONE_GAP);
                var h = card && card.offsetHeight ? card.offsetHeight : 300;
                return Math.min(h, maxH);
            },

            positionCardPhone(card, step) {
                var ins = phoneInsets();
                // A page that overflows sideways widens innerWidth/100vw past what the
                // screen shows; size and centre the card on the visible width instead
                var visibleW = Math.min(this.vw, document.documentElement.clientWidth || this.vw);
                card.style.width = Math.min(380, visibleW - 24) + 'px';
                // Cap the card to the space between the bars; long text scrolls inside it
                card.style.maxHeight = Math.max(120, root.innerHeight - ins.top - ins.bottom - 2 * PHONE_GAP) + 'px';
                var pos = computePhoneCardPosition(
                    step.position,
                    { top: this.highlightTop, left: this.highlightLeft,
                      width: this.highlightWidth, height: this.highlightHeight },
                    { width: card.offsetWidth, height: card.offsetHeight },
                    { width: visibleW, height: this.vh },
                    ins.top, ins.bottom, this.hideHighlight
                );
                this.cardTop = pos.top;
                this.cardLeft = pos.left;
                this.cardSide = pos.side;
            },

            positionCard() {
                var card = this.$refs.card;
                var step = this.currentStep;
                if (!card || !step) return;
                if (isPhone()) { this.positionCardPhone(card, step); return; }
                card.style.maxHeight = '';
                card.style.width = '';
                // With no spotlight, always centre the card
                var position = this.hideHighlight ? 'center' : step.position;
                var pos = computeCardPosition(
                    position,
                    { top: this.highlightTop, left: this.highlightLeft,
                      width: this.highlightWidth, height: this.highlightHeight },
                    { width: card.offsetWidth, height: card.offsetHeight },
                    { width: this.vw, height: this.vh }
                );
                this.cardTop = pos.top;
                this.cardLeft = pos.left;
                this.cardSide = pos.side;
            },

            /**
             * Would showing `el` require scrolling? True only when the target is not
             * already FULLY visible in the viewport (with a small margin). We no
             * longer try to CENTRE targets — many advanced targets sit near the page
             * bottom and can never reach the centre, so a centre-based test reported
             * "needs scroll" for things already on screen and forced a pointless
             * scroll (and the full-screen-reset) on every step. Scrolling only when
             * the target is genuinely off-screen means on-screen steps ease straight
             * from the previous element. Kept identical to scrollToTarget's test.
             */
            /** Phone: how far to scroll so `el` clears the bars and the card (0 = none). */
            phoneScrollDelta(el) {
                var ins = phoneInsets();
                var r = computeHighlight(el.getBoundingClientRect(), this.padding);
                r.bottom = r.top + r.height;
                var step = this.currentStep;
                return planPhoneLayout(r, {
                    vh: root.innerHeight, topInset: ins.top, bottomInset: ins.bottom,
                    cardHeight: this.phoneCardHeight(ins),
                    pref: step && step.position,
                    fixedTarget: isNavTarget(el)
                }).delta;
            },

            needsScroll(el) {
                if (isPhone()) return Math.abs(this.phoneScrollDelta(el)) >= 1;
                var rect = el.getBoundingClientRect();
                var vh = root.innerHeight;
                var margin = 12;
                return rect.top < margin || rect.bottom > vh - margin;
            },

            async scrollToTarget(el) {
                var tall = el.getBoundingClientRect().height > root.innerHeight;
                if (isPhone()) {
                    // Phone: scroll just enough to clear the fixed bars and leave room for the card
                    var delta = this.phoneScrollDelta(el);
                    if (Math.abs(delta) < 1) return;
                    root.scrollBy({ top: delta, left: 0, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
                } else {
                    if (!this.needsScroll(el)) return;   // already fully in view: no scroll
                    el.scrollIntoView({
                        behavior: prefersReducedMotion() ? 'auto' : 'smooth',
                        // When we do scroll, bring the target as far ONTO screen as the
                        // page allows — centre it (a near-bottom target just scrolls to
                        // the page's max, landing comfortably in view rather than barely
                        // peeking at the edge). A tall target aligns to the top instead.
                        // Note: whether we scroll at all is decided by needsScroll (full
                        // visibility), not by centring — so this doesn't re-introduce a
                        // scroll on every step.
                        block: tall ? 'start' : 'center'
                    });
                }
                // Wait until the smooth scroll has truly stopped before returning, so
                // the spotlight is positioned once, against the target's FINAL rect.
                var deadline = performance.now() + 1200;
                var lastY = root.scrollY;
                var stableCount = 0;
                await sleep(60);
                while (performance.now() < deadline) {
                    var y = root.scrollY;
                    if (y === lastY) {
                        if (++stableCount >= 2) break;   // stopped for 2 checks running
                    } else {
                        stableCount = 0;
                    }
                    lastY = y;
                    await sleep(50);
                }
            },

            onViewportChange() {
                if (!this.showOverlay) return;
                this.updateViewport();
                this.scheduleReposition();
            },

            onScroll() {
                if (!this.showOverlay) return;
                // While we're easing the spotlight to a new step's target, ignore
                // trailing scroll events from the just-finished programmatic scroll:
                // they would re-enable tracking (disabling the transition) and make
                // the box snap. User scrolling resumes normal tracking afterwards.
                if (this._positioning) return;
                this.tracking = true;
                clearTimeout(this._scrollTimer);
                var self = this;
                this._scrollTimer = setTimeout(function () { self.tracking = false; }, 150);
                this.scheduleReposition();
            },

            scheduleReposition() {
                if (this._rafPending) return;
                this._rafPending = true;
                var self = this;
                root.requestAnimationFrame(function () {
                    self._rafPending = false;
                    if (self.showOverlay && self.positionHighlight()) self.positionCard();
                });
            },

            onHtmxSettle() {
                if (!this.showOverlay) return;
                clearTimeout(this._settleTimer);
                var self = this;
                this._settleTimer = setTimeout(async function () {
                    var step = self.currentStep;
                    if (!step || !self.showOverlay) return;
                    if (self.positionHighlight()) {
                        self.positionCard();
                        return;
                    }
                    var el = await self.waitForElement(step.selector, 500);
                    if (el && self.positionHighlight()) {
                        self.positionCard();
                    } else if (self.showOverlay) {
                        console.warn('[tutorial] target vanished after htmx swap, skipping step', step.selector);
                        await self.goTo(self.currentIndex + 1, 1);
                    }
                }, SETTLE_DEBOUNCE_MS);
            },

            // --- skip / finish ---
            skip() {
                this.showConfirmSkip = true;
                var self = this;
                this.$nextTick(function () { self.focusFirstIn(self.$refs.confirm); });
            },

            cancelSkip() {
                this.showConfirmSkip = false;
                var self = this;
                this.$nextTick(function () { self.focusCard(); });
            },

            async confirmSkip() {
                await this.post('/tutorial/dismiss', { track_id: this.trackId });
                storageRemove(RESUME_DISMISSED_KEY);
                this.closeOverlay();
            },

            async finish() {
                await this.post('/tutorial/complete', { track_id: this.trackId });
                storageRemove(RESUME_DISMISSED_KEY);
                this.closeOverlay();
            },

            closeOverlay() {
                this._stepToken++;
                clearInterval(this._revealTimer);
                setMenuOpen(false);
                this.showCard = false;
                this.showConfirmSkip = false;
                this.showOverlay = false;
                document.documentElement.classList.remove('tutorial-active');
                this.highlightVisible = false;
                this.active = false;
                // Next tour run (replay) should open its own demo short afresh.
                this._demoShortOpened = false;
                if (this._prevFocus && typeof this._prevFocus.focus === 'function') {
                    try { this._prevFocus.focus(); } catch (e) { /* ignore */ }
                }
                this._prevFocus = null;
            },

            // --- resume prompt (delegated to the standard .flash--toast system) ---

            /** Build and show a resume toast in the shared #notification-toasts container. */
            offerResume() {
                var container = document.getElementById('notification-toasts');
                if (!container) return;
                if (container.querySelector('[data-tutorial-resume]')) return; // already showing

                var toast = document.createElement('div');
                toast.className = 'flash flash--toast flash--default flash--clickable';
                toast.setAttribute('role', 'status');
                toast.setAttribute('data-toast', '');
                toast.setAttribute('data-tutorial-resume', this.trackId || '');
                toast.setAttribute('data-duration', String(this.resumeMs));
                toast.style.cursor = 'pointer';
                toast.innerHTML =
                    '<span class="flash__icon" aria-hidden="true">' +
                    '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 -960 960 960" fill="currentColor"><path d="M320-200v-560l440 280-440 280Z"/></svg>' +
                    '</span>' +
                    '<div class="flash__message">Resume your tutorial where you left off?</div>' +
                    '<div class="flash__progress" aria-hidden="true"><span class="flash__progress-fill" data-toast-progress></span></div>';

                var self = this;
                toast.addEventListener('click', function () {
                    // A swipe ends in a click too; ignore it if the toast is being dismissed
                    if (toast.classList.contains('flash--leaving')) return;
                    toast.remove();
                    self.resumeTutorial();
                });

                container.appendChild(toast);
                // Offered once per session: whether the player taps it, swipes it,
                // or lets it time out, we do not nag again on later page loads.
                // Tapping to resume clears this (resumeAt), so a later pause can prompt again.
                storageSet(RESUME_DISMISSED_KEY, this.trackId || '');
                // notifications.js initialises any [data-toast] it finds (swipe + timer)
                if (root.OreXToasts && typeof root.OreXToasts.init === 'function') {
                    root.OreXToasts.init(toast);
                }
            },

            async resumeTutorial() {
                await this.resumeAt(this.trackId, this.currentIndex, true);
            },

            /** Continue a saved tutorial at `index`, navigating first if allowed and needed. */
            async resumeAt(trackId, index, allowNavigate) {
                storageRemove(RESUME_DISMISSED_KEY);
                var track = await this.fetchTrack(trackId);
                if (!track || !track.steps.length) return;
                this.loadTrack(track);
                if (index < 0 || index >= this.steps.length) index = 0;
                var step = this.steps[index];
                // Resuming can drop the player straight into a step that assumes
                // an earlier action already ran (e.g. the demo short was opened at
                // the shorting step, several steps back). Replay any such action
                // whose step is at or before the resume point so the pages ahead
                // show live data. Actions are idempotent, so this is safe.
                await this.replayActionsUpTo(index);
                if (allowNavigate && needsPageNavigation(root.location.pathname, step.route)) {
                    this.navigateTo(step.route, index);
                    return;
                }
                await this.showStep(index, 1);
            },

            // --- keyboard / focus ---
            onKeydown(e) {
                if (!this.showOverlay) return;
                if (e.key === 'Escape') {
                    e.preventDefault();
                    if (this.showConfirmSkip) this.cancelSkip();
                    else this.skip();
                    return;
                }
                if (e.key === 'Tab') this.trapFocus(e);
            },

            trapFocus(e) {
                var container = this.showConfirmSkip ? this.$refs.confirm : this.$refs.card;
                if (!container) return;
                var items = container.querySelectorAll(FOCUSABLE);
                if (!items.length) { e.preventDefault(); return; }
                var first = items[0];
                var last = items[items.length - 1];
                var current = document.activeElement;
                if (!container.contains(current)) {
                    e.preventDefault();
                    first.focus();
                } else if (e.shiftKey && current === first) {
                    e.preventDefault();
                    last.focus();
                } else if (!e.shiftKey && current === last) {
                    e.preventDefault();
                    first.focus();
                }
            },

            focusFirstIn(container) {
                if (!container) return;
                var first = container.querySelector(FOCUSABLE);
                if (first) first.focus();
            },

            focusCard() {
                var card = this.$refs.card;
                if (!card) return;
                var primary = card.querySelector('[data-tutorial-primary]');
                if (primary && !primary.disabled) primary.focus();
                else this.focusFirstIn(card);
            }
        };
    }

    document.addEventListener('alpine:init', function () {
        root.Alpine.data('tutorial', tutorialComponent);
    });
})(typeof window !== 'undefined' ? window : globalThis);
