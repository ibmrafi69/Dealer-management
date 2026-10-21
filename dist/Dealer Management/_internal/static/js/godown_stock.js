(() => {
    const form = document.getElementById("bulk-stock-form");
    const rowsContainer = document.getElementById("bulk-stock-rows");
    const rowTemplate = document.getElementById("bulk-stock-row-template");
    const addRowButton = document.getElementById("add-stock-row");
    const saveButton = document.getElementById("save-all-stock");
    const sizesElement = document.getElementById("product-ctn-sizes");

    if (!form || !rowsContainer || !rowTemplate || !addRowButton || !saveButton || !sizesElement) {
        return;
    }

    const piecesPerCarton = JSON.parse(sizesElement.textContent);
    const prefix = rowsContainer.dataset.formPrefix;
    const totalForms = document.getElementById(`id_${prefix}-TOTAL_FORMS`);

    const rows = () => Array.from(rowsContainer.querySelectorAll(".bulk-stock-row"));

    const numberValue = (input) => {
        const value = Number.parseInt(input.value, 10);
        return Number.isFinite(value) && value >= 0 ? value : 0;
    };

    const updateRow = (row) => {
        const product = row.querySelector('[data-field="product"]');
        const cartons = row.querySelector('[data-field="received_ctn"]');
        const pieces = row.querySelector('[data-field="received_pcs"]');
        const total = row.querySelector("[data-total-pcs]");
        const rowError = row.querySelector("[data-row-error]");
        const cartonSize = Number(piecesPerCarton[product.value] || 0);
        const partialPieces = numberValue(pieces);
        const partialTooLarge = cartonSize > 0 && partialPieces >= cartonSize;

        pieces.max = cartonSize > 0 ? String(cartonSize - 1) : "";
        pieces.setCustomValidity(partialTooLarge ? "Partial pieces must be less than this product's Pieces per CTN value." : "");
        total.textContent = `${numberValue(cartons) * cartonSize + partialPieces} PCS`;
        rowError.textContent = partialTooLarge ? pieces.validationMessage : "";
        row.classList.toggle("row-invalid", partialTooLarge);
    };

    const updateRows = () => {
        const selectedProducts = new Map();
        rows().forEach((row) => {
            const product = row.querySelector('[data-field="product"]');
            product.setCustomValidity("");
            updateRow(row);
            if (product.value) {
                const matchingRows = selectedProducts.get(product.value) || [];
                matchingRows.push(row);
                selectedProducts.set(product.value, matchingRows);
            }
        });

        selectedProducts.forEach((matchingRows) => {
            if (matchingRows.length > 1) {
                matchingRows.forEach((row) => {
                    const product = row.querySelector('[data-field="product"]');
                    const rowError = row.querySelector("[data-row-error]");
                    product.setCustomValidity("This product is already included in another row.");
                    rowError.textContent = product.validationMessage;
                    row.classList.add("row-invalid");
                });
            }
        });

        rows().forEach((row) => {
            row.querySelector("[data-remove-row]").disabled = rows().length === 1;
        });
    };

    const reindexRows = () => {
        rows().forEach((row, index) => {
            row.querySelectorAll("[data-field]").forEach((field) => {
                field.name = `${prefix}-${index}-${field.dataset.field}`;
                field.id = `id_${prefix}-${index}-${field.dataset.field}`;
            });
        });
        totalForms.value = String(rows().length);
        updateRows();
    };

    addRowButton.addEventListener("click", () => {
        rowsContainer.append(rowTemplate.content.cloneNode(true));
        reindexRows();
        const currentRows = rows();
        currentRows[currentRows.length - 1].querySelector('[data-field="product"]').focus();
    });

    rowsContainer.addEventListener("click", (event) => {
        const button = event.target.closest("[data-remove-row]");
        if (button && !button.disabled) {
            button.closest(".bulk-stock-row").remove();
            reindexRows();
        }
    });

    rowsContainer.addEventListener("input", updateRows);
    rowsContainer.addEventListener("change", updateRows);
    form.addEventListener("submit", () => {
        updateRows();
        if (form.checkValidity()) {
            saveButton.disabled = true;
            saveButton.textContent = "Saving...";
        }
    });

    updateRows();
})();
