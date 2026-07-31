/**
 * Toast notification manager.
 * Handles both initial page-load flash toasts and dynamically inserted
 * notification toasts delivered via htmx polling.
 */
(function () {
    'use strict';

    // Track whether the user has interacted with the page (needed for autoplay policy)
    var userHasInteracted = false;
    var interactionEvents = ['click', 'keydown', 'touchstart', 'pointerdown'];
    function markInteracted() {
        userHasInteracted = true;
        interactionEvents.forEach(function (evt) {
            document.removeEventListener(evt, markInteracted, { capture: true });
        });
    }
    interactionEvents.forEach(function (evt) {
        document.addEventListener(evt, markInteracted, { capture: true, once: true });
    });

    function initToast(toast) {
        // Skip if already initialised
        if (toast.dataset.toastInit) {
            return;
        }
        toast.dataset.toastInit = '1';

        const duration = Number(toast.dataset.duration || 3000);
        const progress = toast.querySelector('[data-toast-progress]');
        let removed = false;

        toast.style.setProperty('--toast-duration', `${duration}ms`);

        if (progress) {
            progress.style.animationDuration = `${duration}ms`;
        }

        const dismiss = () => {
            if (removed) {
                return;
            }
            removed = true;
            toast.classList.add('flash--leaving');
            window.setTimeout(() => {
                toast.remove();
            }, 350);
        };

        window.setTimeout(dismiss, duration);
    }

    // Initialise any toasts already in the DOM on page load
    document.addEventListener('DOMContentLoaded', () => {
        const toasts = Array.from(document.querySelectorAll('[data-toast]'));
        toasts.forEach(initToast);
    });

    // Handle toasts injected by htmx (notification polling)
    document.addEventListener('htmx:afterSwap', (event) => {
        const target = event.detail.target;
        if (!target) {
            return;
        }
        const newToasts = Array.from(target.querySelectorAll('[data-toast]'));
        newToasts.forEach(initToast);

        // Play achievement sound for advancement toasts
        const advancementToasts = newToasts.filter(t => t.classList.contains('flash--advancement'));
        if (advancementToasts.length > 0 && userHasInteracted) {
            try {
                const sound = new Audio('/static/audio/advancement.mp3');
                sound.volume = 0.5;
                sound.play().catch(() => {});
            } catch (e) {
                // Audio playback not available — silently skip
            }
        }
    });
})();
