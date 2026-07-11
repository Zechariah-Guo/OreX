/**
 * OreX Expandable Cards — click handler for ore cards on the market page.
 * Toggles the expanded class to reveal additional details.
 */
(function () {
    'use strict';

    const cards = document.querySelectorAll('.ore-card--expandable');

    cards.forEach(function (card) {
        const toggle = card.querySelector('.ore-card__toggle');
        if (!toggle) return;

        toggle.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            card.classList.toggle('ore-card--expanded');
        });
    });
})();
