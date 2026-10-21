(() => {
    const form = document.querySelector('#pending-sales-form');
    const rowsContainer = document.querySelector('#pending-sales-rows');
    const productOptions = document.querySelector('#pending-product-options');
    const rowTemplate = document.querySelector('#pending-row-template');
    const addButton = document.querySelector('#add-pending-row');
    if (!form || !rowsContainer || !productOptions || !rowTemplate) return;

    const number = (value) => Math.max(Number.parseFloat(value) || 0, 0);
    const money = (value) => number(value).toFixed(2);
    const rows = () => [...rowsContainer.querySelectorAll('.pending-sales-row')];
    const payment = (name) => number(document.querySelector(`[name="${name}"]`)?.value);

    function updateTotals() {
        const totalSale = rows().reduce(
            (total, row) => total + number(row.querySelector('.pending-sale-value').textContent),
            0,
        );
        document.getElementById('pending-grand-total').textContent = money(totalSale);
        document.getElementById('pending-shortage').textContent = money(
            totalSale - payment('cash') - payment('expenses') - payment('credit') - payment('discount') - payment('others'),
        );
    }

    function updateRow(row) {
        const order = number(row.querySelector('[name="order_quantity"]').value);
        const price = number(row.dataset.price);
        const returned = number(row.querySelector('.pending-return').value);
        const damage = number(row.querySelector('.pending-damage').value);
        const freeProduct = number(row.querySelector('.pending-free-product').value);
        const saleQuantity = order - returned - damage;

        row.classList.toggle('row-invalid', returned + damage > order);
        row.querySelector('.pending-return-value').textContent = money(returned * price);
        row.querySelector('.pending-sale-quantity').textContent = money(saleQuantity);
        row.querySelector('.pending-sale-value').textContent = money(saleQuantity * price);
        row.querySelector('.pending-damage-value').textContent = money(damage * price);
        row.querySelector('.pending-free-product-value').textContent = money(freeProduct * price);
        updateTotals();
    }

    function setEditing(row, editing) {
        row.classList.toggle('is-editing', editing);
        row.querySelectorAll('.pending-row-editor').forEach((element) => {
            element.hidden = !editing;
        });
        row.querySelector('.pending-product-name').hidden = editing;
        row.querySelector('.pending-order-display').hidden = editing;
        row.querySelector('.pending-row-edit').hidden = editing;
        row.querySelector('.pending-row-save').hidden = !editing;
        row.querySelector('.pending-row-cancel').hidden = !editing;
    }

    function selectedProduct(row) {
        return row.querySelector('.pending-product-select').selectedOptions[0];
    }

    function commitRow(row) {
        const option = selectedProduct(row);
        if (!option?.value) {
            row.querySelector('.pending-product-select').focus();
            return false;
        }
        const order = number(row.querySelector('.pending-order-editor').value);
        row.querySelector('[name="product_id"]').value = option.value;
        row.querySelector('[name="order_quantity"]').value = order;
        row.dataset.price = option.dataset.price || '0';
        row.querySelector('.pending-product-name').innerHTML = `<strong>${option.textContent}</strong>`;
        row.querySelector('.pending-category-cell').textContent = option.dataset.category || '-';
        row.querySelector('.pending-ctn-cell').textContent = option.dataset.ctn || '-';
        row.querySelector('.pending-price-cell').textContent = money(option.dataset.price);
        row.querySelector('.pending-order-display').textContent = money(order);
        setEditing(row, false);
        updateRow(row);
        return true;
    }

    function cancelEdit(row) {
        if (!row.querySelector('[name="item_id"]').value) {
            row.remove();
            updateTotals();
            return;
        }
        row.querySelector('.pending-product-select').value = row.querySelector('[name="product_id"]').value;
        row.querySelector('.pending-order-editor').value = row.querySelector('[name="order_quantity"]').value;
        setEditing(row, false);
    }

    function bindRow(row) {
        row.querySelectorAll('.pending-return, .pending-damage, .pending-free-product, [name="line_discount"]').forEach((input) => {
            input.addEventListener('input', () => updateRow(row));
        });
        row.querySelector('.pending-row-edit').addEventListener('click', () => {
            row.querySelector('.pending-product-select').value = row.querySelector('[name="product_id"]').value;
            row.querySelector('.pending-order-editor').value = row.querySelector('[name="order_quantity"]').value;
            setEditing(row, true);
            row.querySelector('.pending-product-select').focus();
        });
        row.querySelector('.pending-row-save').addEventListener('click', () => {
            if (!commitRow(row)) return;
            form.requestSubmit(form.querySelector('[name="save_action"][value="pending"]'));
        });
        row.querySelector('.pending-row-cancel').addEventListener('click', () => cancelEdit(row));
        row.querySelector('.remove-pending-row').addEventListener('click', () => {
            row.remove();
            updateTotals();
        });
        updateRow(row);
    }

    function addRow() {
        const row = rowTemplate.content.firstElementChild.cloneNode(true);
        const select = row.querySelector('.pending-product-select');
        select.innerHTML = '<option value="">Select product</option>' + productOptions.innerHTML;
        rowsContainer.appendChild(row);
        bindRow(row);
        setEditing(row, true);
        select.focus();
    }

    rows().forEach((row) => {
        bindRow(row);
        setEditing(row, false);
    });
    addButton?.addEventListener('click', addRow);

    form.addEventListener('submit', (event) => {
        for (const row of rows()) {
            if (row.classList.contains('is-editing') && !commitRow(row)) {
                event.preventDefault();
                return;
            }
        }
    });

    document.querySelectorAll('.pending-payment').forEach((input) => {
        input.addEventListener('input', updateTotals);
    });
    const cashInput = document.querySelector('[name="cash"]');
    const currencyInputs = [...document.querySelectorAll('[data-currency-count]')];
    const updateCash = () => {
        let total = 0;
        currencyInputs.forEach((input) => {
            const amount = number(input.dataset.denomination) * number(input.value);
            total += amount;
            const cell = document.querySelector(`.currency-amount[data-denomination="${input.dataset.denomination}"]`);
            if (cell) cell.textContent = money(amount);
        });
        const totalCell = document.getElementById('currency-count-total');
        if (totalCell) totalCell.textContent = money(total);
        if (cashInput) cashInput.value = money(total);
        updateTotals();
    };
    if (cashInput && currencyInputs.length) {
        cashInput.readOnly = true;
        currencyInputs.forEach((input) => input.addEventListener('input', updateCash));
        updateCash();
    }
})();
