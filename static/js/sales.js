(() => {
    const finalSaveButton = document.querySelector('.save-button');
    if (finalSaveButton) {
        finalSaveButton.name = 'save_action';
        finalSaveButton.value = 'finalize';
        finalSaveButton.textContent = 'Final Save';
    }
    const dateInput = document.querySelector('#sales-date');
    const invoicePreview = document.querySelector('#invoice-number-preview');
    const routeInput = document.querySelector('#route-name');
    const routeDayInput = document.querySelector('#route-day');
    const suggestion = document.querySelector('#route-suggestion');
    const routeSuggestions = document.querySelector('#route-suggestions');
    if (dateInput && routeInput && routeDayInput && suggestion && routeSuggestions) {
        const weekdays = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
        const showExpectedRoute = (weekday) => {
            routeDayInput.value = weekday || '';
            const route = weekday && routeSuggestions.querySelector(`[data-weekday="${weekday}"]`);
            suggestion.hidden = !route;
            if (!route) return;

            routeInput.value = route.dataset.route;
            suggestion.querySelector('#expected-route-name').textContent = route.dataset.route;
            let weekdayElement = suggestion.querySelector('#expected-route-weekday');
            if (!weekdayElement) {
                weekdayElement = document.createElement('span');
                suggestion.append(' (', weekdayElement, ')');
            }
            weekdayElement.textContent = weekday;
        };
        const weekdayForDate = () => dateInput.value ? weekdays[new Date(`${dateInput.value}T00:00:00`).getDay()] : null;

        dateInput.addEventListener('change', () => showExpectedRoute(weekdayForDate()));
        showExpectedRoute(weekdayForDate());
    }
    if (dateInput && invoicePreview) {
        dateInput.addEventListener('change', async () => {
            if (!dateInput.value) return;
            const response = await fetch(`${dateInput.dataset.previewUrl}?date=${encodeURIComponent(dateInput.value)}`);
            if (response.ok) invoicePreview.value = (await response.json()).invoice_number;
        });
    }

    const rows = document.querySelector('#sales-rows');
    const optionTemplate = document.querySelector('#product-options');
    const addButton = document.querySelector('#add-row');
    if (!rows || !optionTemplate) return;

    const showAvailableStock = (option) => {
        if (!option.dataset.stockLabel) option.dataset.stockLabel = option.textContent;
        option.textContent = `${option.dataset.stockLabel} [${option.dataset.available || 0} PCS]`;
    };
    optionTemplate.content.querySelectorAll('option').forEach(showAvailableStock);
    rows.querySelectorAll('option[data-available]').forEach(showAvailableStock);

    const number = (value) => Number.parseFloat(value) || 0;
    const money = (value) => number(value).toFixed(2);

    function updateTotals() {
        const totals = { orderQty: 0, returnQty: 0, returnValue: 0, saleQty: 0, sale: 0, damageQty: 0, damage: 0, freeQty: 0, free: 0, order: 0 };
        rows.querySelectorAll('.sales-row').forEach((row) => {
            totals.orderQty += number(row.querySelector('.order').value);
            totals.returnQty += number(row.querySelector('.returned').value);
            totals.returnValue += number(row.querySelector('.return-value').textContent);
            totals.saleQty += number(row.querySelector('.sale-quantity').textContent);
            totals.damageQty += number(row.querySelector('.damage').value);
            totals.damage += number(row.querySelector('.damage-value').textContent);
            totals.freeQty += number(row.querySelector('.free-product').value);
            totals.free += number(row.querySelector('.free-product-value').textContent);
            totals.order += number(row.querySelector('.order-value').textContent);
            totals.sale += number(row.querySelector('.sale-value-total').textContent);
        });
        const mappings = { 'total-order-qty': totals.orderQty, 'total-return-qty': totals.returnQty, 'total-return-value': totals.returnValue, 'total-sale-qty': totals.saleQty, 'total-sale': totals.sale, 'total-damage-qty': totals.damageQty, 'total-damage': totals.damage, 'total-free-qty': totals.freeQty, 'total-free': totals.free, 'total-order': totals.order };
        Object.entries(mappings).forEach(([id, value]) => { document.getElementById(id).textContent = money(value); });
        const grandTotal = totals.sale;
        document.getElementById('grand-total').textContent = money(grandTotal);
        const payment = (name) => number(document.querySelector(`[name="${name}"]`)?.value);
        document.getElementById('shortage').textContent = money(grandTotal - payment('cash') - payment('expenses') - payment('credit') - payment('payment_discount') - payment('others'));
    }

    function updateRow(row) {
        const option = row.querySelector('.product-select').selectedOptions[0];
        const hasProduct = option && option.value;
        const ctn = hasProduct ? number(option.dataset.ctn) : 0;
        const available = hasProduct ? number(option.dataset.available) : 0;
        const dealer = hasProduct ? number(option.dataset.dealer) : 0;
        const trade = hasProduct ? number(option.dataset.trade) : 0;
        const foc = hasProduct ? number(option.dataset.foc) : 0;
        const sale = hasProduct ? number(option.dataset.sale) || trade : 0;
        row.querySelector('.category-cell').textContent = hasProduct ? option.dataset.category : '-';
        row.querySelector('.ctn-cell').textContent = hasProduct ? ctn : '-';
        row.querySelector('.dealer-price').textContent = hasProduct ? money(dealer) : '-';
        row.querySelector('.trade-price').textContent = hasProduct ? money(trade) : '-';
        row.querySelector('.foc-price').textContent = hasProduct ? money(foc) : '-';
        row.querySelector('.sale-price').textContent = hasProduct ? money(sale) : '-';
        const order = number(row.querySelector('.order').value);
        const returned = number(row.querySelector('.returned').value);
        const damage = number(row.querySelector('.damage').value);
        const free = number(row.querySelector('.free-product').value);
        const saleQuantity = order - returned - damage;
        row.classList.toggle('row-invalid', returned + damage > order);
        row.classList.toggle('stock-short', hasProduct && order * ctn > available);
        row.querySelector('.sale-quantity').textContent = money(saleQuantity);
        row.querySelector('.damage-value').textContent = money(damage * sale);
        row.querySelector('.free-product-value').textContent = money(free * sale);
        row.querySelector('.order-value').textContent = money(order * sale);
        row.querySelector('.return-value').textContent = money(returned * sale);
        row.querySelector('.sale-value-total').textContent = money(saleQuantity * sale);
        updateTotals();
    }

    function bindRow(row) {
        row.querySelector('.product-select').addEventListener('change', () => updateRow(row));
        row.querySelectorAll('input').forEach((input) => input.addEventListener('input', () => updateRow(row)));
        row.querySelector('.remove-row').addEventListener('click', () => { if (rows.children.length > 1) { row.remove(); updateTotals(); } });
        updateRow(row);
    }

    addButton.addEventListener('click', () => {
        const row = rows.querySelector('.sales-row').cloneNode(true);
        row.querySelector('.product-select').innerHTML = '<option value="">Select product</option>' + optionTemplate.innerHTML;
        row.querySelectorAll('input').forEach((input) => { input.value = '0'; });
        row.querySelectorAll('.calc').forEach((cell) => { cell.textContent = cell.classList.contains('category-cell') || cell.classList.contains('ctn-cell') || cell.classList.contains('dealer-price') || cell.classList.contains('trade-price') || cell.classList.contains('foc-price') || cell.classList.contains('sale-price') ? '-' : '0.00'; });
        rows.appendChild(row);
        bindRow(row);
    });

    document.querySelectorAll('.recon-input').forEach((input) => input.addEventListener('input', updateTotals));
    rows.querySelectorAll('.sales-row').forEach(bindRow);
})();
/*
    const cashInput = document.querySelector('[name="cash"]');
    const currencyCountInputs = document.querySelectorAll('[data-currency-count]');

    function updateCashFromCurrencyCount() {
        if (!cashInput || !currencyCountInputs.length) return;
        let total = 0;
        currencyCountInputs.forEach((input) => {
            const denomination = number(input.dataset.denomination);
            const count = number(input.value);
            const amount = denomination * count;
            total += amount;
            const amountCell = document.querySelector(`.currency-amount[data-denomination="${input.dataset.denomination}"]`);
            if (amountCell) amountCell.textContent = money(amount);
        });
        const totalElement = document.querySelector('#currency-count-total');
        if (totalElement) totalElement.textContent = money(total);
        cashInput.value = money(total);
    }
        updateCashFromCurrencyCount();
    currencyCountInputs.forEach((input) => input.addEventListener('input', updateTotals));
*/
(() => { const cashInput = document.querySelector('[name="cash"]'); const inputs = [...document.querySelectorAll('[data-currency-count]')]; const activeInput = document.querySelector('[name="currency_count_active"]'); if (!cashInput || !inputs.length) return; const number = (value) => Math.max(Number.parseFloat(value) || 0, 0); const money = (value) => number(value).toFixed(2); const updateCash = () => { let total = 0; inputs.forEach((input) => { const amount = number(input.dataset.denomination) * number(input.value); total += amount; const cell = document.querySelector(`.currency-amount[data-denomination="${input.dataset.denomination}"]`); if (cell) cell.textContent = money(amount); }); const totalCell = document.querySelector('#currency-count-total'); if (totalCell) totalCell.textContent = money(total); cashInput.value = money(total); cashInput.dispatchEvent(new Event('input', { bubbles: true })); }; cashInput.readOnly = true; if (!activeInput || activeInput.value === '1') updateCash(); inputs.forEach((input) => input.addEventListener('input', () => { if (activeInput) activeInput.value = '1'; updateCash(); })); })();
