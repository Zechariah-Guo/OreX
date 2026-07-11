/**
 * Theme Manager — Settings page theme switching interactions.
 *
 * Loaded only on the settings page. The inline theme-init script
 * in base.html handles initial application on all pages to prevent FOUC.
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4, 9.1
 */
(function () {
    'use strict';

    var STORAGE_KEY_THEME = 'orex-theme';
    var VALID_THEMES = ['light', 'dark', 'system'];

    /**
     * Resolve the OS preferred colour scheme.
     * Falls back to 'light' if matchMedia is not supported.
     * @returns {'light'|'dark'}
     */
    function resolveSystemTheme() {
        try {
            if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
                return 'dark';
            }
        } catch (e) {
            // matchMedia threw — treat as unsupported
        }
        return 'light';
    }

    /**
     * Read the saved theme from localStorage.
     * Returns 'system' if localStorage is unavailable or value is corrupted.
     * @returns {'light'|'dark'|'system'}
     */
    function getTheme() {
        try {
            var stored = localStorage.getItem(STORAGE_KEY_THEME);
            if (stored && VALID_THEMES.indexOf(stored) !== -1) {
                return stored;
            }
            // Corrupted or missing value — reset to 'light'
            localStorage.setItem(STORAGE_KEY_THEME, 'light');
        } catch (e) {
            // localStorage unavailable — fall back silently
        }
        return 'light';
    }

    /**
     * Apply the given theme mode to the document.
     * If mode is 'system', resolves the OS preference first.
     * @param {'light'|'dark'|'system'} mode
     */
    function applyTheme(mode) {
        var resolved = mode;
        if (mode === 'system') {
            resolved = resolveSystemTheme();
        }
        document.documentElement.setAttribute('data-theme', resolved);
    }

    /**
     * Save the theme to localStorage and apply it immediately.
     * @param {'light'|'dark'|'system'} mode
     */
    function setTheme(mode) {
        if (VALID_THEMES.indexOf(mode) === -1) {
            mode = 'light';
        }
        try {
            localStorage.setItem(STORAGE_KEY_THEME, mode);
        } catch (e) {
            // localStorage unavailable — apply without persisting
        }
        applyTheme(mode);
        updateAriaChecked(mode);
    }

    /**
     * Update aria-checked attributes on theme switcher buttons.
     * @param {string} activeMode - The currently active theme mode.
     */
    function updateAriaChecked(activeMode) {
        var buttons = document.querySelectorAll('.theme-switcher__btn');
        for (var i = 0; i < buttons.length; i++) {
            var btn = buttons[i];
            var isActive = btn.getAttribute('data-theme') === activeMode;
            btn.setAttribute('aria-checked', isActive ? 'true' : 'false');
        }
    }

    /**
     * Initialise theme manager: read preference, set UI state, attach handlers.
     */
    function init() {
        var currentTheme = getTheme();

        // Apply theme (in case inline script missed something)
        applyTheme(currentTheme);

        // Set correct aria-checked on theme buttons
        updateAriaChecked(currentTheme);

        // Attach click handlers to theme switcher buttons
        var buttons = document.querySelectorAll('.theme-switcher__btn');
        for (var i = 0; i < buttons.length; i++) {
            buttons[i].addEventListener('click', function () {
                var mode = this.getAttribute('data-theme');
                setTheme(mode);
            });
        }
    }

    // Listen for OS colour scheme changes — re-apply when in 'system' mode
    try {
        var mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        var handleSystemChange = function () {
            var current = getTheme();
            if (current === 'system') {
                applyTheme('system');
            }
        };
        // Modern browsers use addEventListener; older ones use addListener
        if (mediaQuery.addEventListener) {
            mediaQuery.addEventListener('change', handleSystemChange);
        } else if (mediaQuery.addListener) {
            mediaQuery.addListener(handleSystemChange);
        }
    } catch (e) {
        // matchMedia not supported — no system theme detection
    }

    // Initialise on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
