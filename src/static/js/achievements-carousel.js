/* Profile achievements carousel (compact layout only; CSS hides it from 880px up).
 * Coverflow stack: the centred badge is largest, neighbours shrink and tuck
 * behind it. Drag/swipe, arrow buttons, Left/Right keys (when the carousel has
 * focus) and tapping a neighbour all move it. It never rotates on its own. */
(function () {
    'use strict';

    var DRAG_START_PX = 8;      // movement before a drag is captured
    var FLICK_PX = 24;          // a shorter drag than half a step still advances one badge past this
    var STEP_UNITS = 0.66;      // distance between centre and first neighbour, in badge widths

    function wrap(value, count) {
        return ((value % count) + count) % count;
    }

    // Offset (in badge widths), scale, opacity for a signed distance from the centre
    function layout(delta) {
        var t = Math.abs(delta);
        var sign = delta < 0 ? -1 : 1;
        var x;
        if (t <= 1) x = STEP_UNITS * t;
        else if (t <= 2) x = STEP_UNITS + 0.4 * (t - 1);
        else x = STEP_UNITS + 0.4 + 0.2 * (t - 2);
        return {
            x: sign * x,
            s: Math.max(0.3, 1 - 0.28 * t),
            o: t <= 2 ? 1 : Math.max(0, 3 - t),
            z: Math.round(100 - t * 10)
        };
    }

    function init(root) {
        var stage = root.querySelector('[data-ach-stage]');
        var slides = Array.prototype.slice.call(stage.querySelectorAll('.ach-carousel__slide'));
        var count = slides.length;
        if (!count) return;

        var titleEl = root.querySelector('[data-ach-title]');
        var descEl = root.querySelector('[data-ach-desc]');
        var stateEl = root.querySelector('[data-ach-state]');
        var posEl = root.querySelector('[data-ach-pos]');
        var liveEl = root.querySelector('[data-ach-live]');
        var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

        var start = parseInt(root.getAttribute('data-start'), 10);
        var index = isNaN(start) ? 0 : wrap(start, count);   // unwrapped target index
        var pos = index;                                     // float position while dragging
        var announced = false;

        function render() {
            slides.forEach(function (slide, i) {
                var delta = i - pos;
                delta = delta - count * Math.round(delta / count);   // shortest way round
                var l = layout(delta);
                slide.style.setProperty('--x', l.x.toFixed(3));
                slide.style.setProperty('--s', l.s.toFixed(3));
                slide.style.setProperty('--o', l.o.toFixed(3));
                slide.style.setProperty('--z', l.z);
                slide.style.pointerEvents = l.o > 0.5 ? '' : 'none';
            });
        }

        function showDetails() {
            var current = slides[wrap(index, count)];
            var name = current.getAttribute('data-name');
            var desc = current.getAttribute('data-desc');
            var earned = current.getAttribute('data-earned') === '1';
            var when = current.getAttribute('data-earned-at');
            var state = earned ? (when ? 'Earned ' + when : 'Earned') : 'Locked';
            titleEl.textContent = name;
            descEl.textContent = desc;
            stateEl.textContent = state;
            stateEl.classList.toggle('ach-carousel__state--locked', !earned);
            var label = (wrap(index, count) + 1) + ' / ' + count;
            posEl.textContent = label;
            if (announced) {
                liveEl.textContent = name + '. ' + state + '. ' + desc + '. Achievement ' +
                    (wrap(index, count) + 1) + ' of ' + count;
            }
        }

        function goTo(target) {
            index = target;
            pos = target;
            stage.classList.toggle('ach-carousel__stage--static', reduceMotion.matches);
            render();
            showDetails();
        }

        function step(direction) {
            announced = true;
            goTo(index + direction);
        }

        // Initial state: no transition on first paint
        stage.classList.add('ach-carousel__stage--static');
        render();
        showDetails();
        announced = true;
        requestAnimationFrame(function () {
            requestAnimationFrame(function () {
                stage.classList.toggle('ach-carousel__stage--static', reduceMotion.matches);
            });
        });

        root.querySelector('[data-ach-prev]').addEventListener('click', function () { step(-1); });
        root.querySelector('[data-ach-next]').addEventListener('click', function () { step(1); });

        // Keys only act while the carousel itself has focus
        stage.addEventListener('keydown', function (event) {
            if (event.target !== stage || event.altKey || event.ctrlKey || event.metaKey) return;
            if (event.key === 'ArrowLeft') { event.preventDefault(); step(-1); }
            else if (event.key === 'ArrowRight') { event.preventDefault(); step(1); }
        });

        // Pointer drag: horizontal movement only; vertical pans stay with the browser
        var pointerId = null;
        var startX = 0, startY = 0, startPos = 0, stepPx = 100;
        var dragging = false;
        var justDragged = false;

        function pointerButton(event) {
            return event.target.closest && event.target.closest('.ach-carousel__btn');
        }

        stage.addEventListener('pointerdown', function (event) {
            if (pointerId !== null || pointerButton(event)) return;
            if (event.pointerType === 'mouse' && event.button !== 0) return;
            pointerId = event.pointerId;
            startX = event.clientX;
            startY = event.clientY;
            startPos = index;
            dragging = false;
            stepPx = Math.max(40, slides[0].offsetWidth * STEP_UNITS);
        });

        stage.addEventListener('pointermove', function (event) {
            if (event.pointerId !== pointerId) return;
            var dx = event.clientX - startX;
            var dy = event.clientY - startY;
            if (!dragging) {
                if (Math.abs(dx) < DRAG_START_PX || Math.abs(dx) < Math.abs(dy)) return;
                dragging = true;
                try { stage.setPointerCapture(pointerId); } catch (e) { /* pointer already gone */ }
                stage.classList.add('ach-carousel__stage--dragging');
            }
            pos = startPos - dx / stepPx;
            render();
        });

        function endDrag(event, cancelled) {
            if (event.pointerId !== pointerId) return;
            var dx = event.clientX - startX;
            var wasDragging = dragging;
            pointerId = null;
            dragging = false;
            stage.classList.remove('ach-carousel__stage--dragging');
            if (!wasDragging) return;
            justDragged = true;
            setTimeout(function () { justDragged = false; }, 0);
            var target = startPos;
            if (!cancelled) {
                var moved = -dx / stepPx;
                target = startPos + Math.round(moved);
                if (target === startPos && Math.abs(dx) >= FLICK_PX) target += moved > 0 ? 1 : -1;
            }
            if (target !== startPos) announced = true;
            goTo(target);
        }

        stage.addEventListener('pointerup', function (event) { endDrag(event, false); });
        stage.addEventListener('pointercancel', function (event) { endDrag(event, true); });

        // Tap a visible neighbour to bring it to the centre
        stage.addEventListener('click', function (event) {
            if (justDragged || pointerButton(event)) return;
            var slide = event.target.closest('.ach-carousel__slide');
            if (!slide) return;
            var i = slides.indexOf(slide);
            var delta = i - wrap(index, count);
            delta = delta - count * Math.round(delta / count);
            if (delta !== 0) step(delta);
        });

        reduceMotion.addEventListener('change', function () {
            stage.classList.toggle('ach-carousel__stage--static', reduceMotion.matches);
        });
    }

    function boot() {
        var root = document.querySelector('.ach-carousel');
        if (root) init(root);
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
    else boot();
})();
