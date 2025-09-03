const socket = io();
let priceCache = {};

function toggleTheme() {
    fetch('/toggle_theme', { method: 'POST' })
        .then(resp => resp.json())
        .then(data => {
            const html = document.documentElement;
            html.classList.remove('light', 'dark');
            html.classList.add(data.theme);

            const icon = document.getElementById('theme-icon');
            if (icon) {
                icon.className = `bi ${data.theme === 'dark' ? 'bi-sun-fill' : 'bi-moon-fill'} me-1`;
            }
            const toggle = document.querySelector('.theme-toggle');
            if (toggle) {
                toggle.innerHTML = `<i class="bi ${data.theme === 'dark' ? 'bi-sun-fill' : 'bi-moon-fill'} me-1" id="theme-icon"></i> ${data.theme === 'dark' ? 'Light' : 'Dark'}`;
            }
        })
        .catch(err => console.error('Theme toggle failed', err));
}
window.toggleTheme = toggleTheme;

function attachControlHandlers(toggleBot, updateData) {
    document.querySelectorAll('button[id^="action-"]').forEach(btn => {
        if (!btn.dataset.bound) {
            btn.addEventListener('click', () => {
                const pairId = parseInt(btn.id.replace('action-', ''));
                const row = btn.closest('tr');
                const symbol = row ? row.dataset.symbol : '';
                const exchange = row ? row.dataset.exchange : '';
                const mode = row ? row.dataset.mode : '';
                toggleBot(pairId, symbol, exchange, mode, btn.id)
                    .then(() => {
                        updateData();
                    })
                    .catch(err => console.error('toggleBot failed', err));
            });
            btn.dataset.bound = 'true';
        }
    });
}

async function initializeApp() {
    // Load modules dynamically based on page requirements
    if (document.getElementById('price-table')) {
        const { updateData, resetProfit, resetExchangeProfit, removePairProfit } = await import('./modules/market_data.js');
        const editModule = await import('./modules/editConfig.js');
        window.openEditModal = editModule.openEditModal;
        window.saveConfig = editModule.saveConfig;
        window.resetProfit = resetProfit;
        window.resetExchangeProfit = resetExchangeProfit;
        window.removePairProfit = removePairProfit;

        const { toggleBot, updateAllBotStatuses } = await import('./modules/bot_control.js');
        attachControlHandlers(toggleBot, updateData);

        // Initial status update and start polling
        if (document.getElementById('price-table-body')) { // Check if we are on the dashboard
            updateAllBotStatuses(); // Initial call
            setInterval(updateAllBotStatuses, 5000); // Poll every 5 seconds
        }

        const baseSelect = document.getElementById('base-currency-select');
        if (baseSelect) {
            baseSelect.addEventListener('change', e => {
                fetch('/set_base_currency', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ base_currency: e.target.value })
                });
            });
        }



        setInterval(() => {
            updateData().then(() => attachControlHandlers(toggleBot, updateData));
        }, 30000);
        updateData().then(() => attachControlHandlers(toggleBot, updateData));
    }
    if (document.getElementById('market-overview-table')) {
        const { initializeMarketTable } = await import('./modules/market_data.js');
        fetch('/api/data')
            .then(response => response.json())
            .then(data => {
                priceCache = data.prices;
                const pairs = Object.keys(data.prices);
                initializeMarketTable(pairs, priceCache);
            })
            .catch(error => console.error('Error fetching pairs:', error));
    }
    if (document.getElementById('profitChart')) {
        const { renderProfitChart } = await import('./modules/charts.js');
        renderProfitChart();
    }
    if (document.getElementById('profit-log-table')) { // Updated ID to check for the new table
        const { loadProfitLogData, initTradesPage } = await import('./modules/trades.js');
        initTradesPage();
        loadProfitLogData(); // Initial call to load data for page 1
    }
    if (document.getElementById('trading-pairs-form')) {
        const { validateSettingsForm, setupPairSelector } = await import('./modules/settings.js');
        validateSettingsForm();
        if (window.selectedSymbols) {
            setupPairSelector(window.selectedSymbols);
        }
    }
    if (document.getElementById('backtest-form')) {
        const settingsModule = await import('./modules/settings.js');
        settingsModule.validateSettingsForm();

        // Expose for inline HTML usage
        window.runBacktest = settingsModule.runBacktest;
        window.runOptimize = settingsModule.runOptimize;
    }
}

socket.on('price_update', (data) => {
    const prices = data.prices;
    const trade_status = data.trade_status || {};
    priceCache = { ...priceCache, ...prices };
    if (document.getElementById('market-overview-table')) {
        import('./modules/market_data.js').then(({ updateMarketTable }) => {
            updateMarketTable(prices, priceCache);
        });
    }
    for (const symbol in prices) {
        // Find the table row using the 'data-symbol' attribute
        const row = document.querySelector(`tr[data-symbol='${symbol}']`);
        if (!row) {
            // If no row is found for the symbol, skip to the next symbol.
            // This could happen if a price update is received for a symbol not currently in the table.
            console.warn(`Price update for symbol '${symbol}' but no matching row found in the table.`);
            continue;
        }

        // Get the 'data-id' attribute from the row
        const id = row.getAttribute('data-id');
        if (!id) {
            console.warn(`Row found for symbol '${symbol}' but it's missing a 'data-id' attribute.`);
            continue;
        }

        // Find the specific price cell using its ID, e.g., "price-1", "price-2"
        const priceElement = document.getElementById(`price-${id}`);
        if (priceElement) {
            // Update the cell's text with the new price, formatted to 4 decimal places.
            // Handles 'N/A' case if the price is not a number.
            priceElement.innerText = prices[symbol] !== 'N/A' && typeof prices[symbol] === 'number'
                ? prices[symbol].toFixed(4)
                : (prices[symbol] || 'N/A'); // Display 'N/A' if price is null/undefined
        } else {
            // This would be an issue: row found, data-id found, but no price cell for that id.
            console.warn(`Price cell with id 'price-${id}' not found for symbol '${symbol}'.`);
        }

        // ... (rest of the code updates the Start/Stop button based on trade_status) ...
        const btn = document.getElementById(`action-${id}`);
        if (btn) {
            const running = trade_status[symbol];
            btn.innerText = running ? 'Stop' : 'Start';
            btn.classList.toggle('btn-success', !running);
            btn.classList.toggle('btn-danger', running);
            const editActionBtn = document.getElementById("edit-" + id);
            if (editActionBtn) {
                if (running) {
                    editActionBtn.classList.add("disabled");
                } else {
                    editActionBtn.classList.remove("disabled");
                }
            }
        }
    }
});

function searchPair() {
    const query = document.getElementById('pair-search').value.toUpperCase();
    const rows = document.querySelectorAll('#pairs-table tr');
    rows.forEach(row => {
        const symbol = row.cells[0].textContent.toUpperCase();
        row.style.display = symbol.includes(query) ? '' : 'none';
    });
}

function logout() {
    window.location.href = '/logout';
}

document.addEventListener('DOMContentLoaded', initializeApp);

// Live Strategy Log listener
socket.on('live_strategy_log', function(msg) {
    const logWindow = document.getElementById('live-strategy-log-output');
    const messageText = msg.data;

    if (logWindow) {
        const logEntry = document.createTextNode(messageText + '\\n');
        logWindow.appendChild(logEntry);
        logWindow.scrollTop = logWindow.scrollHeight; // Auto-scroll to bottom
    }

    // Check for insufficient funds alert
    if (messageText && messageText.startsWith("[ALERT] Not enough balance")) {
        // Display a more prominent notification for this specific alert
        // For simplicity, using a browser alert. A more sophisticated UI would use a toast or modal.
        alert("Insufficient Funds Alert: \n" + messageText);

        // Potentially trigger a manual refresh of bot statuses if needed,
        // though the bot being stopped should eventually be reflected by polling or other updates.
        // Example: if (typeof updateAllBotStatuses === 'function') { updateAllBotStatuses(); }
        // However, updateAllBotStatuses is defined in bot_control.js and might not be globally available here
        // without specific import or exposing it globally.
        // The existing polling (setInterval(updateAllBotStatuses, 5000)) should pick up the change.
    }
});

// Request initial logs when socket connects (or reconnects)
socket.on('connect', function() {
    // Ensure this is only emitted if the log window exists, i.e., we are on the dashboard
    if (document.getElementById('live-strategy-log-output')) {
        socket.emit('request_initial_strategy_logs');
    }
});
