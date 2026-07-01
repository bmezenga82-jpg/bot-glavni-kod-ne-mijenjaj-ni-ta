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

let _lastBacktestMeta = null; // pamtimo parametre za save
let _allFolders = [];        // flat lista svih mapa za dropdownove

export function runBacktest() {
    const form = document.getElementById('backtest-form');
    const showLog = document.getElementById('show_trade_log')?.checked;
    const resultsEl = document.getElementById('backtest-results');

    // Kolektirati checkboxove, izostaviti primarni par
    const primary = document.getElementById('symbol')?.value;
    const compareSymbols = [...document.querySelectorAll('.compare-pair-cb:checked')]
        .map(cb => cb.value)
        .filter(s => s !== primary)
        .join(',');

    // FormData se gradi NAKON što imamo compare listu
    const formData = new FormData(form);
    formData.set('compare_symbols', compareSymbols);

    resultsEl.textContent = 'Učitavanje...';

    // Pamtimo meta za save
    _lastBacktestMeta = {
        symbol: formData.get('symbol'),
        exchange: formData.get('exchange'),
        buy_pct: parseFloat(formData.get('buy_percentage')),
        sell_pct: parseFloat(formData.get('sell_percentage')),
        amount: parseFloat(formData.get('amount')),
        total_capital: parseFloat(formData.get('total_capital')),
        timeframe: formData.get('timeframe'),
        start_date: formData.get('start_date'),
        end_date: formData.get('end_date'),
        profit_mode: formData.get('profit_mode'),
    };

    fetch('/backtest', { method: 'POST', body: formData })
    .then(response => response.json())
    .then(data => {
        if (!data.results) {
            resultsEl.textContent = 'No results available.';
            return;
        }

        const entries = Object.entries(data.results);
        let resultText = '';

        // ── Usporedna tablica (samo kad ima više parova) ──────
        if (entries.length > 1) {
            const pad = (s, w) => String(s).padEnd(w);
            resultText += `════ USPOREDBA PAROVA ════════════════════════════\n`;
            resultText += `${pad('Par', 14)} ${pad('P&L ukupno', 15)} ${pad('God. ROI', 12)} Trades  Otvoreno\n`;
            resultText += `──────────────────────────────────────────────────\n`;
            for (const [sym, r] of entries) {
                const pnl  = r.total_pnl != null
                    ? `${r.total_pnl >= 0 ? '+' : ''}${r.total_pnl.toFixed(2)} USDC`
                    : 'N/A';
                const roi  = r.annualized_roi != null
                    ? `${r.annualized_roi >= 0 ? '+' : ''}${r.annualized_roi.toFixed(1)}%/god`
                    : 'N/A';
                resultText += `${pad(sym, 14)} ${pad(pnl, 15)} ${pad(roi, 12)} ${pad(r.trade_count ?? '-', 8)} ${r.open_positions ?? '-'}\n`;
            }
            resultText += `══════════════════════════════════════════════════\n\n`;
        }

        // ── Detalji po paru ───────────────────────────────────
        for (const [symbol, result] of entries) {
            resultText += `═══════════════════════════════════════\n`;
            resultText += `Symbol:              ${symbol}\n`;
            if (result.total_capital != null)
                resultText += `Total Capital:       ${result.total_capital.toFixed(2)} USDC\n`;
            if (result.candles)
                resultText += `Period analysed:     ${result.candles} candles (${result.timeframe})\n`;
            if (result.last_price != null)
                resultText += `Last price:          ${result.last_price} USDC\n`;
            resultText += `\n`;
            resultText += `── Realized (closed trades) ────────────\n`;
            resultText += `Trades completed:    ${result.trade_count ?? 'N/A'}\n`;
            resultText += `Realized Profit:     ${result.net_profit.toFixed(4)} USDC`;
            if (result.roi_pct != null) resultText += ` (${result.roi_pct.toFixed(2)}% ROI)`;
            resultText += '\n\n';
            resultText += `── Open positions (end of period) ──────\n`;
            if (result.open_positions != null) {
                resultText += `Open lots:           ${result.open_positions}\n`;
                resultText += `Capital in open:     ${(result.total_invested_open ?? 0).toFixed(2)} USDC\n`;
                if (result.avg_buy_price > 0) {
                    resultText += `Avg. buy price:      ${result.avg_buy_price.toFixed(4)} USDC\n`;
                    resultText += `Current price:       ${(result.last_price ?? 0).toFixed(4)} USDC\n`;
                    const bePct = result.breakeven_pct ?? 0;
                    if (bePct > 0)
                        resultText += `Break-even:          potreban rast +${bePct.toFixed(1)}%\n`;
                    else
                        resultText += `Break-even:          već pokriven ✓ (${Math.abs(bePct).toFixed(1)}% iznad avg)\n`;
                }
                const unreal = result.unrealized_pnl ?? 0;
                resultText += `Unrealized P&L:      ${unreal.toFixed(4)} USDC`;
                resultText += unreal >= 0 ? ' ✓\n' : ' ⚠\n';
            }
            if (result.profit_mode === 'crypto') {
                resultText += `\n── Crypto Profit ───────────────────────\n`;
                resultText += `Prikupljeno:         ${result.crypto_profit_qty} crypto\n`;
                resultText += `Vrijednost sad:      ${result.crypto_value_usdc >= 0 ? '+' : ''}${result.crypto_value_usdc.toFixed(4)} USDC`;
                resultText += ` (po ${result.last_price} USDC)\n`;
                resultText += `USDC ekvivalent:     ${result.usdc_equivalent >= 0 ? '+' : ''}${result.usdc_equivalent.toFixed(4)} USDC`;
                resultText += ` (da je USDC mod)\n`;
                const diff = result.crypto_value_usdc - result.usdc_equivalent;
                resultText += `Razlika:             ${diff >= 0 ? '+' : ''}${diff.toFixed(4)} USDC`;
                resultText += diff >= 0 ? ' ✓ (crypto isplativije)\n' : ' ⚠ (cijena pala, USDC mod bi bio bolji)\n';
                // Break-even kalkulator
                if (result.crypto_profit_qty > 0 && result.usdc_equivalent > 0 && result.last_price > 0) {
                    const breakEven = result.usdc_equivalent / result.crypto_profit_qty;
                    const breakEvenPct = ((breakEven / result.last_price) - 1) * 100;
                    resultText += `Break-even cijena:   ${breakEven.toFixed(4)} USDC/token`;
                    if (breakEvenPct > 0)
                        resultText += ` (potreban rast +${breakEvenPct.toFixed(1)}%)\n`;
                    else
                        resultText += ` (već pokriveno! ${breakEvenPct.toFixed(1)}%)\n`;
                }
            }

            resultText += `\n── UKUPNO ──────────────────────────────\n`;
            if (result.profit_mode === 'crypto') {
                const total = result.crypto_value_usdc + (result.unrealized_pnl ?? 0);
                resultText += `Total P&L (crypto):  ${total >= 0 ? '+' : ''}${total.toFixed(4)} USDC\n`;
            } else if (result.total_pnl != null) {
                const total = result.total_pnl;
                resultText += `Total P&L:           ${total.toFixed(4)} USDC`;
                if (result.total_roi_pct != null) resultText += ` (${result.total_roi_pct.toFixed(2)}% ROI)`;
                resultText += total >= 0 ? ' ✓\n' : ' ⚠\n';
            }
            if (result.annualized_roi != null && result.period_days != null) {
                resultText += `Godišnji ROI:        ${result.annualized_roi >= 0 ? '+' : ''}${result.annualized_roi.toFixed(2)}% / god`;
                resultText += ` (za ${result.period_days} dana)\n`;
            }
            resultText += `═══════════════════════════════════════\n`;

            // Pregled po mjesecima
            if (result.monthly_breakdown) {
                const months = Object.entries(result.monthly_breakdown);
                if (months.length > 0) {
                    resultText += `\n── Pregled po mjesecima ────────────────\n`;
                    resultText += `Mj.        Profit (USDC)    Trades\n`;
                    resultText += `────────────────────────────────────────\n`;
                    let mTotal = 0;
                    months.forEach(([m, d]) => {
                        const p = d.profit;
                        mTotal += p;
                        const pStr = (p >= 0 ? '+' : '') + p.toFixed(2);
                        resultText += `${m}   ${pStr.padEnd(16)} ${d.trades}\n`;
                    });
                    resultText += `────────────────────────────────────────\n`;
                    resultText += `UKUPNO     ${((mTotal >= 0 ? '+' : '') + mTotal.toFixed(2)).padEnd(16)}\n`;
                }
            }

            // trade log — samo ako je checkbox uključen
            if (showLog && result.trade_log && result.trade_log.length) {
                resultText += `\nTrade Log (${result.trade_log.length} entries):\n`;
                result.trade_log.forEach(log => resultText += `  ${log}\n`);
            } else if (result.trade_log) {
                resultText += `[Trade log: ${result.trade_log.length} unosa — uključi checkbox za prikaz]\n`;
            }
            resultText += '\n';
        }

        resultsEl.textContent = resultText;

        // Pokaži sekciju za spremi (za prvi par u rezultatima)
        const firstResult = Object.values(data.results)[0];
        if (firstResult && _lastBacktestMeta) {
            _lastBacktestMeta.net_profit = firstResult.net_profit;
            _lastBacktestMeta.total_pnl = firstResult.total_pnl;
            _lastBacktestMeta.roi_pct = firstResult.roi_pct;
            _lastBacktestMeta.annualized_roi = firstResult.annualized_roi;
            _lastBacktestMeta.trade_count = firstResult.trade_count;
            _lastBacktestMeta.open_positions = firstResult.open_positions;
            _lastBacktestMeta.period_days = firstResult.period_days;
        }
        document.getElementById('save-test-section')?.classList.remove('d-none');
    })
    .catch(error => {
        resultsEl.textContent = 'Error running backtest: ' + error;
    });
}

export function saveBacktest() {
    if (!_lastBacktestMeta) return;
    const nameEl = document.getElementById('save-test-name');
    const msgEl = document.getElementById('save-test-msg');
    const folderEl = document.getElementById('save-test-folder');
    const name = nameEl?.value.trim() || `${_lastBacktestMeta.symbol} ${_lastBacktestMeta.buy_pct}/${_lastBacktestMeta.sell_pct}%`;
    const folder_id = folderEl?.value ? parseInt(folderEl.value) : null;

    fetch('/api/backtest/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ..._lastBacktestMeta, name, folder_id }),
    })
    .then(r => r.json())
    .then(() => {
        if (msgEl) { msgEl.textContent = '✓ Sačuvano'; msgEl.className = 'mt-1 text-success small'; msgEl.classList.remove('d-none'); }
        if (nameEl) nameEl.value = '';
        loadSavedTests();
        setTimeout(() => msgEl?.classList.add('d-none'), 2000);
    })
    .catch(() => {
        if (msgEl) { msgEl.textContent = 'Greška pri snimanju'; msgEl.className = 'mt-1 text-danger small'; msgEl.classList.remove('d-none'); }
    });
}

function _flattenFolders(folders, indent = 0) {
    const result = [];
    for (const f of folders) {
        result.push({ id: f.id, name: f.name, indent });
        if (f.children?.length) result.push(..._flattenFolders(f.children, indent + 1));
    }
    return result;
}

function _renderTestRow(t, indent = 0) {
    const profit = t.net_profit ?? 0;
    const safeName = t.name.replace(/'/g, "\\'");
    return `
    <div class="d-flex align-items-center gap-2 py-1 border-bottom" style="font-size:0.8rem; padding-left:${8 + indent * 16}px;">
        <input type="checkbox" class="saved-test-cb" value="${t.id}" style="flex-shrink:0;">
        <span class="flex-grow-1 text-truncate" title="${t.name}">
            <strong>${t.name}</strong>
            <span class="text-muted ms-1">${t.symbol} ${t.buy_pct}/${t.sell_pct}%</span>
        </span>
        <span class="${profit >= 0 ? 'text-success' : 'text-danger'}" style="white-space:nowrap;">
            ${profit >= 0 ? '+' : ''}${profit.toFixed(2)}
        </span>
        <button class="btn btn-xxs btn-outline-primary" style="padding:1px 5px;font-size:0.7rem;" onclick="openTest(${t.id})" title="Otvori">▶</button>
        <button class="btn btn-xxs btn-outline-secondary" style="padding:1px 5px;font-size:0.7rem;" onclick="renameTest(${t.id},'${safeName}')" title="Preimenuj">✎</button>
        <button class="btn btn-xxs btn-outline-warning" style="padding:1px 5px;font-size:0.7rem;" onclick="moveTest(${t.id})" title="Premjesti">↗</button>
        <button class="btn btn-xxs btn-outline-danger" style="padding:1px 5px;font-size:0.7rem;" onclick="deleteTest(${t.id})" title="Obriši">✕</button>
    </div>`;
}

function _renderFolderTree(folders, tests, indent = 0) {
    let html = '';
    for (const f of folders) {
        const safeName = f.name.replace(/'/g, "\\'");
        const folderTests = tests.filter(t => t.folder_id === f.id);
        html += `
        <div style="padding-left:${indent * 16}px;">
            <div class="d-flex align-items-center gap-1 py-1" style="font-size:0.82rem; cursor:pointer;"
                 onclick="this.nextElementSibling.classList.toggle('d-none')">
                <span class="text-warning">📁</span>
                <strong class="flex-grow-1">${f.name}</strong>
                <button class="btn btn-xxs btn-outline-secondary" style="padding:1px 5px;font-size:0.7rem;"
                    onclick="event.stopPropagation();renameFolder(${f.id},'${safeName}')">✎</button>
                <button class="btn btn-xxs btn-outline-success" style="padding:1px 5px;font-size:0.7rem;"
                    onclick="event.stopPropagation();createFolder(${f.id})">+</button>
                <button class="btn btn-xxs btn-outline-danger" style="padding:1px 5px;font-size:0.7rem;"
                    onclick="event.stopPropagation();deleteFolder(${f.id})">✕</button>
            </div>
            <div>
                ${f.children?.length ? _renderFolderTree(f.children, tests, indent + 1) : ''}
                ${folderTests.map(t => _renderTestRow(t, indent + 1)).join('')}
                ${!f.children?.length && !folderTests.length ? `<div class="text-muted small ps-3 py-1">prazno</div>` : ''}
            </div>
        </div>`;
    }
    return html;
}

export function loadSavedTests() {
    Promise.all([
        fetch('/api/backtest/folders').then(r => r.json()),
        fetch('/api/backtest/saved').then(r => r.json()),
    ]).then(([folders, tests]) => {
        window._savedTestsData = tests;
        _allFolders = _flattenFolders(folders);

        // Popuni dropdown za save
        const folderSel = document.getElementById('save-test-folder');
        if (folderSel) {
            folderSel.innerHTML = '<option value="">— bez mape —</option>' +
                _allFolders.map(f => `<option value="${f.id}">${'&nbsp;&nbsp;'.repeat(f.indent)}${f.name}</option>`).join('');
        }

        const body = document.getElementById('saved-tests-body');
        if (!body) return;

        const rootTests = tests.filter(t => !t.folder_id);
        let html = _renderFolderTree(folders, tests);
        if (rootTests.length) {
            html += rootTests.map(t => _renderTestRow(t, 0)).join('');
        }
        if (!html) html = '<div class="text-muted small text-center py-2">Nema sačuvanih testova.</div>';
        body.innerHTML = html;
    })
    .catch(() => {});
}

export function createFolder(parentId = null) {
    const name = prompt('Naziv mape:');
    if (!name?.trim()) return;
    fetch('/api/backtest/folders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), parent_id: parentId || null }),
    }).then(() => loadSavedTests());
}

export function renameFolder(id, currentName) {
    const newName = prompt('Novi naziv:', currentName);
    if (!newName || newName === currentName) return;
    fetch(`/api/backtest/folders/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName }),
    }).then(() => loadSavedTests());
}

export function deleteFolder(id) {
    if (!confirm('Obrisati mapu? Testovi ostaju, premještaju se u root.')) return;
    fetch(`/api/backtest/folders/${id}`, { method: 'DELETE' })
    .then(() => loadSavedTests());
}

export function moveTest(id) {
    const opts = [{ id: null, label: '— bez mape (root) —' }]
        .concat(_allFolders.map(f => ({ id: f.id, label: ' '.repeat(f.indent * 2) + f.name })));
    const choice = prompt(
        'Premjesti u mapu:\n' + opts.map((o, i) => `${i}: ${o.label}`).join('\n') + '\n\nUnesi broj:'
    );
    if (choice === null || choice === '') return;
    const idx = parseInt(choice);
    if (isNaN(idx) || idx < 0 || idx >= opts.length) return;
    fetch(`/api/backtest/saved/${id}/move`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder_id: opts[idx].id }),
    }).then(() => loadSavedTests());
}

export function deleteTest(id) {
    if (!confirm('Obrisati ovaj test?')) return;
    fetch(`/api/backtest/saved/${id}`, { method: 'DELETE' })
    .then(() => loadSavedTests());
}

export function renameTest(id, currentName) {
    const newName = prompt('Novi naziv:', currentName);
    if (!newName || newName === currentName) return;
    fetch(`/api/backtest/saved/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName }),
    }).then(() => loadSavedTests());
}

export function openTest(id) {
    const all = window._savedTestsData || [];
    const t = all.find(x => x.id === id);
    if (!t) return;

    // Popuni formu sa sačuvanim parametrima
    const set = (sel, val) => { const el = document.getElementById(sel); if (el) el.value = val; };
    set('symbol', t.symbol);
    set('exchange', t.exchange);
    set('buy_percentage', t.buy_pct);
    set('sell_percentage', t.sell_pct);
    set('amount', t.amount);
    set('total_capital', t.total_capital);
    set('timeframe', t.timeframe || '1h');
    set('start_date', t.start_date || '');
    set('end_date', t.end_date || '');
    set('profit_mode', t.profit_mode || 'usdc');

    // Trigger recalc kalkulatora
    if (typeof updateCapitalCalc === 'function') updateCapitalCalc();

    // Postavi naziv za save na isti naziv
    const nameEl = document.getElementById('save-test-name');
    if (nameEl) nameEl.value = t.name;

    // Pokreni backtest
    if (typeof window.runBacktest === 'function') window.runBacktest();
}

export function compareSelected() {
    const selected = [...document.querySelectorAll('.saved-test-cb:checked')].map(cb => parseInt(cb.value));
    if (selected.length < 2) {
        alert('Odaberi najmanje 2 testa za usporedbu.');
        return;
    }
    const all = window._savedTestsData || [];
    const tests = all.filter(t => selected.includes(t.id));
    const resultsEl = document.getElementById('backtest-results');
    if (!resultsEl) return;

    const pad = (s, w) => String(s ?? '—').padEnd(w);
    let text = `════ USPOREDBA SAČUVANIH TESTOVA ══════════════════════\n`;
    text += `${pad('Naziv', 22)} ${pad('Par', 12)} ${pad('Buy/Sell', 10)} ${pad('Realizirano', 14)} ${pad('Uk. P&L', 12)} ${pad('God.ROI', 9)} Trades\n`;
    text += `───────────────────────────────────────────────────────────────────\n`;

    const sorted = [...tests].sort((a, b) => (b.net_profit ?? 0) - (a.net_profit ?? 0));
    sorted.forEach((t, i) => {
        const real = t.net_profit ?? 0;
        const pnl  = t.total_pnl ?? 0;
        const roi  = t.annualized_roi;
        text += `${pad((i+1)+'. '+t.name, 22)} ${pad(t.symbol, 12)} ${pad(t.buy_pct+'/'+t.sell_pct+'%', 10)} `;
        text += `${pad((real >= 0 ? '+' : '') + real.toFixed(2) + ' $', 14)} `;
        text += `${pad((pnl  >= 0 ? '+' : '') + pnl.toFixed(2)  + ' $', 12)} `;
        text += `${pad(roi != null ? (roi >= 0 ? '+' : '') + roi.toFixed(1) + '%' : '—', 9)} ${t.trade_count ?? '—'}\n`;
        text += `${pad('', 22)} ${t.start_date||'?'} → ${t.end_date||'?'}  |  kapital: ${t.total_capital} USDC  |  iznos: ${t.amount} USDC\n\n`;
    });
    text += `════════════════════════════════════════════════════════════════════\n`;
    resultsEl.textContent = text;
}

export function runOptimize() {
    const form = document.getElementById('backtest-form');
    const resultsEl = document.getElementById('backtest-results');

    const startDate = document.getElementById('start_date')?.value;
    const endDate   = document.getElementById('end_date')?.value;
    if (!startDate || !endDate) {
        resultsEl.textContent =
            '⚠ Molim postavi Start Date i End Date prije optimizacije.\n' +
            'Bez datuma optimizer koristi period od 2023-01-01 do danas (~3 godine),\n' +
            'što može trajati nekoliko minuta.';
        return;
    }

    const formData = new FormData(form);
    resultsEl.textContent = 'Optimizing... (ovo može potrajati 30-60 sekundi za duži period)';
    fetch('/optimize', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            resultsEl.textContent = 'Greška: ' + data.error;
            return;
        }
        if (!data.top_combos || !data.top_combos.length) {
            resultsEl.textContent = 'Nema rezultata.';
            return;
        }
        const optimizeBy = document.getElementById('optimize_by')?.value || 'realized';
        const m = data.meta || {};
        const coverageMode = m.coverage_mode || false;
        const primaryList   = optimizeBy === 'realized' ? (data.top_by_realized || []) : data.top_combos;
        const secondaryList = optimizeBy === 'realized' ? data.top_combos : (data.top_by_realized || []);
        const primaryLabel   = optimizeBy === 'realized'
            ? 'TOP 5 po REALIZIRANOM PROFITU (samo zatvoreni ciklusi)\n  ✓ Stabilan — ne ovisi o smjeru tržišta'
            : 'TOP 5 po UKUPNOM P&L (realized + unrealized)\n  ⚠ Varira s tržištem — u bull marketu izgleda bolje';
        const secondaryLabel = optimizeBy === 'realized'
            ? 'TOP 5 po UKUPNOM P&L (realized + unrealized)\n  ⚠ Varira s tržištem — informativno'
            : 'TOP 5 po REALIZIRANOM PROFITU (samo zatvoreni ciklusi)\n  ✓ Stabilan pokazatelj — informativno';

        let text = `═══ TOP 5 KOMBINACIJA ═══\n`;
        if (m.symbol) {
            text += `Valuta:    ${m.symbol} na ${m.exchange}\n`;
            const sd = m.start_date || '2023-01-01 (default)';
            const ed = m.end_date   || 'danas (default)';
            text += `Period:    ${sd} → ${ed} (${m.timeframe})\n`;
            text += `Kapital:   ${m.total_capital} USDC\n`;
            if (m.combinations_tested) {
                const stepNote = m.step_used > 0.2 ? ` (korak povećan na ${m.step_used}% — previše kombinacija)` : '';
                text += `Kombina.:  ${m.combinations_tested} testirano, korak ${m.step_used}%${stepNote}\n`;
            }
            if (coverageMode) {
                text += `Način:     FIKSIRANA POKRIVENOST PADA ${m.target_coverage_pct}%\n`;
                text += `           → Svaki buy% dobiva amount koji pokriva ${m.target_coverage_pct}% pada\n`;
                text += `           → Profit je direktno usporediv — isti rizik, različiti iznosi\n`;
            } else if (m.normalize_amount) {
                text += `Iznos:     SKALIRAN proporcionalno buy%  |  referenca ${m.amount} USDC pri ${m.buy_pct_ref}%\n`;
            } else {
                text += `Per-trade: ${m.amount} USDC (fiksno)\n`;
            }
        }
        const fmtCombo = (c, i) => {
            const amtStr = c.amount != null ? ` | Iznos: ${c.amount} USDC` : '';
            const covStr = c.coverage_pct != null ? ` | Pokrivenost: ${c.coverage_pct}%` : '';
            let s = `#${i + 1}  Buy: ${c.buy_pct}%  /  Sell: ${c.sell_pct}%${amtStr}${covStr}\n`;
            s += `     Realizirano:     ${c.net_profit >= 0 ? '+' : ''}${c.net_profit.toFixed(4)} USDC\n`;
            s += `     Nerealizirano:   ${c.unrealized_pnl >= 0 ? '+' : ''}${c.unrealized_pnl.toFixed(4)} USDC\n`;
            s += `     Ukupni P&L:      ${c.total_pnl >= 0 ? '+' : ''}${c.total_pnl.toFixed(4)} USDC (${c.roi_pct.toFixed(2)}% ROI)\n`;
            if (c.annualized_roi != null)
                s += `     Godišnji ROI:    ${c.annualized_roi >= 0 ? '+' : ''}${c.annualized_roi.toFixed(2)}% / god\n`;
            const invested = c.total_invested_open != null ? c.total_invested_open.toFixed(2) : (c.open_positions * c.amount).toFixed(2);
            s += `     Trades: ${c.trade_count}   |   Otvorenih: ${c.open_positions} pos = ${invested} USDC uloženo\n`;
            return s;
        };

        const fmtConsistentCombo = (c, i) => {
            const label = c.consistency_label || '';
            let s = `#${i + 1}  ${label}  |  Buy: ${c.buy_pct}%  /  Sell: ${c.sell_pct}%\n`;
            s += `     Realizirano:  ${c.net_profit >= 0 ? '+' : ''}${c.net_profit.toFixed(4)} USDC`;
            s += `   |  Ukupni P&L: ${c.total_pnl >= 0 ? '+' : ''}${c.total_pnl.toFixed(4)} USDC`;
            if (c.annualized_roi != null)
                s += `   |  ${c.annualized_roi >= 0 ? '+' : ''}${c.annualized_roi.toFixed(2)}% god\n`;
            else
                s += '\n';
            return s;
        };

        text += '━'.repeat(50) + '\n';
        text += `  ${primaryLabel}\n`;
        text += '━'.repeat(50) + '\n\n';
        primaryList.forEach((c, i) => { text += fmtCombo(c, i) + '\n'; });

        text += '━'.repeat(50) + '\n';
        text += `  ${secondaryLabel}\n`;
        text += '━'.repeat(50) + '\n\n';
        secondaryList.forEach((c, i) => { text += fmtCombo(c, i) + '\n'; });

        const consistentResults = m.consistent_results;
        if (m.consistent && consistentResults && consistentResults.length) {
            text += '━'.repeat(50) + '\n';
            text += '  KONZISTENTNO TESTIRANJE — 3 pod-perioda\n';
            text += '  ★★★ = robustno u svim periodima, ★☆☆ = samo 1/3\n';
            text += '  Sortirano: više zvjezdica > veći profit\n';
            text += '━'.repeat(50) + '\n\n';
            consistentResults.forEach((c, i) => { text += fmtConsistentCombo(c, i) + '\n'; });
        }

        text += '═'.repeat(51) + '\n';
        resultsEl.textContent = text;
    })
    .catch(error => {
        resultsEl.textContent = 'Greška: ' + error;
    });
}
