export function validateSettingsForm() {
    const form = document.getElementById('trading-pairs-form');
    if (form) {
        form.addEventListener('submit', (event) => {
            const selected = document.getElementById('selected_pairs').selectedOptions;
            if (!selected.length) {
                alert('Please select at least one trading pair.');
                event.preventDefault();
                return;
            }
            const buyInputs = document.querySelectorAll('input[name^="buy_percentage"]');
            for (const input of buyInputs) {
                const value = parseFloat(input.value);
                if (isNaN(value)) {
                    alert('Buy percentage must be a valid number for all pairs.');
                    event.preventDefault();
                    return;
                }
            }
            const sellInputs = document.querySelectorAll('input[name^="sell_percentage"]');
            for (const input of sellInputs) {
                const value = parseFloat(input.value);
                if (value <= 0 || isNaN(value)) {
                    alert('Sell percentage must be positive for all pairs.');
                    event.preventDefault();
                    return;
                }
            }
            const amountInputs = document.querySelectorAll('input[name^="amount"]');
            for (const input of amountInputs) {
                const value = parseFloat(input.value);
                if (value <= 0 || isNaN(value)) {
                    alert('Amount must be positive for all pairs.');
                    event.preventDefault();
                    return;
                }
            }
        });
    }
}

export function setupPairSelector(selected) {
   const exchangeSelect = document.getElementById('new_exchange');
   const pairSelect = document.getElementById('new_pair');
    const modeSelect = document.getElementById('new_mode');
    if (!exchangeSelect || !pairSelect) return;

    function loadPairs() {
        const ex = exchangeSelect.value;
        fetch(`/api/exchange_pairs?exchange=${ex}`)
            .then(r => r.json())
            .then(data => {
                pairSelect.innerHTML = '<option value="">Select a pair</option>';
                data.pairs.forEach(p => {
                    if (!selected.includes(p)) {
                        const opt = document.createElement('option');
                        opt.value = p;
                        opt.textContent = p;
                        pairSelect.appendChild(opt);
                    }
                });
            });

        if (modeSelect) {
            if (ex === 'binance') {
                modeSelect.innerHTML = '<option value="testnet">Testnet</option><option value="real">Real</option>';
            } else {
                modeSelect.innerHTML = '<option value="real">Real</option>';
            }
        }
    }

    exchangeSelect.addEventListener('change', loadPairs);

    // Fetch pairs for the initially selected exchange on page load
    if (document.readyState !== 'loading') {
        loadPairs();
    } else {
        document.addEventListener('DOMContentLoaded', loadPairs, { once: true });
    }
}

export function runBacktest() {
    const form = document.getElementById('backtest-form');
    const formData = new FormData(form);
    fetch('/backtest', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.results) {
            let resultText = '';
            for (const [symbol, result] of Object.entries(data.results)) {
                resultText += `Symbol: ${symbol}\n`;
                resultText += `Net Profit: ${result.net_profit.toFixed(2)} USDC\n`;
                resultText += 'Trade Log:\n';
                result.trade_log.forEach(log => resultText += `  ${log}\n`);
                resultText += '\n';
            }
            document.getElementById('backtest-results').textContent = resultText;
        } else {
            document.getElementById('backtest-results').textContent = 'No results available.';
        }
    })
    .catch(error => {
        document.getElementById('backtest-results').textContent = 'Error running backtest: ' + error;
    });
}

export function runOptimize() {
    const form = document.getElementById('backtest-form');
    const formData = new FormData(form);
    fetch('/optimize', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        document.getElementById('backtest-results').textContent = `Best Buy Percentage: ${data.best_buy_percentage}%\nBest Sell Percentage: ${data.best_sell_percentage}%`;
    })
    .catch(error => {
        document.getElementById('backtest-results').textContent = 'Error running optimization: ' + error;
    });
}
