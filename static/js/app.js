
(() => {

    /* MOBILE NAVIGATION */

    const toggle = document.getElementById('navToggle');
    const nav = document.getElementById('mainNav');

    if (toggle && nav) {
        toggle.addEventListener('click', () => {

            const open = nav.classList.toggle('open');

            toggle.setAttribute(
                'aria-expanded',
                String(open)
            );

        });
    }

    /* FLASH MESSAGE CLOSE */

    document.querySelectorAll('.flash-close').forEach(btn => {

        btn.addEventListener('click', () => {
            btn.closest('.flash')?.remove();
        });

    });

    /* BOUNDARY PREMIUM LOADING SCREEN */

    const loader = document.getElementById('boundary-loader');

    // Display loader only on the homepage.
    if (!loader) return;

    // Total visible animation: 4.2 seconds + 0.8-second fade.
    const LOADER_DURATION = 4200;
    const FADE_DURATION = 800;

    window.setTimeout(() => {

        loader.classList.add('is-hidden');

        window.setTimeout(() => {
            loader.remove();
        }, FADE_DURATION);

    }, LOADER_DURATION);

})();
