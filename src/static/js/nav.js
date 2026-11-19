/**
 * Navigation bar interactions:
 * - Avatar colour assignment (deterministic based on username)
 * - Dropdown toggle on avatar click
 */
(function () {
    'use strict';

    const AVATAR_COLOURS = [
        '#161616',
        '#D8D8D8',
        '#B87333',
        '#F6CF0C',
        '#26619C',
        '#D33B2B',
        '#50C878',
        '#B9F2FF',
        '#241F20'
    ];

    /**
     * Simple hash of a string to pick a deterministic colour index.
     */
    function hashUsername(username) {
        let hash = 0;
        for (let i = 0; i < username.length; i++) {
            hash = ((hash << 5) - hash) + username.charCodeAt(i);
            hash |= 0; // Convert to 32-bit int
        }
        return Math.abs(hash);
    }

    /**
     * Returns black or white depending on which contrasts more with the bg.
     * Uses relative luminance formula.
     */
    function getContrastingTextColour(hex) {
        const r = parseInt(hex.slice(1, 3), 16) / 255;
        const g = parseInt(hex.slice(3, 5), 16) / 255;
        const b = parseInt(hex.slice(5, 7), 16) / 255;

        const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        return luminance > 0.4 ? '#000000' : '#FFFFFF';
    }

    function init() {
        const avatarBtn = document.getElementById('nav-avatar-btn');
        const dropdown = document.getElementById('nav-dropdown');

        if (!avatarBtn || !dropdown) return;

        // Avatar colour: use server-provided inline style if present,
        // otherwise fall back to client-side hash (shouldn't happen normally)
        if (!avatarBtn.style.backgroundColor || avatarBtn.style.backgroundColor === 'rgb(74, 74, 74)') {
            const username = avatarBtn.dataset.username || '';
            const colourIndex = hashUsername(username) % AVATAR_COLOURS.length;
            const bgColour = AVATAR_COLOURS[colourIndex];
            avatarBtn.style.backgroundColor = bgColour;
            avatarBtn.style.color = getContrastingTextColour(bgColour);
        }

        function closeMenu() {
            dropdown.classList.remove('nav__dropdown--open');
            avatarBtn.setAttribute('aria-expanded', 'false');
        }

        // Toggle dropdown on click
        avatarBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            const isOpen = dropdown.classList.toggle('nav__dropdown--open');
            avatarBtn.setAttribute('aria-expanded', isOpen);
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', function (e) {
            // Phone tutorial: the tour decides when the menu is open, so the
            // tap that advances it must not close the menu first (flicker)
            if (document.documentElement.classList.contains('tutorial-active') &&
                window.matchMedia('(max-width: 640px)').matches) return;
            if (!dropdown.contains(e.target) && e.target !== avatarBtn) {
                closeMenu();
            }
        });

        // Close on Escape key
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                closeMenu();
            }
        });

        // Close when a menu link is followed, and when returning via bfcache
        dropdown.addEventListener('click', function (e) {
            if (e.target.closest('a')) closeMenu();
        });
        window.addEventListener('pageshow', closeMenu);

        initPhoneBars(dropdown, closeMenu);
        initLongPress();
    }

    /**
     * Phone only (max-width: 640px): hide the bars on scroll down, show on
     * scroll up. Close the avatar menu on scroll.
     */
    function initPhoneBars(dropdown, closeMenu) {
        const phone = window.matchMedia('(max-width: 640px)');
        const root = document.documentElement;
        if (!document.querySelector('.main-nav--auth')) return;

        // Top zone: the bars are always shown and no direction is computed.
        // It is as tall as the top bar, so a bounce that settles a few px
        // below 0 cannot read as "scrolled down".
        const TOP_ZONE = 64;
        // Hysteresis: the bars only change after this many px of travel in one
        // direction since the last direction change. Overscroll bounces at the
        // top or bottom reverse by a few px and never reach it.
        const HIDE_DISTANCE = 12;
        const SHOW_DISTANCE = 16;

        let lastY = clampY(window.scrollY);
        let direction = 0;   // 1 = down, -1 = up
        let travelled = 0;   // px moved in `direction` since it last changed
        let ticking = false;

        function show() { root.classList.remove('nav-hidden'); }

        function maxScroll() {
            return Math.max(0, root.scrollHeight - window.innerHeight);
        }

        // Rubber-banding (Android Chrome glow/bounce, iOS) can report a
        // position below 0 or past the end: clamp it to the real range.
        function clampY(y) {
            return Math.min(Math.max(0, y || 0), maxScroll());
        }

        function update() {
            ticking = false;
            if (!phone.matches) return;

            const y = clampY(window.scrollY);
            const dy = y - lastY;
            lastY = y;

            if (y <= TOP_ZONE) {
                direction = 0;
                travelled = 0;
                show();
                return;
            }
            if (dy === 0) return;

            const dir = dy > 0 ? 1 : -1;
            if (dir !== direction) {
                direction = dir;
                travelled = 0;
            }
            travelled += Math.abs(dy);

            // A running tutorial keeps both bars up and the menu as it set it
            if (root.classList.contains('tutorial-active')) { show(); return; }
            if (travelled >= HIDE_DISTANCE && dropdown.classList.contains('nav__dropdown--open')) {
                closeMenu();
                return;
            }
            if (maxScroll() <= 80) { show(); return; }

            if (dir > 0 && travelled >= HIDE_DISTANCE) {
                root.classList.add('nav-hidden');
            } else if (dir < 0 && travelled >= SHOW_DISTANCE) {
                show();
            }
        }

        window.addEventListener('scroll', function () {
            if (!phone.matches || ticking) return;
            ticking = true;
            window.requestAnimationFrame(update);
        }, { passive: true });

        document.addEventListener('focusin', function (e) {
            if (phone.matches && e.target.closest &&
                e.target.closest('.nav__links, .nav__brand, #nav-dropdown')) {
                show();
            }
        });

        phone.addEventListener('change', function () {
            if (!phone.matches) show();
        });
    }

    /**
     * Phone only: holding a nav icon (touch) for 450ms shows its label; the
     * click that follows the release is suppressed so peeking never navigates.
     */
    function initLongPress() {
        const phone = window.matchMedia('(max-width: 640px)');
        const SELECTOR = '.nav__dropdown-icon, .nav__dropdown-item, .nav__tab-link';
        let tooltip = null;
        let timer = null;
        let shown = false;
        let target = null;
        let startX = 0;
        let startY = 0;

        function getTooltip() {
            if (!tooltip) {
                tooltip = document.createElement('div');
                tooltip.className = 'nav__tooltip';
                tooltip.setAttribute('role', 'tooltip');
                document.body.appendChild(tooltip);
            }
            return tooltip;
        }

        function labelFor(el) {
            const label = el.querySelector('.nav__dropdown-label');
            if (label) return label.textContent.trim();
            return el.getAttribute('aria-label') || el.getAttribute('title') || '';
        }

        function showLabel(el) {
            const text = labelFor(el);
            if (!text) return;
            const tip = getTooltip();
            tip.textContent = text;
            tip.classList.add('nav__tooltip--visible');
            const r = el.getBoundingClientRect();
            const w = tip.offsetWidth;
            const h = tip.offsetHeight;
            const inBottomBar = !!el.closest('.nav__links') && !el.closest('#nav-dropdown');
            let left = r.left + r.width / 2 - w / 2;
            left = Math.max(4, Math.min(left, window.innerWidth - w - 4));
            let top = inBottomBar ? r.top - h - 8 : r.bottom + 8;
            top = Math.max(4, Math.min(top, window.innerHeight - h - 4));
            tip.style.left = left + 'px';
            tip.style.top = top + 'px';
            shown = true;
        }

        function hideLabel() {
            if (tooltip) tooltip.classList.remove('nav__tooltip--visible');
        }

        function cancel() {
            clearTimeout(timer);
            timer = null;
            target = null;
            hideLabel();
        }

        function suppressNextClick() {
            function swallow(ev) {
                ev.preventDefault();
                ev.stopPropagation();
            }
            document.addEventListener('click', swallow, { capture: true, once: true });
            // If no click follows (e.g. pointer moved away), drop the guard.
            setTimeout(function () {
                document.removeEventListener('click', swallow, true);
            }, 400);
        }

        function release() {
            const wasShown = shown;
            cancel();
            shown = false;
            if (wasShown) suppressNextClick();
        }

        document.addEventListener('pointerdown', function (e) {
            if (!phone.matches || e.pointerType !== 'touch') return;
            const el = e.target.closest && e.target.closest(SELECTOR);
            if (!el || !el.closest('.main-nav--auth')) return;
            cancel();
            shown = false;
            target = el;
            startX = e.clientX;
            startY = e.clientY;
            timer = setTimeout(function () {
                timer = null;
                showLabel(el);
            }, 450);
        });

        document.addEventListener('pointermove', function (e) {
            if (!target) return;
            const moved = Math.hypot(e.clientX - startX, e.clientY - startY) > 10;
            const left = !target.contains(document.elementFromPoint(e.clientX, e.clientY));
            if (moved || left) {
                cancel();
                shown = false;
            }
        });

        document.addEventListener('pointerup', function () { if (target || shown) release(); });
        document.addEventListener('pointercancel', function () { cancel(); shown = false; });

        // The browser's own long-press (context menu / link preview / drag)
        // would otherwise end the press (pointercancel) while the finger is down.
        document.addEventListener('contextmenu', function (e) {
            if (!phone.matches) return;
            if (timer || shown || target ||
                (e.target.closest && e.target.closest(SELECTOR) && e.target.closest('.main-nav--auth'))) {
                e.preventDefault();
            }
        });
        document.addEventListener('dragstart', function (e) {
            if (phone.matches && e.target.closest && e.target.closest('.main-nav--auth')) e.preventDefault();
        });
        document.addEventListener('selectstart', function (e) {
            if (phone.matches && (timer || shown || target)) e.preventDefault();
        });

        // Dismiss the label when the finger lifts (touchend is the reliable
        // signal on iOS where pointerup can be skipped after a long press).
        document.addEventListener('touchend', function () { if (target || shown) release(); }, { passive: true });
        document.addEventListener('touchcancel', function () { cancel(); shown = false; }, { passive: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Sticky nav: add translucent background on scroll
    const nav = document.querySelector('.main-nav');
    if (nav) {
        window.addEventListener('scroll', function () {
            if (window.scrollY > 10) {
                nav.classList.add('main-nav--scrolled');
            } else {
                nav.classList.remove('main-nav--scrolled');
            }
        }, { passive: true });
    }
})();
