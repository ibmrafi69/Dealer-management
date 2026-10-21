(() => {
    const salesForm = document.querySelector("#sales-form");
    if (!salesForm) {
        return;
    }

    salesForm.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" || event.isComposing) {
            return;
        }

        const target = event.target;
        if (
            !(target instanceof HTMLInputElement) ||
            ["hidden", "submit", "button", "reset"].includes(target.type)
        ) {
            return;
        }

        // Only data-entry inputs in the Daily Sales form are protected.
        // Submit buttons and every other form retain their native behaviour.
        event.preventDefault();
    });
})();
