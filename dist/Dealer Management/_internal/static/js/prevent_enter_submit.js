(() => {
    const pendingEnterForms = new Set();
    const formControlSelector = "input, select, textarea, button, [contenteditable='true'], [role='combobox']";
    const nativeFormSubmit = HTMLFormElement.prototype.submit;

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" || event.isComposing) {
            return;
        }

        const target = event.target;
        if (!(target instanceof Element) || !target.matches(formControlSelector)) {
            return;
        }

        const form = target.closest("form");
        if (!form) {
            return;
        }

        // Do not cancel the key itself: textarea newlines and native select
        // interactions continue to work. Only a submit caused by this Enter is blocked.
        pendingEnterForms.add(form);
        window.setTimeout(() => pendingEnterForms.delete(form), 0);
    }, true);

    document.addEventListener("submit", (event) => {
        if (pendingEnterForms.has(event.target)) {
            event.preventDefault();
            event.stopImmediatePropagation();
        }
    }, true);

    // Most submits dispatch the event above. This also covers the shared
    // group selector, whose onchange handler uses form.submit() directly.
    HTMLFormElement.prototype.submit = function submitWithoutEnterShortcut() {
        if (!pendingEnterForms.has(this)) {
            nativeFormSubmit.call(this);
        }
    };
})();
