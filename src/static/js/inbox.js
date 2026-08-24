/**
 * Inbox page interactivity — complements htmx declarative attrs.
 * Handles filter tab active state syncing, list item read-state
 * visual updates, and keyboard accessibility for list items.
 */
(function () {
    'use strict';

    // ─── Filter Tab Active State ─────────────────────────────────────────────────
    // After htmx swaps the list content via a filter tab click, the active tab
    // class doesn't update because the tabs live outside the swap target.
    // Listen for htmx:afterRequest on filter tabs and toggle the active class.

    function updateActiveTab(clickedTab) {
        var tabs = document.querySelectorAll('.inbox__filter-tab');
        for (var i = 0; i < tabs.length; i++) {
            tabs[i].classList.remove('inbox__filter-tab--active');
            tabs[i].removeAttribute('aria-current');
        }
        clickedTab.classList.add('inbox__filter-tab--active');
        clickedTab.setAttribute('aria-current', 'page');
    }

    // ─── List Item Read State ────────────────────────────────────────────────────
    // When a list item is clicked (triggers hx-post to mark as read and load detail),
    // immediately update its visual class from --unread to --read so the user gets
    // instant feedback without waiting for a list re-fetch.

    function markItemAsRead(item) {
        if (item.classList.contains('inbox__list-item--unread')) {
            item.classList.remove('inbox__list-item--unread');
            item.classList.add('inbox__list-item--read');
        }
    }

    // ─── Keyboard Accessibility ──────────────────────────────────────────────────
    // List items have tabindex="0" but need Enter/Space handlers to trigger the
    // same htmx request that a click would. htmx listens for click events, so
    // we simulate a click on keydown.

    function handleListItemKeydown(event) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            event.currentTarget.click();
        }
    }

    function bindKeyboardHandlers() {
        var items = document.querySelectorAll('.inbox__list-item');
        for (var i = 0; i < items.length; i++) {
            // Avoid double-binding by checking a data attribute
            if (!items[i].dataset.kbBound) {
                items[i].dataset.kbBound = '1';
                items[i].addEventListener('keydown', handleListItemKeydown);
            }
        }
    }

    // ─── Delete Animation ───────────────────────────────────────────────────────
    // Animate the list item sliding out to the left before htmx removes it.
    // We intercept the delete button click, add the removing class, then let
    // htmx proceed after the animation completes.

    document.addEventListener('htmx:confirm', function (event) {
        var trigger = event.detail.elt;
        if (!trigger.classList.contains('inbox__delete-btn')) {
            return;
        }

        var item = trigger.closest('.inbox__list-item');
        if (!item || item.classList.contains('inbox__list-item--removing')) {
            return;
        }

        // Prevent htmx from firing immediately
        event.preventDefault();

        // Add slide-out class
        item.classList.add('inbox__list-item--removing');

        // After animation completes, issue the htmx request
        setTimeout(function () {
            event.detail.issueRequest();
        }, 300);
    });

    // ─── Event Delegation & Lifecycle ────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', function () {
        // Initial keyboard binding for list items rendered server-side
        bindKeyboardHandlers();

        // Delegate click on list items for read-state update
        var listPanel = document.querySelector('.inbox__list');
        if (listPanel) {
            listPanel.addEventListener('click', function (event) {
                var item = event.target.closest('.inbox__list-item');
                if (item && !event.target.closest('.inbox__delete-btn')) {
                    markItemAsRead(item);
                }
            });
        }

        // Delegate click on filter tabs for active state update
        var filterNav = document.querySelector('.inbox__filters');
        if (filterNav) {
            filterNav.addEventListener('click', function (event) {
                var tab = event.target.closest('.inbox__filter-tab');
                if (tab) {
                    updateActiveTab(tab);
                }
            });
        }
    });

    // After htmx swaps new list content in, re-bind keyboard handlers on new items
    document.addEventListener('htmx:afterSwap', function (event) {
        var target = event.detail.target;
        if (!target) {
            return;
        }
        // If the swap target is the list panel (or contains list items), rebind
        if (target.classList.contains('inbox__list') || target.querySelector('.inbox__list-item')) {
            bindKeyboardHandlers();
        }
    });
})();
