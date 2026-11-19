/**
 * Falling Ores — Cosmetic background effect for advancement themes.
 *
 * Activates when <html> has class "cosmetic-money" or "cosmetic-gold".
 * - Money theme: falling Emerald.webp images
 * - Gold theme: falling Gold_Ingot.webp images
 *
 * Lower frequency (800ms) and more transparent (0.12) than the landing page
 * variant to avoid distracting from working pages.
 *
 * Self-contained: creates the .falling-container div if it doesn't exist,
 * cleans up if the theme class is removed.
 */
(function() {
    'use strict';

    var INTERVAL_MS = 800;
    var OPACITY = 0.12;
    var MIN_SIZE = 30;
    var MAX_SIZE = 55;
    var MIN_DURATION = 8;
    var MAX_DURATION = 14;
    // Steady-state count: average duration / spawn interval (11s / 0.8s)
    var SEED_COUNT = Math.round(((MIN_DURATION + MAX_DURATION) / 2) * 1000 / INTERVAL_MS);

    var intervalId = null;
    var container = null;
    var observing = false;
    var runningTheme = null;

    function getActiveTheme() {
        var root = document.documentElement;
        if (root.classList.contains('cosmetic-money')) return 'money';
        if (root.classList.contains('cosmetic-gold')) return 'gold';
        return null;
    }

    function getOreImage(theme) {
        if (theme === 'money') return '/static/images/ores/Emerald.webp';
        if (theme === 'gold') return '/static/images/ores/Gold_Ingot.webp';
        return null;
    }

    function ensureContainer() {
        container = document.getElementById('falling-ores-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'falling-ores-container';
            container.className = 'falling-container';
            document.body.appendChild(container);
        }
        return container;
    }

    function removeContainer() {
        if (container) {
            container.remove();
            container = null;
        }
    }

    function createFallingOre(oreSrc, preseed) {
        if (!container) return;

        var img = document.createElement('img');
        img.src = oreSrc;
        img.className = 'falling-img';
        img.alt = '';
        img.setAttribute('aria-hidden', 'true');

        // Random horizontal position (2% – 92%)
        img.style.left = (Math.random() * 90 + 2) + '%';

        // Random size
        var size = Math.random() * (MAX_SIZE - MIN_SIZE) + MIN_SIZE;
        img.style.width = size + 'px';
        img.style.height = size + 'px';

        // Opacity
        img.style.opacity = OPACITY;

        // Random fall duration
        var duration = Math.random() * (MAX_DURATION - MIN_DURATION) + MIN_DURATION;
        img.style.animationDuration = duration + 's';

        // Pre-seeded ores start part-way through their fall (negative delay),
        // so progress is spread over the actual viewport height.
        var elapsed = preseed ? Math.random() * duration : 0;
        if (preseed) img.style.animationDelay = '-' + elapsed + 's';

        container.appendChild(img);

        // Remove after animation completes
        setTimeout(function() {
            if (img.parentNode) img.remove();
        }, (duration - elapsed) * 1000 + 500);
    }

    function start(theme) {
        var oreSrc = getOreImage(theme);
        if (!oreSrc) return;

        ensureContainer();

        // Pre-seed a steady-state batch already mid-fall (skipped for reduced motion)
        var reduce = window.matchMedia &&
            window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (!reduce) {
            for (var i = 0; i < SEED_COUNT; i++) {
                createFallingOre(oreSrc, true);
            }
        }

        // Continuous creation
        intervalId = setInterval(function() {
            createFallingOre(oreSrc);
        }, INTERVAL_MS);
    }

    function stop() {
        if (intervalId !== null) {
            clearInterval(intervalId);
            intervalId = null;
        }
        removeContainer();
    }

    function sync() {
        var theme = getActiveTheme();
        // Unrelated class toggles on <html> (e.g. nav-hidden on scroll) must
        // not restart the effect: only act when the theme actually changed.
        if (theme === runningTheme && (theme === null || intervalId !== null)) return;
        stop();
        runningTheme = theme;
        if (theme) start(theme);
    }

    // Initial check
    sync();

    // Watch for class changes on <html> to react to theme switches
    if (typeof MutationObserver !== 'undefined' && !observing) {
        var observer = new MutationObserver(function(mutations) {
            for (var i = 0; i < mutations.length; i++) {
                if (mutations[i].attributeName === 'class') {
                    sync();
                    break;
                }
            }
        });
        observer.observe(document.documentElement, { attributes: true });
        observing = true;
    }
})();
