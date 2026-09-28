(() => {
    const storageKey = 'aafia-sidebar-collapsed';
    const body = document.body;
    const toggle = document.querySelector('.sidebar-toggle');
    if (!toggle) return;

    const isNarrowScreen = () => window.matchMedia('(max-width: 900px)').matches;
    const savedState = (() => {
        try {
            return localStorage.getItem(storageKey);
        } catch (_) {
            return null;
        }
    })();

    const setCollapsed = (collapsed, persist = false) => {
        body.classList.toggle('sidebar-collapsed', collapsed);
        body.classList.toggle('sidebar-expanded', !collapsed);
        toggle.setAttribute('aria-expanded', String(!collapsed));
        toggle.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
        toggle.setAttribute('title', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
        toggle.querySelector('span').textContent = collapsed ? '\u00bb' : '\u00ab';
        if (persist) {
            try {
                localStorage.setItem(storageKey, String(collapsed));
            } catch (_) {
                // The control remains usable when browser storage is disabled.
            }
        }
    };

    setCollapsed(savedState === null ? isNarrowScreen() : savedState === 'true');
    toggle.addEventListener('click', () => setCollapsed(!body.classList.contains('sidebar-collapsed'), true));
})();
