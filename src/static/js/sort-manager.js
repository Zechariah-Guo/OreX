/**
 * Sort Manager — Core sort logic for the market page ore card grid.
 *
 * This module provides:
 * - localStorage read/write with validation for sort mode and custom order
 * - DOM reordering of .ore-card elements within #ore-price-grid
 * - Trend-based comparison for Rising/Falling sort modes
 *
 * Requirements: 2.1, 3.1, 4.1, 6.1, 6.2, 6.3
 */
(function () {
    'use strict';

    // ─── Constants ───────────────────────────────────────────────────────────────
    var STORAGE_KEY_SORT = 'orex-sort-mode';
    var STORAGE_KEY_ORDER = 'orex-custom-order';
    var VALID_SORT_MODES = ['default', 'rising', 'falling', 'custom'];

    // Store the original server-rendered card order for "default" restore
    var defaultOrder = [];

    // ─── localStorage helpers ────────────────────────────────────────────────────

    /**
     * Check whether localStorage is available.
     * @returns {boolean}
     */
    function storageAvailable() {
        try {
            var test = '__storage_test__';
            localStorage.setItem(test, test);
            localStorage.removeItem(test);
            return true;
        } catch (e) {
            return false;
        }
    }

    /**
     * Read the saved sort mode from localStorage.
     * Returns 'default' if localStorage is unavailable or value is invalid.
     * If the stored value is corrupted, resets it to 'default'.
     * @returns {'default'|'rising'|'falling'|'custom'}
     */
    function getSortMode() {
        if (!storageAvailable()) {
            console.warn('SortManager: localStorage unavailable, falling back to default sort.');
            return 'default';
        }
        try {
            var stored = localStorage.getItem(STORAGE_KEY_SORT);
            if (stored && VALID_SORT_MODES.indexOf(stored) !== -1) {
                return stored;
            }
            // Corrupted or missing — reset to 'default'
            localStorage.setItem(STORAGE_KEY_SORT, 'default');
        } catch (e) {
            console.warn('SortManager: Error reading sort mode from localStorage.', e);
        }
        return 'default';
    }

    /**
     * Save the sort mode to localStorage and re-sort the cards.
     * Invalid modes are normalised to 'default'.
     * Dispatches a 'sortmodechange' event so the dropdown UI can update.
     * @param {string} mode - One of 'default', 'rising', 'falling', 'custom'
     */
    function setSortMode(mode) {
        if (VALID_SORT_MODES.indexOf(mode) === -1) {
            mode = 'default';
        }
        try {
            if (storageAvailable()) {
                localStorage.setItem(STORAGE_KEY_SORT, mode);
            }
        } catch (e) {
            console.warn('SortManager: Error writing sort mode to localStorage.', e);
        }
        sortCards(mode);
        // Notify UI (dropdown label/indicator) of the mode change
        try {
            document.dispatchEvent(new CustomEvent('sortmodechange', { detail: { mode: mode } }));
        } catch (e) {
            // CustomEvent not supported in very old browsers — ignore
        }
    }

    /**
     * Read the custom card order from localStorage.
     * Returns an empty array if unavailable, corrupted, or not a valid array of integers.
     * If the stored value is corrupted, resets it to [].
     * @returns {number[]}
     */
    function getCustomOrder() {
        if (!storageAvailable()) {
            return [];
        }
        try {
            var raw = localStorage.getItem(STORAGE_KEY_ORDER);
            if (!raw) {
                return [];
            }
            var parsed = JSON.parse(raw);
            // Validate: must be an array of integers
            if (Array.isArray(parsed) && parsed.every(function (item) {
                return typeof item === 'number' && Number.isInteger(item);
            })) {
                return parsed;
            }
            // Corrupted — reset
            localStorage.setItem(STORAGE_KEY_ORDER, JSON.stringify([]));
        } catch (e) {
            // Invalid JSON or storage error — reset
            try {
                if (storageAvailable()) {
                    localStorage.setItem(STORAGE_KEY_ORDER, JSON.stringify([]));
                }
            } catch (writeErr) {
                // Cannot write either — ignore
            }
            console.warn('SortManager: Error reading custom order from localStorage.', e);
        }
        return [];
    }

    /**
     * Save the custom card order to localStorage.
     * Validates that ids is an array of integers before writing.
     * @param {number[]} ids - Array of ore ID integers
     */
    function setCustomOrder(ids) {
        // Validate input
        if (!Array.isArray(ids) || !ids.every(function (item) {
            return typeof item === 'number' && Number.isInteger(item);
        })) {
            ids = [];
        }
        try {
            if (storageAvailable()) {
                localStorage.setItem(STORAGE_KEY_ORDER, JSON.stringify(ids));
            }
        } catch (e) {
            console.warn('SortManager: Error writing custom order to localStorage.', e);
        }
    }

    // ─── Sort logic ──────────────────────────────────────────────────────────────

    /**
     * Extract the trend class from an ore card element.
     * Looks for .ore-card__trend--rise, .ore-card__trend--fall, or .ore-card__trend--hold
     * on the .ore-card__trend child element.
     * @param {Element} card - An .ore-card element
     * @returns {'rise'|'fall'|'hold'}
     */
    function getTrend(card) {
        var trendEl = card.querySelector('.ore-card__trend');
        if (!trendEl) return 'hold';
        if (trendEl.classList.contains('ore-card__trend--rise')) return 'rise';
        if (trendEl.classList.contains('ore-card__trend--fall')) return 'fall';
        return 'hold';
    }

    /**
     * Extract the ore ID from a card element's id attribute.
     * Expects format: "ore-card-{number}"
     * @param {Element} card - An .ore-card element
     * @returns {number|NaN}
     */
    function getCardId(card) {
        var id = card.id || '';
        var match = id.match(/^ore-card-(\d+)$/);
        return match ? parseInt(match[1], 10) : NaN;
    }

    /**
     * Compare two ore card elements by trend for sorting.
     *
     * Priority mapping:
     *   Rising direction:  rise=0, hold=1, fall=2
     *   Falling direction: fall=0, hold=1, rise=2
     *
     * @param {Element} a - First ore card element
     * @param {Element} b - Second ore card element
     * @param {'rising'|'falling'} direction - Sort direction
     * @returns {number} Negative if a before b, positive if b before a, 0 if equal
     */
    function compareTrend(a, b, direction) {
        var priorityMap;
        if (direction === 'rising') {
            priorityMap = { rise: 0, hold: 1, fall: 2 };
        } else {
            priorityMap = { fall: 0, hold: 1, rise: 2 };
        }

        var trendA = getTrend(a);
        var trendB = getTrend(b);

        var priorityA = priorityMap[trendA] !== undefined ? priorityMap[trendA] : 1;
        var priorityB = priorityMap[trendB] !== undefined ? priorityMap[trendB] : 1;

        return priorityA - priorityB;
    }

    /**
     * Reorder .ore-card elements within #ore-price-grid based on the given sort mode.
     *
     * Modes:
     *   'default'  — restore the original server-rendered card order
     *   'rising'   — sort by trend: rise first, hold second, fall last
     *   'falling'  — sort by trend: fall first, hold second, rise last
     *   'custom'   — order per stored custom order; unknowns appended at end
     *
     * @param {string} mode - One of 'default', 'rising', 'falling', 'custom'
     */
    function sortCards(mode) {
        var grid = document.getElementById('ore-price-grid');
        if (!grid) return;

        var cards = grid.querySelectorAll('.ore-card');
        if (!cards.length) return;

        var cardsArray = Array.prototype.slice.call(cards);

        if (mode === 'default') {
            // Restore the server-rendered order
            if (defaultOrder.length) {
                var orderMap = {};
                for (var i = 0; i < defaultOrder.length; i++) {
                    orderMap[defaultOrder[i]] = i;
                }
                cardsArray.sort(function (a, b) {
                    var idA = getCardId(a);
                    var idB = getCardId(b);
                    var posA = orderMap[idA] !== undefined ? orderMap[idA] : 9999;
                    var posB = orderMap[idB] !== undefined ? orderMap[idB] : 9999;
                    return posA - posB;
                });
            } else {
                // No stored default order — leave as-is (first load)
                return;
            }
        } else if (mode === 'rising' || mode === 'falling') {
            cardsArray.sort(function (a, b) {
                return compareTrend(a, b, mode);
            });
        } else if (mode === 'custom') {
            var customOrder = getCustomOrder();
            if (!customOrder.length) {
                // No custom order saved — leave as server order
                return;
            }

            // Build a map: oreId → position in custom order
            var customMap = {};
            for (var ci = 0; ci < customOrder.length; ci++) {
                customMap[customOrder[ci]] = ci;
            }

            // Separate cards into known (in custom order) and unknown
            var knownCards = [];
            var unknownCards = [];
            for (var j = 0; j < cardsArray.length; j++) {
                var cardId = getCardId(cardsArray[j]);
                if (!isNaN(cardId) && customMap[cardId] !== undefined) {
                    knownCards.push(cardsArray[j]);
                } else {
                    unknownCards.push(cardsArray[j]);
                }
            }

            // Sort known cards by their position in custom order
            knownCards.sort(function (a, b) {
                return customMap[getCardId(a)] - customMap[getCardId(b)];
            });

            // Combine: known cards first (in custom order), unknowns at end (server order)
            cardsArray = knownCards.concat(unknownCards);
        }

        // Re-append cards in sorted order (moves existing DOM nodes)
        for (var k = 0; k < cardsArray.length; k++) {
            grid.appendChild(cardsArray[k]);
        }
    }

    // ─── HTMX afterSwap re-sort wiring ─────────────────────────────────────────
    // Re-apply the current sort mode after HTMX refreshes #ore-price-grid.
    // Uses document.body event delegation so it works regardless of script load order.
    // Requirements: 2.2, 3.2, 4.2, 5.4
    document.body.addEventListener('htmx:afterSwap', function (event) {
        if (!event.detail || !event.detail.target) return;
        if (event.detail.target.id !== 'ore-price-grid') return;

        var grid = event.detail.target;
        var cards = grid.querySelectorAll('.ore-card');

        // Skip sort when grid container is empty (server error case)
        if (!cards.length) return;

        // Capture the fresh server order as the new default
        defaultOrder = [];
        for (var i = 0; i < cards.length; i++) {
            var id = getCardId(cards[i]);
            if (!isNaN(id)) {
                defaultOrder.push(id);
            }
        }

        // Re-apply the active sort mode
        sortCards(getSortMode());

        // Re-initialize drag-and-drop on new cards
        initDragAndDrop();
    });

    // ─── Drag-and-Drop ──────────────────────────────────────────────────────────
    // Requirements: 5.1, 5.2, 5.3

    var draggedCard = null;
    var draggedCardId = null;

    /**
     * Handle the start of a drag operation.
     * Stores a reference to the dragged card and sets the drag data.
     * @param {DragEvent} e
     */
    function handleDragStart(e) {
        draggedCard = e.currentTarget;
        draggedCardId = getCardId(draggedCard);
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', String(draggedCardId));
        draggedCard.classList.add('ore-card--dragging');
    }

    /**
     * Handle dragover events to allow dropping.
     * Determines the drop position based on pointer location relative to the target card.
     * @param {DragEvent} e
     */
    function handleDragOver(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';

        var targetCard = e.currentTarget;
        if (targetCard === draggedCard) return;

        // Add visual indicator for drop target
        var grid = document.getElementById('ore-price-grid');
        if (!grid) return;

        // Remove previous drop indicators
        var allCards = grid.querySelectorAll('.ore-card');
        for (var i = 0; i < allCards.length; i++) {
            allCards[i].classList.remove('ore-card--drag-over');
        }
        targetCard.classList.add('ore-card--drag-over');
    }

    /**
     * Handle the drop event — performs insertion reorder.
     * Removes the dragged card from its original position and inserts it at the
     * target position. Other cards shift to fill the gap.
     * After drop: saves new order to localStorage and switches to 'custom' mode.
     * @param {DragEvent} e
     */
    function handleDrop(e) {
        e.preventDefault();

        var targetCard = e.currentTarget;
        if (!draggedCard || targetCard === draggedCard) return;

        var grid = document.getElementById('ore-price-grid');
        if (!grid) return;

        // Perform insertion reorder:
        // Determine whether to insert before or after the target based on position
        var cards = Array.prototype.slice.call(grid.querySelectorAll('.ore-card'));
        var draggedIndex = cards.indexOf(draggedCard);
        var targetIndex = cards.indexOf(targetCard);

        // Remove dragged card from DOM
        grid.removeChild(draggedCard);

        // Re-query cards after removal to get updated positions
        var updatedCards = Array.prototype.slice.call(grid.querySelectorAll('.ore-card'));
        var newTargetIndex = updatedCards.indexOf(targetCard);

        // Insert at target position
        if (draggedIndex < targetIndex) {
            // Dragging forward: insert after the target
            if (targetCard.nextSibling) {
                grid.insertBefore(draggedCard, targetCard.nextSibling);
            } else {
                grid.appendChild(draggedCard);
            }
        } else {
            // Dragging backward: insert before the target
            grid.insertBefore(draggedCard, targetCard);
        }

        // Read the new order from the DOM and save it
        var finalCards = grid.querySelectorAll('.ore-card');
        var newOrder = [];
        for (var i = 0; i < finalCards.length; i++) {
            var id = getCardId(finalCards[i]);
            if (!isNaN(id)) {
                newOrder.push(id);
            }
        }

        // Save order and switch to custom mode
        setCustomOrder(newOrder);
        setSortMode('custom');

        // Clean up visual states
        handleDragEnd(e);
    }

    /**
     * Handle the end of a drag operation — clean up visual states.
     * @param {DragEvent} e
     */
    function handleDragEnd(e) {
        if (draggedCard) {
            draggedCard.classList.remove('ore-card--dragging');
        }

        // Remove all drag-over indicators
        var grid = document.getElementById('ore-price-grid');
        if (grid) {
            var allCards = grid.querySelectorAll('.ore-card');
            for (var i = 0; i < allCards.length; i++) {
                allCards[i].classList.remove('ore-card--drag-over');
            }
        }

        draggedCard = null;
        draggedCardId = null;
    }

    /**
     * Initialise drag-and-drop on all .ore-card elements.
     * Sets draggable attribute, touch-action style, and attaches event listeners.
     * Can be re-called after HTMX swaps to re-attach to new DOM elements.
     */
    function initDragAndDrop() {
        var grid = document.getElementById('ore-price-grid');
        if (!grid) return;

        var cards = grid.querySelectorAll('.ore-card');
        for (var i = 0; i < cards.length; i++) {
            var card = cards[i];

            // Set draggable attribute and touch-action for mobile
            card.setAttribute('draggable', 'true');
            card.style.touchAction = 'none';

            // Remove existing listeners to prevent duplicates (safe for re-init)
            card.removeEventListener('dragstart', handleDragStart);
            card.removeEventListener('dragover', handleDragOver);
            card.removeEventListener('drop', handleDrop);
            card.removeEventListener('dragend', handleDragEnd);

            // Attach drag event listeners
            card.addEventListener('dragstart', handleDragStart);
            card.addEventListener('dragover', handleDragOver);
            card.addEventListener('drop', handleDrop);
            card.addEventListener('dragend', handleDragEnd);
        }
    }

    // Initialise drag-and-drop on DOMContentLoaded
    document.addEventListener('DOMContentLoaded', function () {
        // Capture the initial server-rendered order as the default
        var grid = document.getElementById('ore-price-grid');
        if (grid) {
            var cards = grid.querySelectorAll('.ore-card');
            for (var i = 0; i < cards.length; i++) {
                var id = getCardId(cards[i]);
                if (!isNaN(id)) {
                    defaultOrder.push(id);
                }
            }
        }
        initDragAndDrop();
    });

    // ─── Dropdown interaction ─────────────────────────────────────────────────────

    /**
     * Set up sort control dropdown behaviour on DOMContentLoaded.
     * - Reads saved sort mode and applies it
     * - Toggles dropdown visibility on button click
     * - Handles option selection
     * - Closes dropdown on outside click
     *
     * Requirements: 1.2, 1.3, 6.3
     */
    document.addEventListener('DOMContentLoaded', function () {
        var sortControl = document.getElementById('sort-control');
        if (!sortControl) return;

        var btn = sortControl.querySelector('.sort-control__btn');
        var menu = sortControl.querySelector('.sort-control__menu');
        var options = menu.querySelectorAll('li[role="option"]');

        if (!btn || !menu || !options.length) return;

        // ── Helper: update active indicator on menu items ──
        function setActiveIndicator(mode) {
            for (var i = 0; i < options.length; i++) {
                var option = options[i];
                if (option.getAttribute('data-sort') === mode) {
                    option.setAttribute('aria-selected', 'true');
                    option.classList.add('active');
                } else {
                    option.removeAttribute('aria-selected');
                    option.classList.remove('active');
                }
            }
            // Update the button label text to show current mode
            var label = document.getElementById('sort-control-label');
            if (label) {
                var modeLabels = {
                    'default': 'Default',
                    'rising': 'Rising ↑',
                    'falling': 'Falling ↓',
                    'custom': 'Custom'
                };
                label.textContent = modeLabels[mode] || 'Default';
            }
        }

        // ── Helper: open/close dropdown ──
        function openDropdown() {
            menu.classList.add('sort-control__menu--open');
            btn.setAttribute('aria-expanded', 'true');
        }

        function closeDropdown() {
            menu.classList.remove('sort-control__menu--open');
            btn.setAttribute('aria-expanded', 'false');
        }

        function toggleDropdown() {
            var isOpen = menu.classList.contains('sort-control__menu--open');
            if (isOpen) {
                closeDropdown();
            } else {
                openDropdown();
            }
        }

        // ── Initialise: read saved sort mode and apply ──
        var savedMode = getSortMode();
        sortCards(savedMode);
        setActiveIndicator(savedMode);

        // ── Button click: toggle dropdown ──
        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            toggleDropdown();
        });

        // ── Option click: select sort mode ──
        for (var i = 0; i < options.length; i++) {
            options[i].addEventListener('click', function (e) {
                var mode = this.getAttribute('data-sort');
                setSortMode(mode);
                setActiveIndicator(mode);
                closeDropdown();
            });
        }

        // ── Click outside: close dropdown ──
        document.addEventListener('click', function (e) {
            if (!sortControl.contains(e.target)) {
                closeDropdown();
            }
        });

        // ── Listen for programmatic sort mode changes (e.g. from drag-and-drop) ──
        document.addEventListener('sortmodechange', function (e) {
            if (e.detail && e.detail.mode) {
                setActiveIndicator(e.detail.mode);
            }
        });
    });

    // ─── Expose internal functions for other parts of sort-manager ────────────────
    // These are attached to window so that drag-and-drop handlers (task 3.3),
    // HTMX wiring (task 3.4), and dropdown interaction (task 3.5) can access them.
    window.SortManager = {
        getSortMode: getSortMode,
        setSortMode: setSortMode,
        getCustomOrder: getCustomOrder,
        setCustomOrder: setCustomOrder,
        sortCards: sortCards,
        compareTrend: compareTrend,
        initDragAndDrop: initDragAndDrop
    };

})();
