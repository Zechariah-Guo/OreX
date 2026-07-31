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
    var SEED_COUNT = 3;

    var intervalId = null;
    var container = null;
    var observing = false;

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

    function createFallingOre(oreSrc) {
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

        container.appendChild(img);

        // Remove after animation completes
        setTimeout(function() {
            if (img.parentNode) img.remove();
        }, duration * 1000 + 500);
    }

    function start(theme) {
        var oreSrc = getOreImage(theme);
        if (!oreSrc) return;

        ensureContainer();

        // Seed a few on load
        for (var i = 0; i < SEED_COUNT; i++) {
            (function(delay) {
                setTimeout(function() { createFallingOre(oreSrc); }, delay);
            })(i * 250);
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
        if (theme) {
            // If already running for same theme, no-op
            if (intervalId !== null) {
                stop();
            }
            start(theme);
        } else {
            stop();
        }
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
