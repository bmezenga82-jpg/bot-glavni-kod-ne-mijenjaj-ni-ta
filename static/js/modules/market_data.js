import { updateNotifications } from './notifications.js';
import { toggleBot } from './bot_control.js';
window.currentTradeStatus = {};

// Expose functions to window for inline onclick handlers in dynamically generated HTML
window.resetProfit = resetProfit;
window.removePairProfit = removePairProfit;
window.resetExchangeProfit = resetExchangeProfit;
window.toggleBot = toggleBot;

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
                const prices = data.prices || {};
                for (const [symbol, orders] of Object.entries(data.orders)) {
                    const sellOrder = orders['sell'];
                    const buyOrder  = orders['buy'];
                    const currentPrice = prices[symbol];

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

                    // Grid viz — samo ako imamo i sell i buy nalog i trenutnu cijenu
                    if (sellOrder && buyOrder && currentPrice) {
                        const vizRow = document.createElement('tr');
                        vizRow.innerHTML = `<td colspan="6" style="padding:4px 8px 8px 8px;">${buildOrderGridViz(symbol, sellOrder, buyOrder, currentPrice)}</td>`;
                        ordersTable.appendChild(vizRow);
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
                            const ts = msg.timestamp ? new Date(msg.timestamp) : null;
                            const tsStr = ts ? `${String(ts.getDate()).padStart(2,'0')}.${String(ts.getMonth()+1).padStart(2,'0')}. ${String(ts.getHours()).padStart(2,'0')}:${String(ts.getMinutes()).padStart(2,'0')} ` : '';
                            li.innerHTML = `<small style="opacity:0.65">${tsStr}</small>${sym}: ${msg.message}`;
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
                            editBtn.dataset.running = running ? 'true' : 'false';
                        }
                    }
                }
            }

            if (data.account_info) {
                renderAccountInfo(data.account_info);
                if (typeof window._capitalRefreshHook === 'function') {
                    window._capitalRefreshHook(data.account_info);
                }
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
                  <thead><tr><th>Par</th><th class="text-end">Profit (USDC)</th><th class="text-end">Token Profit</th><th class="text-end" title="Vrijednost zadržanih tokena u trenutku kad su zarađeni (qty × cijena pri prodaji)">USDC ekv.</th><th class="text-end" title="Kripto qty × trenutna cijena (+ pozitivno = cijena rasla od zarade)">Kripto vrijednost</th><th></th></tr></thead>
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
            row.dataset.symbol = p.symbol;
            const running = window.currentTradeStatus[p.symbol];
            if (running) anyRunning = true;

            const currentPrice = window.priceCache ? (window.priceCache[p.symbol] || 0) : 0;
            const cryptoQty = Number(p.profit_crypto);
            const currentVal = cryptoQty * currentPrice;
            const usdcRealized = Number(p.profit_usdc);
            const usdcEquiv = Number(p.profit_usdc_equiv || 0);
            const hasCrypto = cryptoQty > 0;
            row.dataset.cryptoQty = cryptoQty;
            row.dataset.usdcEquiv = usdcEquiv;

            let cryptoValCell = `<td class="text-end text-muted" id="crypto-val-${p.pair_id}">—</td>`;
            if (hasCrypto && currentPrice > 0) {
                const diff = currentVal - usdcEquiv;
                const color = diff >= 0 ? 'text-success' : 'text-danger';
                const sign = diff >= 0 ? '+' : '';
                cryptoValCell = `<td class="text-end" id="crypto-val-${p.pair_id}">
                    <span class="fw-bold ${color}">${currentVal.toFixed(2)} $</span>
                    <div style="font-size:0.7rem;" class="${color}">(${sign}${diff.toFixed(2)} $ vs USDC)</div>
                </td>`;
            } else if (hasCrypto) {
                cryptoValCell = `<td class="text-end text-muted" style="font-size:0.75rem;" id="crypto-val-${p.pair_id}">čeka cijenu...</td>`;
            }

            const usdcEquivCell = usdcEquiv > 0
                ? `<td class="text-end text-info">${usdcEquiv.toFixed(4)} $</td>`
                : `<td class="text-end text-muted">—</td>`;

            row.innerHTML = `
                <td>${p.symbol}</td>
                <td id="profit-usdc-info-${p.pair_id}" class="text-end">${usdcRealized > 0 ? usdcRealized.toFixed(4) : '—'}</td>
                <td id="profit-crypto-info-${p.pair_id}" class="text-end">${cryptoQty > 0 ? cryptoQty.toFixed(6) : '—'}</td>
                ${usdcEquivCell}
                ${cryptoValCell}
                <td>
                    <button class="btn btn-xxs btn-secondary${running ? ' disabled' : ''}" style="padding:1px 4px;font-size:0.55rem;" onclick="resetProfit(${p.pair_id})">Reset</button>
                    <button class="btn btn-xxs btn-danger ms-1 remove-pair${running ? ' disabled' : ''}" style="padding:1px 4px;font-size:0.55rem;" onclick="removePairProfit(${p.pair_id})"><i class="bi bi-x-circle"></i></button>
                </td>`;
            tbody.appendChild(row);
            totalUsdc += usdcRealized;
            totalCrypto += cryptoQty;
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

function buildOrderGridViz(symbol, sellOrder, buyOrder, currentPrice) {
    const sellPrice = Number(sellOrder.price);
    const buyPrice  = Number(buyOrder.price);
    const cur       = Number(currentPrice);
    if (!sellPrice || !buyPrice || !cur) return '';

    const minP  = buyPrice  * 0.998;
    const maxP  = sellPrice * 1.002;
    const range = maxP - minP || 1;
    const BAR_W = 160;
    const px = (p) => Math.round(((p - minP) / range) * BAR_W);

    const sellPct = ((sellPrice - cur) / cur * 100).toFixed(2);
    const buyPct  = ((buyPrice  - cur) / cur * 100).toFixed(2);

    const line = (price, color, label, pct) => {
        const pos = px(price);
        return `<div style="display:flex;align-items:center;margin-bottom:3px;">
            <div style="width:78px;text-align:right;color:${color};font-size:0.72rem;margin-right:6px;">$${Number(price).toFixed(4)}</div>
            <div style="position:relative;width:${BAR_W}px;height:11px;background:#1a1d20;border-radius:2px;">
                <div style="position:absolute;left:${pos}px;top:0;width:2px;height:100%;background:${color};"></div>
            </div>
            <div style="margin-left:8px;color:${color};font-size:0.7rem;white-space:nowrap;">${label} ${pct}%</div>
        </div>`;
    };

    return `<div style="font-family:monospace;font-size:0.75rem;background:rgba(0,0,0,0.2);padding:6px 8px;border-radius:4px;">
        <div style="color:#6c757d;margin-bottom:4px;font-size:0.7rem;">⬥ ${symbol} grid</div>
        ${line(sellPrice, '#dc3545', '▲ SELL', '+' + sellPct)}
        ${line(cur,       '#0d6efd', '● NOW',  '')}
        ${line(buyPrice,  '#198754', '▼ BUY',  buyPct)}
    </div>`;
}

function renderOpenPositions(list) {
    const tbody = document.getElementById('open-positions-body');
    if (!tbody) return;

    // Ukupan broj parova u naslovu kartice
    const posHeader = document.querySelector('#open-positions-table')?.closest('.card')?.querySelector('.card-header');
    if (posHeader) {
        const badge = posHeader.querySelector('.pos-count-badge') || document.createElement('span');
        badge.className = 'pos-count-badge badge bg-light text-dark ms-2';
        const groupCount = new Set(list.map(p => `${p.symbol}|${p.exchange}`)).size;
        badge.textContent = `${groupCount} par${groupCount !== 1 ? 'a' : ''}`;
        if (!posHeader.querySelector('.pos-count-badge')) posHeader.appendChild(badge);
    }

    // Preimenuj zaglavlje drugog stupca u Qty
    const qtyHeader = document.querySelector('#open-positions-table thead th:nth-child(2)');
    if (qtyHeader) qtyHeader.textContent = 'Qty';
    const liveHeader = document.querySelector('#open-positions-table thead th:nth-child(3)');
    if (liveHeader) liveHeader.textContent = 'Live Price';
    const entryHeader = document.querySelector('#open-positions-table thead th:nth-child(4)');
    if (entryHeader) entryHeader.textContent = 'Entry Price';
    const costHeader = document.querySelector('#open-positions-table thead th:nth-child(5)');
    if (costHeader) costHeader.textContent = 'Cost';
    const valueHeader = document.querySelector('#open-positions-table thead th:nth-child(6)');
    if (valueHeader) valueHeader.textContent = 'Value';
    const pnlHeader = document.querySelector('#open-positions-table thead th:nth-child(7)');
    if (pnlHeader) pnlHeader.textContent = 'PnL';

    // capture expanded groups before re-render
    const expanded = new Set();
    tbody.querySelectorAll('tr.group-header').forEach(tr => {
        const key = tr.dataset.groupKey;
        const row = tbody.querySelector(`tr.${key}`);
        if (row && row.classList.contains('show')) expanded.add(key);
    });

    tbody.innerHTML = '';

    const grouped = {};
    let grandTotalInvestment = 0;
    let grandTotalNetPnl = 0;
    let grandTotalCurrentValue = 0;

    list.forEach(pos => {
        const key = `${pos.symbol}|${pos.exchange}`;
        if (!grouped[key]) grouped[key] = [];
        grouped[key].push(pos);
    });

    Object.entries(grouped).forEach(([key, positions]) => {
        const [symbol, exchange] = key.split('|');
        const groupClass = `pos-group-${symbol.replace(/[^a-zA-Z0-9]/g, '')}-${exchange}`;
        const totalQty = positions.reduce((s, p) => s + Number(p.quantity), 0);
        const totalInvestmentGroup = positions.reduce((s, p) => s + (Number(p.buy_price) * Number(p.quantity)), 0);
        const totalProfitGroup = positions.reduce((s, p) => s + (p.current_pnl > 0 ? p.current_pnl : 0), 0);
        const totalLossGroup = positions.reduce((s, p) => s + (p.current_pnl < 0 ? p.current_pnl : 0), 0);
        const netPnlGroup = totalProfitGroup + totalLossGroup;
        const avgBuyPrice = totalQty > 0 ? totalInvestmentGroup / totalQty : 0;
        const roiGroup = totalInvestmentGroup > 0 ? (netPnlGroup / totalInvestmentGroup) * 100 : 0;
        const profitMode = positions[0].profit_mode || 'usdc';
        const currentPrice = positions[0].current_price;
        const currentValue = currentPrice !== null ? totalQty * currentPrice : 0;
        const modes = [...new Set(positions.map(p => p.trading_mode))];
        const modeLabel = modes.length === 1 ? modes[0] : 'mixed';
        const isExpanded = expanded.has(groupClass);

        grandTotalInvestment += totalInvestmentGroup;
        grandTotalNetPnl += netPnlGroup;
        grandTotalCurrentValue += currentValue;

        const header = document.createElement('tr');
        header.className = 'table-secondary group-header';
        header.dataset.groupKey = groupClass;
        header.style.verticalAlign = 'top';
        header.innerHTML = `
            <td style="white-space: nowrap;">
                <div class="d-flex flex-column align-items-start">
                    <div class="d-flex align-items-center gap-2">
                        <div class="fw-bold text-primary" style="font-size: 1.15rem; line-height: 1; margin-bottom: 2px;">${symbol}</div>
                        <span class="badge bg-secondary" style="font-size: 0.65rem;">${positions.length} pos</span>
                    </div>
                    <div class="fw-bold text-uppercase" style="font-size: 0.75rem; line-height: 1; color: #ffc107;">${exchange}</div>
                    <div class="text-info mt-1 fw-bold" style="font-size: 0.6rem; letter-spacing: 0.5px;">PROFIT: ${profitMode.toUpperCase()}</div>
                </div>
            </td>
            <td class="text-end" style="white-space: nowrap;">
                <div class="d-flex flex-column align-items-end">
                    <div class="fw-bold text-danger" style="font-size: 1rem; line-height: 1;">${totalQty.toFixed(6)}</div>
                </div>
            </td>
            <td class="text-end" style="white-space: nowrap;">
                <div class="d-flex flex-column align-items-end">
                    <div class="fw-bold text-primary" style="font-size: 0.9rem; line-height: 1;">$${currentPrice !== null ? Number(currentPrice).toFixed(4) : 'N/A'}</div>
                </div>
            </td>
            <td class="text-end" style="white-space: nowrap;">
                <div class="d-flex flex-column align-items-end">
                    <div class="fw-bold text-warning" style="font-size: 0.9rem; line-height: 1;">$${avgBuyPrice.toFixed(4)}</div>
                </div>
            </td>
            <td class="text-end" style="white-space: nowrap;">
                <div class="d-flex flex-column align-items-end">
                    <div class="fw-bold text-info" style="font-size: 0.9rem; line-height: 1;">$${totalInvestmentGroup.toFixed(2)}</div>
                    <div class="text-muted mt-1" style="font-size: 0.55rem; letter-spacing: 0.5px;">COST</div>
                </div>
            </td>
            <td class="text-end" style="white-space: nowrap;">
                <div class="d-flex flex-column align-items-end">
                    <div class="fw-bold text-primary" style="font-size: 1rem; line-height: 1;">$${currentValue.toFixed(2)}</div>
                    <div class="text-muted mt-1" style="font-size: 0.55rem; letter-spacing: 0.5px;">CURRENT</div>
                </div>
            </td>
            <td class="text-end" style="white-space: nowrap;">
                <div class="d-flex flex-column align-items-end">
                    <div class="fw-bold ${netPnlGroup >= 0 ? 'text-success' : 'text-danger'}" style="font-size: 1rem; line-height: 1;">${netPnlGroup >= 0 ? '+' : ''}${netPnlGroup.toFixed(2)}</div>
                    <div class="badge ${roiGroup >= 0 ? 'bg-success' : 'bg-danger'} mt-1" style="font-size: 0.7rem;">${roiGroup >= 0 ? '▲' : '▼'} ${Math.abs(roiGroup).toFixed(2)}%</div>
                </div>
            </td>
            <td class="text-end" style="width: 1%; white-space: nowrap;">
                ${positions.length > 1 ? `<button class="btn btn-xxs btn-light toggle-pos" data-target="${groupClass}"><i class="bi ${isExpanded ? 'bi-chevron-up' : 'bi-chevron-down'}"></i></button>` : ''}
                <button class="btn btn-xxs btn-danger ms-1 remove-pos" data-symbol="${symbol}" data-exchange="${exchange}" data-mode="${modeLabel}"><i class="bi bi-x-circle"></i></button>
            </td>`;
        tbody.appendChild(header);

        if (positions.length > 1) {
            positions.forEach(p => {
                const pnl = typeof p.current_pnl === 'number' ? p.current_pnl : null;
                const investment = Number(p.quantity) * Number(p.buy_price);
                const curVal = p.current_price !== null ? Number(p.quantity) * p.current_price : 0;
                const pnlPct = pnl !== null && investment > 0 ? (pnl / investment) * 100 : 0;

                const row = document.createElement('tr');
                row.className = `collapse ${groupClass}${isExpanded ? ' show' : ''}`;
                row.innerHTML = `
                <td><div class="ps-4 text-muted" style="font-size: 0.65rem; letter-spacing: 1px;">ENTRY</div></td>
                    <td class="text-end">
                        <div class="d-flex flex-column align-items-end">
                            <div class="fw-bold text-danger" style="font-size: 0.85rem; line-height: 1;">${Number(p.quantity).toFixed(6)}</div>
                        </div>
                    </td>
                    <td class="text-end"><div class="fw-bold text-primary" style="font-size: 0.8rem;">$${p.current_price !== null ? Number(p.current_price).toFixed(4) : 'N/A'}</div></td>
                    <td class="text-end">
                        <div class="d-flex flex-column align-items-end">
                            <div class="fw-bold text-warning" style="font-size: 0.85rem; line-height: 1;">$${Number(p.buy_price).toFixed(4)}</div>
                        </div>
                    </td>
                    <td class="text-end">
                        <div class="d-flex flex-column align-items-end">
                            <div class="fw-bold text-info" style="font-size: 0.85rem; line-height: 1;">$${investment.toFixed(2)}</div>
                        </div>
                    </td>
                    <td class="text-end">
                        <div class="d-flex flex-column align-items-end">
                            <div class="fw-bold text-primary" style="font-size: 0.85rem; line-height: 1;">$${curVal.toFixed(2)}</div>
                        </div>
                    </td>
                    <td class="text-end">
                        <div class="d-flex flex-column align-items-end">
                            <div class="small fw-bold ${pnl >= 0 ? 'text-success' : 'text-danger'}" style="line-height: 1;">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}</div>
                            <div class="text-muted mt-1" style="font-size: 0.6rem; line-height: 1;">${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%</div>
                        </div>
                    </td>
                    <td></td>`;
                tbody.appendChild(row);
            });
        }
    });

    if (list.length > 0) {
        const grandTotalRoi = grandTotalInvestment > 0 ? (grandTotalNetPnl / grandTotalInvestment) * 100 : 0;
        const footer = document.createElement('tr');
        footer.className = 'table-dark fw-bold border-top-2';
        footer.innerHTML = `
            <td class="text-center text-uppercase small">Portfolio Total:</td>
            <td colspan="3"></td>
            <td class="text-end" style="color: #0dcaf0; white-space: nowrap;">$${grandTotalInvestment.toFixed(2)}</td>
            <td class="text-end" style="color: #0d6efd; white-space: nowrap;">$${grandTotalCurrentValue.toFixed(2)}</td>
            <td class="text-end ${grandTotalNetPnl >= 0 ? 'text-success' : 'text-danger'}">
                ${grandTotalNetPnl >= 0 ? '+' : ''}${grandTotalNetPnl.toFixed(2)}
                <span class="badge ${grandTotalRoi >= 0 ? 'bg-success' : 'bg-danger'} ms-1">${grandTotalRoi >= 0 ? '+' : ''}${grandTotalRoi.toFixed(2)}%</span>
            </td>
            <td></td>`;
        tbody.appendChild(footer);
    }


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

export function refreshCryptoPrices(priceCache) {
    document.querySelectorAll('tr[data-crypto-qty]').forEach(row => {
        const cryptoQty = parseFloat(row.dataset.cryptoQty);
        if (!(cryptoQty > 0)) return;
        const pairId = row.dataset.pairId;
        const symbol = row.dataset.symbol;
        const usdcEquiv = parseFloat(row.dataset.usdcEquiv) || 0;
        const cell = document.getElementById(`crypto-val-${pairId}`);
        if (!cell) return;
        const price = priceCache[symbol];
        if (!price || price === 'N/A' || typeof price !== 'number') {
            cell.className = 'text-end text-muted';
            cell.style.fontSize = '0.75rem';
            cell.innerHTML = 'čeka cijenu...';
            return;
        }
        const currentVal = cryptoQty * price;
        const diff = currentVal - usdcEquiv;
        const color = diff >= 0 ? 'text-success' : 'text-danger';
        const sign = diff >= 0 ? '+' : '';
        cell.className = 'text-end';
        cell.style.fontSize = '';
        cell.innerHTML = `<span class="fw-bold ${color}">${currentVal.toFixed(2)} $</span>
            <div style="font-size:0.7rem;" class="${color}">(${sign}${diff.toFixed(2)} $ vs USDC)</div>`;
    });
}
