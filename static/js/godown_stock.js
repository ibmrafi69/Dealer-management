(() => {
    const form = document.getElementById("bulk-stock-form");
    const rowsContainer = document.getElementById("bulk-stock-rows");
    const rowTemplate = document.getElementById("bulk-stock-row-template");
    const addRowButton = document.getElementById("add-stock-row");
    const saveButton = document.getElementById("save-all-stock");
    const sizesElement = document.getElementById("product-ctn-sizes");
    const alertBox = document.getElementById("bulk-stock-alert");
    const referenceInput = document.getElementById("id_reference");
    const dateInput = document.getElementById("id_received_at");

    if (!form || !rowsContainer || !rowTemplate || !addRowButton || !saveButton || !sizesElement) {
        return;
    }

    const piecesPerCarton = JSON.parse(sizesElement.textContent);
    const prefix = rowsContainer.dataset.formPrefix;
    const totalForms = document.getElementById(`id_${prefix}-TOTAL_FORMS`);

    const rows = () => Array.from(rowsContainer.querySelectorAll(".bulk-stock-row"));

    const showAlert = (message) => {
        if (alertBox) {
            alertBox.textContent = message;
            alertBox.style.display = "";
            alertBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
    };

    const hideAlert = () => {
        if (alertBox) {
            alertBox.textContent = "";
            alertBox.style.display = "none";
        }
    };

    const numberValue = (input) => {
        if (!input) return 0;
        const value = Number.parseInt(input.value, 10);
        return Number.isFinite(value) && value >= 0 ? value : 0;
    };

    // Helper: checks whether a row has any user input or product selection
    const isRowEmpty = (row) => {
        const product = row.querySelector('[data-field="product"]');
        const cartons = row.querySelector('[data-field="received_ctn"]');
        const pieces = row.querySelector('[data-field="received_pcs"]');
        const hasProduct = Boolean(product && product.value);
        const ctnStr = cartons ? cartons.value.trim() : "";
        const pcsStr = pieces ? pieces.value.trim() : "";
        const ctnNum = numberValue(cartons);
        const pcsNum = numberValue(pieces);
        const hasQty = (ctnStr !== "" && ctnStr !== "0") || (pcsStr !== "" && pcsStr !== "0") || ctnNum > 0 || pcsNum > 0;
        return !hasProduct && !hasQty;
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
        pieces.setCustomValidity(partialTooLarge ? `Partial pieces must be less than this product's Pieces per CTN value (${cartonSize}).` : "");
        total.textContent = `${numberValue(cartons) * cartonSize + partialPieces} PCS`;

        if (isRowEmpty(row)) {
            row.classList.remove("row-invalid");
            if (rowError) rowError.textContent = "";
            return;
        }

        if (partialTooLarge) {
            if (rowError) rowError.textContent = pieces.validationMessage;
            row.classList.add("row-invalid");
        } else if (!row.classList.contains("duplicate-error")) {
            if (rowError && !row.dataset.hasSaveError) {
                rowError.textContent = "";
                row.classList.remove("row-invalid");
            }
        }
    };

    const updateRows = () => {
        const selectedProducts = new Map();
        rows().forEach((row) => {
            const product = row.querySelector('[data-field="product"]');
            product.setCustomValidity("");
            row.classList.remove("duplicate-error");
            delete row.dataset.hasSaveError;
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
                    if (rowError) rowError.textContent = product.validationMessage;
                    row.classList.add("row-invalid", "duplicate-error");
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

    const validateOnSave = () => {
        hideAlert();
        updateRows();

        // Validate top-level challan / reference and date
        if (referenceInput && !referenceInput.value.trim()) {
            showAlert("Please enter a challan or reference number.");
            referenceInput.focus();
            return false;
        }
        if (dateInput && !dateInput.value.trim()) {
            showAlert("Please enter an entry date and time.");
            dateInput.focus();
            return false;
        }

        const allRows = rows();
        let validProductRowsCount = 0;
        let firstInvalidRow = null;
        let firstInvalidField = null;
        let alertMessage = "";

        // Check for duplicate products across rows
        const productCounts = new Map();
        for (const row of allRows) {
            const product = row.querySelector('[data-field="product"]');
            if (product && product.value) {
                productCounts.set(product.value, (productCounts.get(product.value) || 0) + 1);
            }
        }
        for (const row of allRows) {
            const product = row.querySelector('[data-field="product"]');
            if (product && product.value && productCounts.get(product.value) > 1) {
                firstInvalidRow = row;
                firstInvalidField = product;
                alertMessage = "This product is already included in another row.";
                break;
            }
        }

        if (firstInvalidRow) {
            firstInvalidRow.classList.add("row-invalid");
            showAlert(alertMessage);
            firstInvalidRow.scrollIntoView({ behavior: "smooth", block: "nearest" });
            if (firstInvalidField) firstInvalidField.focus();
            return false;
        }

        // Validate each row according to the requirements
        for (const row of allRows) {
            const product = row.querySelector('[data-field="product"]');
            const cartons = row.querySelector('[data-field="received_ctn"]');
            const pieces = row.querySelector('[data-field="received_pcs"]');
            const rowError = row.querySelector("[data-row-error]");
            const hasProduct = Boolean(product && product.value);
            const ctnStr = cartons ? cartons.value.trim() : "";
            const pcsStr = pieces ? pieces.value.trim() : "";
            const ctnNum = numberValue(cartons);
            const pcsNum = numberValue(pieces);
            const hasQty = (ctnStr !== "" && ctnStr !== "0") || (pcsStr !== "" && pcsStr !== "0") || ctnNum > 0 || pcsNum > 0;

            // Requirement 3: If completely empty, ignore it completely (no warning, no error)
            if (!hasProduct && !hasQty) {
                row.classList.remove("row-invalid");
                if (rowError) rowError.textContent = "";
                continue;
            }

            // Requirement 2: Quantity entered, but NO product selected
            if (!hasProduct && hasQty) {
                row.classList.add("row-invalid");
                row.dataset.hasSaveError = "true";
                if (rowError) rowError.textContent = "Please select a product for this row.";
                if (!firstInvalidRow) {
                    firstInvalidRow = row;
                    firstInvalidField = product;
                    alertMessage = "Please select a product for every stock-entry row containing a quantity.";
                }
                continue;
            }

            // Requirement 4: Product selected, but quantity is missing or invalid
            if (hasProduct) {
                const cartonSize = Number(piecesPerCarton[product.value] || 0);

                if (ctnStr === "" || isNaN(Number(ctnStr)) || Number(ctnStr) < 0) {
                    row.classList.add("row-invalid");
                    row.dataset.hasSaveError = "true";
                    if (rowError) rowError.textContent = "Please enter a valid carton quantity.";
                    if (!firstInvalidRow) {
                        firstInvalidRow = row;
                        firstInvalidField = cartons;
                        alertMessage = "Please enter a valid quantity for every selected product.";
                    }
                    continue;
                }

                if (pcsStr === "" || isNaN(Number(pcsStr)) || Number(pcsStr) < 0) {
                    row.classList.add("row-invalid");
                    row.dataset.hasSaveError = "true";
                    if (rowError) rowError.textContent = "Please enter a valid piece quantity.";
                    if (!firstInvalidRow) {
                        firstInvalidRow = row;
                        firstInvalidField = pieces;
                        alertMessage = "Please enter a valid quantity for every selected product.";
                    }
                    continue;
                }

                if (ctnNum === 0 && pcsNum === 0) {
                    row.classList.add("row-invalid");
                    row.dataset.hasSaveError = "true";
                    if (rowError) rowError.textContent = "Enter at least one carton or one piece.";
                    if (!firstInvalidRow) {
                        firstInvalidRow = row;
                        firstInvalidField = cartons;
                        alertMessage = "Please enter a valid quantity for every selected product.";
                    }
                    continue;
                }

                if (cartonSize > 0 && pcsNum >= cartonSize) {
                    row.classList.add("row-invalid");
                    row.dataset.hasSaveError = "true";
                    if (rowError) rowError.textContent = `Partial pieces must be less than this product's Pieces per CTN value (${cartonSize}).`;
                    if (!firstInvalidRow) {
                        firstInvalidRow = row;
                        firstInvalidField = pieces;
                        alertMessage = "Partial pieces must be less than the product's Pieces per CTN value.";
                    }
                    continue;
                }

                // Row is valid!
                validProductRowsCount++;
                row.classList.remove("row-invalid");
                delete row.dataset.hasSaveError;
                if (rowError) rowError.textContent = "";
            }
        }

        if (firstInvalidRow) {
            showAlert(alertMessage);
            firstInvalidRow.scrollIntoView({ behavior: "smooth", block: "nearest" });
            if (firstInvalidField) firstInvalidField.focus();
            return false;
        }

        // At least one product row must have a valid quantity
        if (validProductRowsCount === 0) {
            showAlert("Please add at least one product with a valid quantity before saving.");
            const firstRow = allRows[0];
            if (firstRow) {
                firstRow.classList.add("row-invalid");
                const firstProduct = firstRow.querySelector('[data-field="product"]');
                if (firstProduct) firstProduct.focus();
            }
            return false;
        }

        return true;
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

    rowsContainer.addEventListener("input", () => {
        hideAlert();
        updateRows();
    });
    rowsContainer.addEventListener("change", () => {
        hideAlert();
        updateRows();
    });

    form.addEventListener("submit", (event) => {
        if (!validateOnSave()) {
            event.preventDefault();
            event.stopPropagation();
            saveButton.disabled = false;
            saveButton.textContent = "Save All";
            return false;
        }

        saveButton.disabled = true;
        saveButton.textContent = "Saving...";
    });

    updateRows();
})();
