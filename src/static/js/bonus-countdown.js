/**
 * Live countdown for the daily bonus card.
 *
 * Elements with data-bonus-countdown="<seconds>" are filled with HH:MM:SS.
 * The server supplies seconds remaining (so the player's clock/timezone never
 * matters); we count down with performance.now() and reload at zero so the
 * card flips to its collectable state.
 */
(function () {
    'use strict';

    function pad(n) {
        return n < 10 ? '0' + n : String(n);
    }

    function format(totalSeconds) {
        var h = Math.floor(totalSeconds / 3600);
        var m = Math.floor((totalSeconds % 3600) / 60);
        var s = totalSeconds % 60;
        return pad(h) + ':' + pad(m) + ':' + pad(s);
    }

    function start(el) {
        if (el.dataset.countdownStarted) {
            return;
        }
        var seconds = parseInt(el.dataset.bonusCountdown, 10);
        if (isNaN(seconds)) {
            return;
        }
        el.dataset.countdownStarted = '1';

        var endsAt = performance.now() + seconds * 1000;
        var timer = null;

        function tick() {
            // Element was swapped out by htmx — stop quietly.
            if (!document.body.contains(el)) {
                clearInterval(timer);
                return;
            }
            var left = Math.ceil((endsAt - performance.now()) / 1000);
            if (left <= 0) {
                clearInterval(timer);
                window.location.reload();
                return;
            }
            el.textContent = format(left);
        }

        timer = setInterval(tick, 1000);
        tick();
    }

    function init() {
        document.querySelectorAll('[data-bonus-countdown]').forEach(start);
    }

    document.addEventListener('DOMContentLoaded', init);
    document.addEventListener('htmx:afterSwap', init);
})();
