(() => {
    const isEditableZeroNumberInput = (element) => (
        element instanceof HTMLInputElement
        && element.type === "number"
        && !element.disabled
        && !element.readOnly
        && element.value !== ""
        && element.valueAsNumber === 0
    );

    const selectZeroValue = (event) => {
        const input = event.target;
        if (isEditableZeroNumberInput(input)) {
            input.select();
        }
    };

    // Event delegation also covers numeric inputs added dynamically to Daily Sales.
    document.addEventListener("focusin", selectZeroValue);
    document.addEventListener("click", selectZeroValue);
})();
