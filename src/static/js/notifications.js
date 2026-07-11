document.addEventListener('DOMContentLoaded', () => {
    const toasts = Array.from(document.querySelectorAll('[data-toast]'));

    toasts.forEach((toast) => {
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
    });
});