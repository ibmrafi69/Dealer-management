(() => {
    const rows = [...document.querySelectorAll('.invoice-edit-row')];
    const number = (value) => Math.max(Number.parseFloat(value) || 0, 0);
    const money = (value) => value.toFixed(2);

    function updateTotals() {
        const totalSale = rows.reduce(
            (sum, row) => sum + number(row.querySelector('.sale-value-output').textContent),
            0,
        );
        document.getElementById('edit-grand-total').textContent = money(totalSale);
        const payment = (name) => number(document.querySelector(`[name="${name}"]`).value);
        document.getElementById('edit-shortage').textContent = money(totalSale - payment('cash') - payment('expenses') - payment('credit') - payment('discount') - payment('others'));
    }

    function updateRow(row) {
        const order = number(row.dataset.orderQuantity);
        const returned = number(row.dataset.returnQuantity);
        const salePrice = number(row.querySelector('.sale-price-input').value);
        const damage = number(row.dataset.damageQuantity);
        const saleQuantity = order - returned - damage;
        row.querySelector('.sale-value-output').textContent = money(saleQuantity * salePrice);
        updateTotals();
    }

    rows.forEach((row) => {
        row.querySelectorAll('.edit-price').forEach((input) => input.addEventListener('input', () => updateRow(row)));
        updateRow(row);
    });
    document.querySelectorAll('.edit-payment').forEach((input) => input.addEventListener('input', updateTotals));
})();
(() => { const cashInput = document.querySelector('[name="cash"]'); const inputs = [...document.querySelectorAll('[data-currency-count]')]; const activeInput = document.querySelector('#currency-count-active'); if (!cashInput || !inputs.length) return; const number = (value) => Math.max(Number.parseFloat(value) || 0, 0); const money = (value) => number(value).toFixed(2); const updateCash = () => { let total = 0; inputs.forEach((input) => { const amount = number(input.dataset.denomination) * number(input.value); total += amount; const cell = document.querySelector(`.currency-amount[data-denomination="${input.dataset.denomination}"]`); if (cell) cell.textContent = money(amount); }); const totalCell = document.querySelector('#currency-count-total'); if (totalCell) totalCell.textContent = money(total); cashInput.value = money(total); cashInput.dispatchEvent(new Event('input', { bubbles: true })); }; cashInput.readOnly = true; if (activeInput && activeInput.value === '1') updateCash(); inputs.forEach((input) => input.addEventListener('input', () => { if (activeInput) activeInput.value = '1'; updateCash(); })); })();
