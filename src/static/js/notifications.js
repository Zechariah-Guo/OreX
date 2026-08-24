/**
 * Toast notification manager and polling loop.
 * Handles initial page-load flash toasts, dynamically inserted
 * notification toasts delivered via htmx, and periodic polling for
 * new notifications (red dot + toast injection).
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

        // ─── Swipe / Drag Right to Dismiss ───────────────────────────────────
        var startX = 0;
        var currentX = 0;
        var isDragging = false;
        var DISMISS_THRESHOLD = 100; // px to swipe right before dismissing

        function onPointerDown(e) {
            if (removed) return;
            isDragging = true;
            startX = e.clientX || (e.touches && e.touches[0].clientX) || 0;
            currentX = 0;
            // Kill the entrance animation so inline styles can take effect
            toast.style.animation = 'none';
            toast.style.opacity = '1';
            toast.style.transform = 'translateX(0)';
            toast.style.transition = 'none';
        }

        function onPointerMove(e) {
            if (!isDragging || removed) return;
            var clientX = e.clientX || (e.touches && e.touches[0].clientX) || 0;
            currentX = clientX - startX;
            // Only allow dragging to the right (positive direction)
            if (currentX < 0) currentX = 0;
            toast.style.transform = 'translateX(' + currentX + 'px)';
            toast.style.transition = 'transform 0.2s ease, opacity 0.2s ease';
            toast.style.opacity = String(1 - (currentX / (DISMISS_THRESHOLD * 2)));
        }

        function onPointerUp() {
            if (!isDragging || removed) return;
            isDragging = false;
            if (currentX >= DISMISS_THRESHOLD) {
                // Swiped far enough — dismiss
                toast.style.transition = '';
                dismiss();
            } else {
                // Snap back smoothly
                toast.style.transition = 'transform 0.2s ease, opacity 0.2s ease';
                toast.style.transform = 'translateX(0)';
                toast.style.opacity = '1';
            }
        }

        // Touch events (mobile)
        toast.addEventListener('touchstart', onPointerDown, { passive: true });
        toast.addEventListener('touchmove', onPointerMove, { passive: true });
        toast.addEventListener('touchend', onPointerUp);
        toast.addEventListener('touchcancel', onPointerUp);

        // Mouse events (desktop drag)
        toast.addEventListener('mousedown', onPointerDown);
        toast.addEventListener('mousemove', onPointerMove);
        toast.addEventListener('mouseup', onPointerUp);
        toast.addEventListener('mouseleave', onPointerUp);

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

    // ─── Notification Polling Loop ───────────────────────────────────────────────

    var POLL_INTERVAL = 20000; // 20 seconds
    var lastId = 0;           // Watermark: last notification ID seen

    /**
     * Determine if the user is authenticated by checking for the inbox icon
     * in the profile dropdown. Returns the inbox icon element or null.
     */
    function getInboxIcon() {
        return document.querySelector('.nav__dropdown-icon[title="Inbox"]');
    }

    /**
     * Toggle the red dot (unread indicator) on the inbox icon.
     */
    function updateUnreadDot(inboxIcon, hasUnread) {
        if (!inboxIcon) {
            return;
        }
        if (hasUnread) {
            inboxIcon.classList.add('nav__dropdown-icon--unread');
            inboxIcon.setAttribute('aria-label', 'Inbox - unread notifications');
        } else {
            inboxIcon.classList.remove('nav__dropdown-icon--unread');
            inboxIcon.setAttribute('aria-label', 'Inbox');
        }
    }

    /**
     * Create a toast DOM element from a notification object returned by the poll endpoint.
     */
    function createToastElement(notification) {
        var tag = notification.action_url ? 'a' : 'div';
        var el = document.createElement(tag);

        // Base classes
        var classes = ['flash', 'flash--toast'];
        if (notification.css_class) {
            classes.push(notification.css_class);
        }
        if (notification.action_url) {
            classes.push('flash--clickable');
            el.setAttribute('href', notification.action_url);
            el.setAttribute('aria-label', notification.message);
        } else {
            // No action_url — toast is interactable (for future swipe-to-dismiss etc.)
            // but does not navigate anywhere on click
            classes.push('flash--clickable');
            el.style.cursor = 'pointer';
        }
        el.className = classes.join(' ');
        el.setAttribute('role', 'alert');
        el.setAttribute('data-toast', '');
        el.setAttribute('data-duration', String(notification.duration || 3000));

        // Icon
        var iconSpan = document.createElement('span');
        iconSpan.className = 'flash__icon';
        iconSpan.setAttribute('aria-hidden', 'true');
        if (notification.icon) {
            iconSpan.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 -960 960 960" fill="currentColor"><path d="' + notification.icon + '"/></svg>';
        }
        el.appendChild(iconSpan);

        // Message
        var msgDiv = document.createElement('div');
        msgDiv.className = 'flash__message';
        msgDiv.textContent = notification.message;
        el.appendChild(msgDiv);

        // Progress bar
        var progressDiv = document.createElement('div');
        progressDiv.className = 'flash__progress';
        progressDiv.setAttribute('aria-hidden', 'true');
        var progressFill = document.createElement('span');
        progressFill.className = 'flash__progress-fill';
        progressFill.setAttribute('data-toast-progress', '');
        progressDiv.appendChild(progressFill);
        el.appendChild(progressDiv);

        return el;
    }

    /**
     * Play the achievement sound effect if the user has interacted.
     */
    function playAchievementSound() {
        if (!userHasInteracted) {
            return;
        }
        try {
            var sound = new Audio('/static/audio/advancement.mp3');
            sound.volume = 0.5;
            sound.play().catch(function () {});
        } catch (e) {
            // Audio playback not available — silently skip
        }
    }

    // ─── Toast Queue (paused while profile dropdown is open) ────────────────────

    var toastQueue = [];

    /**
     * Check whether the profile dropdown is currently open.
     */
    function isDropdownOpen() {
        var dropdown = document.getElementById('nav-dropdown');
        return dropdown ? dropdown.classList.contains('nav__dropdown--open') : false;
    }

    /**
     * Flush any queued notifications as toasts (called when dropdown closes).
     */
    function flushToastQueue() {
        if (toastQueue.length === 0) {
            return;
        }
        var queued = toastQueue.slice();
        toastQueue = [];
        displayToasts(queued);
    }

    /**
     * Actually render toast elements into the container and initialise them.
     */
    function displayToasts(notifications) {
        var container = document.getElementById('notification-toasts');
        if (!container || notifications.length === 0) {
            return;
        }

        var hasAchievement = false;

        notifications.forEach(function (n) {
            var toast = createToastElement(n);
            container.appendChild(toast);
            initToast(toast);

            if (n.category === 'achievement' || n.css_class === 'flash--achievement') {
                hasAchievement = true;
            }
        });

        if (hasAchievement) {
            playAchievementSound();
        }
    }

    /**
     * Inject toast elements for new notifications and initialise them.
     * If the profile dropdown is open, queue notifications for later display.
     */
    function showToasts(notifications) {
        if (!notifications || notifications.length === 0) {
            return;
        }

        if (isDropdownOpen()) {
            // Queue notifications while the dropdown is open
            toastQueue = toastQueue.concat(notifications);
            return;
        }

        displayToasts(notifications);
    }

    // Observe the dropdown for class changes — flush queue when it closes
    document.addEventListener('DOMContentLoaded', function () {
        var dropdown = document.getElementById('nav-dropdown');
        if (!dropdown) {
            return;
        }

        var observer = new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
                    if (dropdown.classList.contains('nav__dropdown--open')) {
                        // Dropdown just opened → instantly remove any visible toasts
                        var activeToasts = document.querySelectorAll('[data-toast]');
                        for (var i = 0; i < activeToasts.length; i++) {
                            activeToasts[i].remove();
                        }
                    } else if (toastQueue.length > 0) {
                        // Dropdown just closed → flush queued toasts
                        flushToastQueue();
                    }
                }
            });
        });

        observer.observe(dropdown, { attributes: true, attributeFilter: ['class'] });
    });

    /**
     * Poll the server for new notifications and handle the response.
     */
    function pollNotifications() {
        var inboxIcon = getInboxIcon();

        // Only poll when user is authenticated (inbox icon present)
        if (!inboxIcon) {
            return;
        }

        fetch('/inbox/poll?since=' + lastId, {
            method: 'GET',
            credentials: 'same-origin',
            headers: {
                'Accept': 'application/json'
            }
        })
        .then(function (response) {
            if (!response.ok) {
                return null;
            }
            return response.json();
        })
        .then(function (data) {
            if (!data) {
                return;
            }

            // Update the watermark
            if (data.last_id && data.last_id > lastId) {
                lastId = data.last_id;
            }

            // Toggle red dot based on has_unread
            updateUnreadDot(inboxIcon, data.has_unread);

            // Show toasts for new notifications
            if (data.notifications && data.notifications.length > 0) {
                showToasts(data.notifications);
            }
        })
        .catch(function () {
            // Network error — silently skip this poll cycle
        });
    }

    // Start the polling loop after DOM is ready
    document.addEventListener('DOMContentLoaded', function () {
        // Only start polling if user is authenticated
        if (getInboxIcon()) {
            setInterval(pollNotifications, POLL_INTERVAL);
        }
    });
})();
