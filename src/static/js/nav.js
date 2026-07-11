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

        // Assign avatar colour based on username
        const username = avatarBtn.dataset.username || '';
        const colourIndex = hashUsername(username) % AVATAR_COLOURS.length;
        const bgColour = AVATAR_COLOURS[colourIndex];
        avatarBtn.style.backgroundColor = bgColour;
        avatarBtn.style.color = getContrastingTextColour(bgColour);

        // Toggle dropdown on click
        avatarBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            const isOpen = dropdown.classList.toggle('nav__dropdown--open');
            avatarBtn.setAttribute('aria-expanded', isOpen);
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', function (e) {
            if (!dropdown.contains(e.target) && e.target !== avatarBtn) {
                dropdown.classList.remove('nav__dropdown--open');
                avatarBtn.setAttribute('aria-expanded', 'false');
            }
        });

        // Close on Escape key
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                dropdown.classList.remove('nav__dropdown--open');
                avatarBtn.setAttribute('aria-expanded', 'false');
            }
        });
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
