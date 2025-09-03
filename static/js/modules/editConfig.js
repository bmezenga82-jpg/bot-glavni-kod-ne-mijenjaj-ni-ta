export function openEditModal(id, symbol, buyPercentage, sellPercentage, amount, exchange, mode, profitMode) {
    document.getElementById('edit-id').value = id;
    document.getElementById('edit-symbol').value = symbol;
    document.getElementById('buyPercentage').value = buyPercentage;
    document.getElementById('sellPercentage').value = sellPercentage;
    document.getElementById('amount').value = amount;
    const exSelect = document.getElementById('exchangeSelect');
    if (exSelect) exSelect.value = exchange;
    const modeSelect = document.getElementById('tradingMode');
    if (modeSelect) {
        if (exchange === 'binance') {
            modeSelect.innerHTML = '<option value="testnet">Testnet</option><option value="real">Real</option>';
        } else {
            modeSelect.innerHTML = '<option value="real">Real</option>';
        }
        modeSelect.value = (exchange === 'binance' && mode === 'testnet') ? 'testnet' : 'real';
    }
    const profitSelect = document.getElementById('profitMode');
    if (profitSelect) {
        profitSelect.value = profitMode || 'usdc';
    }
    document.getElementById('editConfigModalLabel').textContent = `Pair Configuration for ${symbol}`;
    const modal = new bootstrap.Modal(document.getElementById('editConfigModal'));
    modal.show();
}

export function saveConfig() {
    const id = document.getElementById('edit-id').value;
    const symbol = document.getElementById('edit-symbol').value;
    const buyPercentage = document.getElementById('buyPercentage').value;
    const sellPercentage = document.getElementById('sellPercentage').value;
    const amount = document.getElementById('amount').value;
    const mode = document.getElementById('tradingMode').value;
    const profitMode = document.getElementById('profitMode').value;

    fetch('/api/update_pair_config', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            pair_id: parseInt(id),
            symbol: symbol,
            buy_percentage: parseFloat(buyPercentage),
            sell_percentage: parseFloat(sellPercentage),
            amount: parseFloat(amount),
            exchange: document.getElementById('exchangeSelect').value,
            trading_mode: mode,
            profit_mode: profitMode
        }),
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            alert('Configuration updated successfully!');
            const modal = bootstrap.Modal.getInstance(document.getElementById('editConfigModal'));
            modal.hide();

            document.getElementById(`buy-${id}`).innerText = parseFloat(buyPercentage);
            document.getElementById(`sell-${id}`).innerText = parseFloat(sellPercentage);
            document.getElementById(`amount-${id}`).innerText = parseFloat(amount);
            const modeEl = document.getElementById(`mode-${id}`);
            if (modeEl) modeEl.innerText = mode;
            const pmEl = document.getElementById(`profit-${id}`);
            if (pmEl) pmEl.innerText = profitMode;
        } else {
            alert('Failed to update configuration: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error updating config:', error);
        alert('Error updating configuration.');
    });
}
