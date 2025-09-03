import { updateNotifications } from './notifications.js';
window.currentTradeStatus = {};

export function initializeMarketTable(pairs, priceCache) {
    const table = $('#market-overview-table').DataTable({
        data: pairs.map(pair => [pair, priceCache[pair] ? `$${priceCache[pair].toFixed(4)}` : 'Loading...']),
        columns: [
            { title: 'Symbol' },
            { title: 'Price (USDC)' }
        ],
        paging: false,
        searching: false,
        info: false
    });
    updateMarketTable(priceCache, priceCache);
}

export function updateMarketTable(prices, priceCache) {
    const table = $('#market-overview-table').DataTable();
    table.rows().every(function() {
        const row = this.data();
        const symbol = row[0];
        row[1] = priceCache[symbol] && priceCache[symbol] !== 'N/A' ? `$${priceCache[symbol].toFixed(4)}` : 'N/A';
        this.data(row).draw(false);
    });
}

export function updateData() {
    return fetch('/api/data')
        .then(response => response.json())
        .then(data => {

            const ordersTable = document.getElementById('orders-body');
            if (ordersTable) {
                ordersTable.innerHTML = '';
                for (const [symbol, orders] of Object.entries(data.orders)) {
                    for (const [side, details] of Object.entries(orders)) {
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td>${details.order_id || 'N/A'}</td>
                            <td>${symbol}</td>
                            <td>${details.exchange || 'N/A'}</td>
                            <td>${side}</td>
                            <td class="text-end">${details.amount}</td>
                            <td class="text-end">${details.price}</td>`;
                        ordersTable.appendChild(row);
                    }
                }
            }

            updateNotifications().then(notes => {
                const logEl = document.getElementById('strategy-log');
                if (logEl) {
                    logEl.innerHTML = '';
                    Object.entries(notes).forEach(([sym, msgs]) => {
                        msgs.slice(-10).forEach(msg => {
                            const li = document.createElement('li');
                            li.className = `list-group-item ${msg.type === 'error' ? 'text-danger' : 'text-success'}`;
                            li.textContent = `${sym}: ${msg.message}`;
                            logEl.appendChild(li);
                        });
                    });
                }
            });

            const totalProfitElement = document.getElementById('total-profit');
            if (totalProfitElement) {
                totalProfitElement.innerText = data.total_profit.toFixed(2);
            }
        const activePairsElement = document.getElementById('active-pairs');
        if (activePairsElement) {
            activePairsElement.innerText = data.active_pairs;
        }

            // Populate initial prices in the main price table from /api/data
            if (data.prices) {
                for (const symbol in data.prices) {
                    const row = document.querySelector(`tr[data-symbol='${symbol}']`);
                    if (!row) continue;
                    const id = row.getAttribute('data-id');
                    if (!id) continue;

                    const priceElement = document.getElementById(`price-${id}`);
                    if (priceElement) {
                        const priceValue = data.prices[symbol];
                        priceElement.innerText = priceValue !== 'N/A' && typeof priceValue === 'number'
                            ? priceValue.toFixed(4)
                            : (priceValue || 'N/A');
                    }
                }
            }

            if (data.trade_status) {
                window.currentTradeStatus = data.trade_status;
                for (const [symbol, running] of Object.entries(data.trade_status)) {
                    const row = document.querySelector(`tr[data-symbol='${symbol}']`);
                    if (!row) continue;
                    const id = row.getAttribute('data-id');
                    const btn = document.getElementById(`action-${id}`);
                    if (btn) {
                        btn.innerText = running ? 'Stop' : 'Start';
                        btn.classList.toggle('btn-success', !running);
                        btn.classList.toggle('btn-danger', running);
                        const editBtn = document.getElementById(`edit-action-${id}`);
                        if (editBtn) {
                            running ? editBtn.classList.add('disabled') : editBtn.classList.remove('disabled');
                        }
                    }
                }
            }

            if (data.account_info) {
                renderAccountInfo(data.account_info);
            }
        })
        .then(() => fetch('/api/pair_profit'))
        .then(r => r.json())
        .then(profits => {
            if (profits && typeof profits === 'object') {
                renderPairProfits(profits);
            }
        })
        .then(() => fetch('/api/open_positions'))
        .then(r => r.json())
        .then(positions => {
            if (Array.isArray(positions)) {
                renderOpenPositions(positions);
            }
        })
        .catch(error => {
            console.error('Error fetching data:', error);
        });
}

export function resetProfit(pairId) {
    if (!confirm('Reset profit totals for this pair?')) return;
    fetch('/api/reset_profit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pair_id: pairId })
    }).then(r => r.json())
      .then(resp => {
        if (resp.status === 'success') {
            [
                `profit-usdc-info-${pairId}`,
                `profit-crypto-info-${pairId}`
            ].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.innerText = '0.0';
            });
        } else {
            alert('Failed to reset profit');
        }
      })
      .catch(err => console.error('Reset error', err));
}

export function removePairProfit(pairId) {
    if (!confirm('Remove profit record for this pair?')) return;
    fetch('/api/remove_pair_profit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pair_id: pairId })
    })
    .then(r => r.json())
    .then(resp => {
        if (resp.status === 'success') {
            const row = document.querySelector(`tr[data-pair-id="${pairId}"]`);
            if (row) {
                const tbody = row.parentElement;
                row.remove();
                const key = tbody.id.replace('profit-body-', '');
                let totalUsdc = 0;
                let totalCrypto = 0;
                tbody.querySelectorAll('tr').forEach(rw => {
                    const id = rw.dataset.pairId;
                    const usdcEl = document.getElementById(`profit-usdc-info-${id}`);
                    const cryptoEl = document.getElementById(`profit-crypto-info-${id}`);
                    if (usdcEl) totalUsdc += parseFloat(usdcEl.textContent) || 0;
                    if (cryptoEl) totalCrypto += parseFloat(cryptoEl.textContent) || 0;
                });
                const heading = document.querySelector(`#heading-${key}`);
                if (heading) {
                    const usdcSpan = heading.querySelector('.account-pnl-usdc');
                    const cryptoSpan = heading.querySelector('.account-pnl-crypto');
                    if (usdcSpan) usdcSpan.textContent = totalUsdc.toFixed(4);
                    if (cryptoSpan) cryptoSpan.textContent = totalCrypto.toFixed(6);
                }
            }
        } else {
            alert('Failed to remove profit record');
        }
        updateData();
    })
    .catch(err => console.error('Remove error', err));
}

export function resetExchangeProfit(key) {
    const rows = document.querySelectorAll(`#profit-body-${key} tr`);
    rows.forEach(row => {
        const pairId = row.dataset.pairId;
        if (pairId) resetProfit(parseInt(pairId));
    });
}

function renderAccountInfo(accountInfo) {
    const container = document.getElementById('account-accordion');
    if (!container) return;
    const expanded = new Set();
    container.querySelectorAll('.accordion-collapse.show').forEach(el => {
        if (el.id) expanded.add(el.id);
    });
    container.innerHTML = '';
    Object.entries(accountInfo).forEach(([key, info]) => {
        const [ex, mode] = key.split('_');
        const collapseId = `collapse-${key}`;
        const tbodyId = `profit-body-${key}`;
        const item = document.createElement('div');
        item.className = 'accordion-item';
        item.innerHTML = `
            <h2 class="accordion-header d-flex align-items-center" id="heading-${key}">
              <button class="accordion-button collapsed flex-grow-1 me-2" type="button" data-bs-toggle="collapse" data-bs-target="#${collapseId}">
                <span class="fw-bold">${ex} - ${mode.charAt(0).toUpperCase() + mode.slice(1)}</span>
                <span class="ms-2 text-info">Bal: ${info.balance}</span>
                <span class="ms-2 text-success">USDC Profit: <span class="account-pnl-usdc">${info.pnl.usdc}</span></span>
                <span class="ms-2 text-warning">Token Profit: <span class="account-pnl-crypto">${info.pnl.crypto}</span></span>
                <span class="ms-2 text-warning">Active: ${info.active_pairs}</span>
              </button>
              <div class="dropdown">
                <button class="btn btn-sm btn-light dropdown-toggle p-0 border-0" type="button" data-bs-toggle="dropdown" aria-expanded="false">
                  <i class="bi bi-three-dots"></i>
                </button>
                <ul class="dropdown-menu dropdown-menu-end">
                  <li><a class="dropdown-item" href="#" id="reset-all-${key}" onclick="resetExchangeProfit('${key}')">Reset All</a></li>
                </ul>
              </div>
            </h2>
            <div id="${collapseId}" class="accordion-collapse collapse${expanded.has(collapseId) ? ' show' : ''}" data-bs-parent="#account-accordion">
              <div class="accordion-body">
                <table class="table table-sm">
                  <thead><tr><th>Pair</th><th>Profit (USDC)</th><th>Token Profit</th><th></th></tr></thead>
                  <tbody id="${tbodyId}"></tbody>
                </table>
              </div>
            </div>`;
        container.appendChild(item);
    });
}

function renderPairProfits(grouped) {
    Object.entries(grouped).forEach(([key, list]) => {
        const tbody = document.getElementById(`profit-body-${key}`);
        if (!tbody) return;
        tbody.innerHTML = '';
        let anyRunning = false;
        let totalUsdc = 0;
        let totalCrypto = 0;
        list.forEach(p => {
            const row = document.createElement('tr');
            row.dataset.pairId = p.pair_id;
            const running = window.currentTradeStatus[p.symbol];
            if (running) anyRunning = true;
            row.innerHTML = `
                <td>${p.symbol}</td>
                <td id="profit-usdc-info-${p.pair_id}">${Number(p.profit_usdc).toFixed(4)}</td>
                <td id="profit-crypto-info-${p.pair_id}">${Number(p.profit_crypto).toFixed(6)}</td>
                <td>
                    <button class="btn btn-xxs btn-secondary${running ? ' disabled' : ''}" style="padding:1px 4px;font-size:0.55rem;" onclick="resetProfit(${p.pair_id})">Reset</button>
                    <button class="btn btn-xxs btn-danger ms-1 remove-pair${running ? ' disabled' : ''}" style="padding:1px 4px;font-size:0.55rem;" onclick="removePairProfit(${p.pair_id})"><i class="bi bi-x-circle"></i></button>
                </td>`;
            tbody.appendChild(row);
            totalUsdc += Number(p.profit_usdc);
            totalCrypto += Number(p.profit_crypto);
        });
        const resetAllBtn = document.getElementById(`reset-all-${key}`);
        if (resetAllBtn) {
            resetAllBtn.classList.toggle('disabled', anyRunning);
        }

        const heading = document.querySelector(`#heading-${key}`);
        if (heading) {
            const usdcSpan = heading.querySelector('.account-pnl-usdc');
            const cryptoSpan = heading.querySelector('.account-pnl-crypto');
            if (usdcSpan) usdcSpan.textContent = totalUsdc.toFixed(4);
            if (cryptoSpan) cryptoSpan.textContent = totalCrypto.toFixed(6);
        }
    });
}

function renderOpenPositions(list) {
    const tbody = document.getElementById('open-positions-body');
    if (!tbody) return;

    // capture expanded groups before re-render
    const expanded = new Set();
    tbody.querySelectorAll('tr.group-header').forEach(tr => {
        const key = tr.dataset.groupKey;
        const row = tbody.querySelector(`tr.${key}`);
        if (row && row.classList.contains('show')) expanded.add(key);
    });

    tbody.innerHTML = '';

    const grouped = {};
    list.forEach(pos => {
        const key = `${pos.symbol}|${pos.exchange}`;
        if (!grouped[key]) grouped[key] = [];
        grouped[key].push(pos);
    });

    Object.entries(grouped).forEach(([key, positions]) => {
        const [symbol, exchange] = key.split('|');
        const groupClass = `pos-group-${symbol.replace(/[^a-zA-Z0-9]/g, '')}-${exchange}`;
        const totalQty = positions.reduce((s, p) => s + Number(p.quantity), 0);
        const totalProfitGroup = positions.reduce((s, p) => s + (p.current_pnl > 0 ? p.current_pnl : 0), 0);
        const totalLossGroup = positions.reduce((s, p) => s + (p.current_pnl < 0 ? p.current_pnl : 0), 0);
        const currentPrice = positions[0].current_price;
        const modes = [...new Set(positions.map(p => p.trading_mode))];
        const modeLabel = modes.length === 1 ? modes[0] : 'mixed';
        const isExpanded = expanded.has(groupClass);

        const header = document.createElement('tr');
        header.className = 'table-secondary group-header';
        header.dataset.groupKey = groupClass;
        header.innerHTML = `
            <td>${symbol}</td>
            <td>${exchange}</td>
            <td>${modeLabel}</td>
            <td class="text-end">${totalQty.toFixed(6)}</td>
            <td class="text-end">-</td>
            <td class="text-end">${currentPrice !== null && currentPrice !== undefined ? Number(currentPrice).toFixed(4) : 'N/A'}</td>
            <td class="text-end text-success">${totalProfitGroup.toFixed(2)}</td>
            <td class="text-end text-danger">${Math.abs(totalLossGroup).toFixed(2)}</td>
            <td class="text-end">
                <button class="btn btn-xxs btn-light toggle-pos" data-target="${groupClass}"><i class="bi ${isExpanded ? 'bi-chevron-up' : 'bi-chevron-down'}"></i></button>
                <button class="btn btn-xxs btn-danger ms-1 remove-pos" data-symbol="${symbol}" data-exchange="${exchange}" data-mode="${modeLabel}"><i class="bi bi-x-circle"></i></button>
            </td>`;
        tbody.appendChild(header);

        positions.forEach(p => {
            const pnl = typeof p.current_pnl === 'number' ? p.current_pnl : null;
            const row = document.createElement('tr');
            row.className = `collapse ${groupClass}${isExpanded ? ' show' : ''}`;
            row.innerHTML = `
                <td></td>
                <td></td>
                <td>${p.trading_mode}</td>
                <td class="text-end">${Number(p.quantity).toFixed(6)}</td>
                <td class="text-end">${Number(p.buy_price).toFixed(4)}</td>
                <td class="text-end">${p.current_price !== null && p.current_price !== undefined ? Number(p.current_price).toFixed(4) : 'N/A'}</td>
                <td class="text-end text-success">${pnl !== null && pnl > 0 ? pnl.toFixed(2) : '0.00'}</td>
                <td class="text-end text-danger">${pnl !== null && pnl < 0 ? Math.abs(pnl).toFixed(2) : '0.00'}</td>
                <td></td>`;
            tbody.appendChild(row);
        });
    });


    tbody.querySelectorAll('button.toggle-pos').forEach(btn => {
        btn.addEventListener('click', () => {
            const key = btn.dataset.target;
            const rows = tbody.querySelectorAll(`.${key}`);
            const expanded = rows.length && rows[0].classList.contains('show');
            // collapse others
            tbody.querySelectorAll('tr.collapse.show').forEach(r => r.classList.remove('show'));
            tbody.querySelectorAll('button.toggle-pos i').forEach(i => i.className = 'bi bi-chevron-down');
            if (!expanded) {
                rows.forEach(r => r.classList.add('show'));
                btn.querySelector('i').className = 'bi bi-chevron-up';
            }
        });
    });

    tbody.querySelectorAll('button.remove-pos').forEach(btn => {
        btn.addEventListener('click', () => {
            const symbol = btn.dataset.symbol;
            const exchange = btn.dataset.exchange;
            const mode = btn.dataset.mode;
            if (!confirm(`Remove open positions for ${symbol}?`)) return;
            fetch('/api/clear_open_positions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ symbol, exchange, trading_mode: mode === 'mixed' ? null : mode })
            })
            .then(r => r.json())
            .then(resp => {
                if (resp.status === 'success') {
                    const groupClass = `pos-group-${symbol.replace(/[^a-zA-Z0-9]/g, '')}-${exchange}`;
                    const headerRow = btn.closest('tr');
                    if (headerRow) headerRow.remove();
                    tbody.querySelectorAll(`.${groupClass}`).forEach(r => r.remove());
                } else {
                    alert('Failed to remove open positions');
                }
                updateData();
            });
        });
    });
}
