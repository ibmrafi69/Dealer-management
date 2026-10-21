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


// Dirty form protection for navigation, Change Group, and Logout
(() => {
    let isFormDirty = false;

    // Track modifications to POST forms (e.g. data entry, edits)
    const isTrackedInput = (target) => {
        if (!target || !target.form) return false;
        const form = target.form;
        if (form.method.toUpperCase() !== 'POST') return false;
        if (form.classList.contains('sidebar-logout-form')) return false;
        if (form.classList.contains('sidebar-delete-group-form')) return false;
        return true;
    };

    document.addEventListener('input', (e) => {
        if (isTrackedInput(e.target)) {
            isFormDirty = true;
        }
    });

    document.addEventListener('change', (e) => {
        if (isTrackedInput(e.target)) {
            isFormDirty = true;
        }
    });

    // Submitting a valid content form clears dirty flag
    document.addEventListener('submit', (e) => {
        const form = e.target;
        if (!form.classList.contains('sidebar-logout-form') && !form.classList.contains('sidebar-delete-group-form')) {
            isFormDirty = false;
        }
    });

    // Prompt user if dirty
    const confirmLeave = (actionDesc) => {
        return window.confirm(`You have unsaved changes. Are you sure you want to ${actionDesc}? Your unsaved data will be lost.`);
    };

    // Logout form
    const logoutForm = document.querySelector('.sidebar-logout-form');
    if (logoutForm) {
        logoutForm.addEventListener('submit', (e) => {
            if (isFormDirty) {
                if (!confirmLeave('log out and exit group')) {
                    e.preventDefault();
                }
            }
        });
    }

    // Change Group link
    document.querySelectorAll('.change-group-link, a[href*="groups"]').forEach((link) => {
        link.addEventListener('click', (e) => {
            if (isFormDirty) {
                if (!confirmLeave('leave this page and change group')) {
                    e.preventDefault();
                }
            }
        });
    });

    // Navigation links
    document.querySelectorAll('.side-nav a, .back-home, .app-brand').forEach((link) => {
        link.addEventListener('click', (e) => {
            if (isFormDirty) {
                if (!confirmLeave('navigate away')) {
                    e.preventDefault();
                }
            }
        });
    });

    // Browser navigation / close tab
    window.addEventListener('beforeunload', (e) => {
        if (isFormDirty) {
            e.preventDefault();
            e.returnValue = '';
        }
    });
})();
