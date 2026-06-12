// portfolio.js — upravljanje portfolijima i rebalancing preporukama

let _portfolios = [];       // [{id, name, threshold_pct}]
let _prices = {};           // {SYMBOL: price_usd}
let _activePortfolioId = null;
let _csvPortfolioId = null;
let _addTokenPortfolioId = null;
let _selectedPortfolioIds = new Set(); // filter za overview

const fmt2 = n => Number(n).toLocaleString('hr-HR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmt4 = n => Number(n).toLocaleString('hr-HR', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
const fmtPct = n => (n >= 0 ? '+' : '') + Number(n).toFixed(2) + '%';

// ── Util ─────────────────────────────────────────────────────────────────────

function getModal(id) {
    return bootstrap.Modal.getOrCreateInstance(document.getElementById(id));
}

function showToast(msg, type = 'success') {
    const el = document.createElement('div');
    el.className = `alert alert-${type} position-fixed bottom-0 end-0 m-3 shadow`;
    el.style.zIndex = 9999;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
}

// ── CMC API ključ ─────────────────────────────────────────────────────────────

async function loadCmcKey() {
    try {
        const r = await fetch('/api/cmc_key');
        const d = await r.json();
        const el = document.getElementById('cmc-api-key-input');
        if (el && d.api_key) el.value = d.api_key;
    } catch {}
}

async function saveCmcKey() {
    const key = document.getElementById('cmc-api-key-input')?.value.trim() || '';
    const msg = document.getElementById('cmc-save-msg');
    try {
        await fetch('/api/cmc_key', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: key })
        });
        if (msg) { msg.textContent = 'Spremljeno!'; msg.className = 'small text-success'; msg.style.display = ''; }
        setTimeout(() => { if (msg) msg.style.display = 'none'; }, 3000);
    } catch {
        if (msg) { msg.textContent = 'Greška!'; msg.className = 'small text-danger'; msg.style.display = ''; }
    }
}

// ── Dohvati cijene za sve simbole ────────────────────────────────────────────

async function fetchPrices(symbols) {
    if (!symbols.length) return {};
    const unique = [...new Set(symbols)];
    try {
        const r = await fetch(`/api/portfolio/prices?symbols=${unique.join(',')}`);
        const d = await r.json();
        if (d.error) { showToast('CMC: ' + d.error, 'danger'); return {}; }
        return d;
    } catch { return {}; }
}

// ── Dohvati sve portfolije ────────────────────────────────────────────────────

async function loadPortfolios() {
    const r = await fetch('/api/portfolio/list');
    _portfolios = await r.json();
    // Sve označene po defaultu
    _selectedPortfolioIds = new Set(_portfolios.map(p => p.id));
    renderTabs();
    renderOverviewFilter();
    await renderOverview();
}

// ── Tab rendering ─────────────────────────────────────────────────────────────

function renderTabs() {
    const tabList = document.getElementById('portfolioTabs');
    // Tab-paneovi moraju biti direktna djeca .tab-content diva
    const tabContent = tabList?.closest('.card')?.querySelector('.tab-content');
    if (!tabList || !tabContent) return;

    // Ukloni stare dinamičke tabove i paneove
    tabList.querySelectorAll('[data-pf-id]').forEach(el => el.remove());
    tabContent.querySelectorAll('[data-pf-pane]').forEach(el => el.remove());

    if (_portfolios.length === 0) {
        document.getElementById('overview-loading').style.display = 'none';
        document.getElementById('overview-empty').style.display = '';
        return;
    }
    document.getElementById('overview-empty').style.display = 'none';

    _portfolios.forEach(pf => {
        // Tab button
        const li = document.createElement('li');
        li.className = 'nav-item';
        li.dataset.pfId = pf.id;
        li.innerHTML = `<button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-pf-${pf.id}"
            data-pf-id="${pf.id}">${escHtml(pf.name)}</button>`;
        li.querySelector('button').addEventListener('click', () => loadPortfolioTab(pf.id));
        tabList.appendChild(li);

        // Tab pane direktno u .tab-content (ne u wrapper div!)
        const pane = document.createElement('div');
        pane.className = 'tab-pane fade';
        pane.id = `tab-pf-${pf.id}`;
        pane.dataset.pfPane = pf.id; // za cleanup
        pane.innerHTML = portfolioTabHTML(pf);
        tabContent.appendChild(pane);

        wirePfTabControls(pf.id);
    });
}

function portfolioTabHTML(pf) {
    return `
    <div class="px-3 py-2 border-bottom border-secondary d-flex flex-wrap gap-2 align-items-center bg-dark">
        <span class="text-white fw-bold">${escHtml(pf.name)}</span>
        <div class="d-flex align-items-center gap-1 ms-3">
            <span class="text-white small">Prag rebalancinga:</span>
            <input type="number" class="form-control form-control-sm" id="threshold-${pf.id}"
                   value="${pf.threshold_pct}" min="1" max="50" step="0.5" style="width:70px;">
            <span class="text-white small">%</span>
            <button class="btn btn-sm btn-outline-light" data-save-threshold="${pf.id}">Spremi</button>
        </div>
        <div class="ms-auto d-flex gap-2">
            <button class="btn btn-sm btn-outline-primary" data-add-token="${pf.id}">+ Token</button>
            <button class="btn btn-sm btn-outline-info" data-csv-upload="${pf.id}">↑ CSV</button>
            <span class="text-muted small pf-last-refresh me-1"></span>
            <button class="btn btn-sm btn-outline-light" data-refresh-pf="${pf.id}">&#8635; Osvježi</button>
            <button class="btn btn-sm btn-outline-danger" data-delete-pf="${pf.id}">Obriši</button>
        </div>
    </div>
    <div id="pf-loading-${pf.id}" class="text-center py-5 text-white">
        <div class="spinner-border mb-2" role="status"></div><div>Učitavam...</div>
    </div>
    <div id="pf-content-${pf.id}" style="display:none;">
        <div class="table-responsive">
            <table class="table table-sm table-dark table-bordered mb-0">
                <thead>
                    <tr>
                        <th>Token</th>
                        <th class="text-end">Količina</th>
                        <th class="text-end">Cijena</th>
                        <th class="text-end">Vrijednost</th>
                        <th class="text-end">% portf.</th>
                        <th class="text-end">Cilj %</th>
                        <th class="text-center">Rebalancing</th>
                        <th class="text-center">Preporuka</th>
                        <th class="text-center">Akcije</th>
                    </tr>
                </thead>
                <tbody id="pf-body-${pf.id}"></tbody>
                <tfoot id="pf-foot-${pf.id}"></tfoot>
            </table>
        </div>
    </div>`;
}

function wirePfTabControls(pfId) {
    const pane = document.getElementById(`tab-pf-${pfId}`);
    if (!pane) return;

    pane.querySelector(`[data-save-threshold="${pfId}"]`)?.addEventListener('click', async () => {
        const val = parseFloat(document.getElementById(`threshold-${pfId}`)?.value) || 5;
        await fetch(`/api/portfolio/${pfId}/threshold`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ threshold_pct: val })
        });
        const pf = _portfolios.find(p => p.id === pfId);
        if (pf) pf.threshold_pct = val;
        showToast('Prag spremljen');
    });

    pane.querySelector(`[data-add-token="${pfId}"]`)?.addEventListener('click', () => {
        _addTokenPortfolioId = pfId;
        document.getElementById('add-token-symbol').value = '';
        document.getElementById('add-token-name').value = '';
        document.getElementById('add-token-amount').value = '';
        getModal('addTokenModal').show();
    });

    pane.querySelector(`[data-csv-upload="${pfId}"]`)?.addEventListener('click', () => {
        _csvPortfolioId = pfId;
        document.getElementById('csv-file-input').value = '';
        document.getElementById('csv-result').style.display = 'none';
        getModal('csvModal').show();
    });

    pane.querySelector(`[data-refresh-pf="${pfId}"]`)?.addEventListener('click', async () => {
        await loadPortfolioTab(pfId);
        updateLastRefreshTime();
    });

    pane.querySelector(`[data-delete-pf="${pfId}"]`)?.addEventListener('click', async () => {
        const pf = _portfolios.find(p => p.id === pfId);
        if (!confirm(`Obriši portfolio "${pf?.name}"?`)) return;
        await fetch(`/api/portfolio/${pfId}`, { method: 'DELETE' });
        await loadPortfolios();
        // Aktiviraj Overview
        document.querySelector('#portfolioTabs [data-bs-target="#tab-overview"]')?.click();
        showToast('Portfolio obrisan');
    });
}

// ── Učitaj tab za portfolio ──────────────────────────────────────────────────

async function loadPortfolioTab(pfId) {
    _activePortfolioId = pfId;
    const loadEl = document.getElementById(`pf-loading-${pfId}`);
    const contentEl = document.getElementById(`pf-content-${pfId}`);
    if (!contentEl) return;

    loadEl.style.display = '';
    contentEl.style.display = 'none';

    try {
        const r = await fetch(`/api/portfolio/${pfId}/holdings`);
        const holdings = await r.json();
        const symbols = holdings.map(h => h.symbol);
        if (symbols.length) {
            const prices = await fetchPrices(symbols);
            Object.assign(_prices, prices);
        }
        const pf = _portfolios.find(p => p.id === pfId) || { threshold_pct: 5 };
        renderPortfolioTable(pfId, holdings, pf.threshold_pct);
    } catch (e) {
        loadEl.innerHTML = `<div class="alert alert-danger m-3">Greška: ${e.message}</div>`;
        return;
    }

    loadEl.style.display = 'none';
    contentEl.style.display = '';
}

function renderPortfolioTable(pfId, holdings, threshold) {
    const tbody = document.getElementById(`pf-body-${pfId}`);
    const tfoot = document.getElementById(`pf-foot-${pfId}`);
    if (!tbody) return;

    // Izračunaj vrijednosti
    const rows = holdings.map(h => {
        const price = _prices[h.symbol] || 0;
        const value = h.amount * price;
        return { ...h, price, value };
    });
    const totalValue = rows.reduce((s, r) => s + r.value, 0); // svi (za grand total)
    const activeValue = rows.filter(r => r.include_rebalancing).reduce((s, r) => s + r.value, 0); // samo aktivni

    tbody.innerHTML = '';
    rows.forEach(h => {
        const isActive = h.include_rebalancing;
        const pct = activeValue > 0 && isActive ? (h.value / activeValue * 100) : 0;
        const diff = pct - h.target_pct;
        const needsRebal = isActive && Math.abs(diff) >= threshold;
        const rebalAction = needsRebal ? (diff > 0 ? 'Prodaj' : 'Kupi') : '—';
        const rebalColor = !needsRebal ? '' : (diff > 0 ? 'text-danger' : 'text-success');
        const targetValue = activeValue * (h.target_pct / 100);
        const diffUsd = targetValue - h.value;
        const diffQty = h.price > 0 ? diffUsd / h.price : 0;

        const tr = document.createElement('tr');
        if (!isActive) tr.style.cssText = 'opacity:0.35; filter:grayscale(1);';
        tr.innerHTML = `
            <td>
                <div class="fw-bold text-primary" style="font-size:0.85rem;">${escHtml(h.symbol)}</div>
                <div class="text-white" style="font-size:0.7rem;">${escHtml(h.name)}</div>
            </td>
            <td class="text-end text-white">
                <span class="pf-amount-display">${fmt4(h.amount)}</span>
                <input type="number" class="form-control form-control-sm pf-amount-input d-none"
                    value="${h.amount}" step="any" min="0" style="width:100px;display:inline-block!important;">
                <button class="btn btn-outline-secondary btn-sm ms-1 pf-amount-edit" data-hid="${h.id}" data-pfid="${pfId}" title="Promijeni količinu" style="padding:1px 5px;font-size:0.7rem;">✎</button>
            </td>
            <td class="text-end text-white">${h.price ? '$' + fmt2(h.price) : '—'}</td>
            <td class="text-end text-white">${h.price ? '$' + fmt2(h.value) : '—'}</td>
            <td class="text-end text-white">${totalValue > 0 ? pct.toFixed(2) + '%' : '—'}</td>
            <td class="text-end">
                <input type="number" class="form-control form-control-sm text-center px-1 pf-target-input"
                    data-hid="${h.id}" data-pfid="${pfId}"
                    value="${h.target_pct || ''}" min="0" max="100" step="1"
                    style="width:70px;display:inline-block;">
            </td>
            <td class="text-center">
                <div class="form-check form-switch d-flex justify-content-center mb-0">
                    <input class="form-check-input pf-rebal-toggle" type="checkbox" data-hid="${h.id}" data-pfid="${pfId}"
                        ${h.include_rebalancing ? 'checked' : ''}>
                </div>
            </td>
            <td class="text-center fw-bold ${rebalColor}">
                ${needsRebal ? `
                    <div>${rebalAction}</div>
                    <div style="font-size:0.8rem; color:#6ea8fe !important;">$${fmt2(Math.abs(diffUsd))}</div>
                    <div style="font-size:0.75rem; color:${diff > 0 ? '#ea868f' : '#75b798'} !important;">${fmt4(Math.abs(diffQty))} ${h.symbol}</div>
                ` : '—'}
            </td>
            <td class="text-center">
                <button class="btn btn-sm btn-outline-danger pf-del-btn" data-hid="${h.id}" data-pfid="${pfId}">×</button>
            </td>`;
        tbody.appendChild(tr);
    });

    // Footer s ukupno
    if (tfoot) {
        const usdcHolding = rows.find(r => (r.symbol === 'USDC' || r.symbol === 'USDT') && r.include_rebalancing);
        const usdcAvailable = usdcHolding ? usdcHolding.value : 0;
        const usdcTargetPct = usdcHolding ? usdcHolding.target_pct : 0;
        const usdcTargetValue = activeValue * (usdcTargetPct / 100);

        let totalBuy = 0, totalSell = 0;
        rows.forEach(r => {
            if (!r.include_rebalancing) return;
            const rpct = activeValue > 0 ? (r.value / activeValue * 100) : 0;
            const rdiff = rpct - r.target_pct;
            const rNeeds = Math.abs(rdiff) >= threshold;
            if (!rNeeds) return;
            const targetVal = activeValue * (r.target_pct / 100);
            const diffUsd = Math.abs(targetVal - r.value);
            if (rdiff > 0) totalSell += diffUsd;
            else totalBuy += diffUsd;
        });

        const netAfterSell = usdcAvailable + totalSell;
        const remaining = netAfterSell - totalBuy;
        const hasEnough = remaining >= 0;

        tfoot.innerHTML = `
        <tr class="table-secondary fw-bold">
            <td colspan="3" class="text-end text-white small text-uppercase">Ukupno (aktivni)</td>
            <td class="text-end text-white">$${fmt2(activeValue)}</td>
            <td class="text-end text-white">100%</td>
            <td colspan="4"></td>
        </tr>
        ${activeValue !== totalValue ? `
        <tr class="table-secondary" style="opacity:0.5;">
            <td colspan="3" class="text-end text-white small text-uppercase">Ukupno (sve)</td>
            <td class="text-end text-white">$${fmt2(totalValue)}</td>
            <td colspan="5"></td>
        </tr>` : ''}
        <tr class="bg-dark">
            <td colspan="9" class="px-3 py-2">
                <div class="d-flex flex-wrap gap-4 align-items-center">
                    <span class="small text-white fw-bold">Rebalancing sažetak:</span>
                    <span class="small">Za kupiti: <span style="color:#6ea8fe !important;" class="fw-bold">$${fmt2(totalBuy)}</span></span>
                    <span class="small">Od prodaje: <span style="color:#75b798 !important;" class="fw-bold">+$${fmt2(totalSell)}</span></span>
                    <span class="small">USDC dostupno: <span style="color:#75b798 !important;" class="fw-bold">$${fmt2(usdcAvailable)}</span></span>
                    <span class="small fw-bold" style="color:${hasEnough ? '#75b798' : '#ea868f'} !important;">
                        ${hasEnough
                            ? `✓ Dovoljno — ostaje $${fmt2(remaining)} USDC`
                            : `✗ Nedostaje $${fmt2(Math.abs(remaining))} USDC`}
                    </span>
                    ${usdcTargetPct > 0 ? `
                    <span class="small text-white ms-2">|</span>
                    <span class="small text-white">Za ${usdcTargetPct}% rezervu uvijek treba: <span style="color:#6ea8fe !important;" class="fw-bold">$${fmt2(usdcTargetValue)}</span></span>
                    ` : ''}
                </div>
            </td>
        </tr>`;
    }

    // Wire up controls
    tbody.querySelectorAll('.pf-target-input').forEach(inp => {
        inp.addEventListener('change', async () => {
            const hid = inp.dataset.hid;
            await fetch(`/api/portfolio/holding/${hid}/target`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target_pct: parseFloat(inp.value) || 0 })
            });
            loadPortfolioTab(parseInt(inp.dataset.pfid));
        });
    });

    tbody.querySelectorAll('.pf-rebal-toggle').forEach(chk => {
        chk.addEventListener('change', async () => {
            await fetch(`/api/portfolio/holding/${chk.dataset.hid}/toggle`, { method: 'POST' });
            loadPortfolioTab(parseInt(chk.dataset.pfid));
        });
    });

    tbody.querySelectorAll('.pf-amount-edit').forEach(btn => {
        btn.addEventListener('click', () => {
            const td = btn.closest('td');
            const display = td.querySelector('.pf-amount-display');
            const input = td.querySelector('.pf-amount-input');
            const isEditing = !input.classList.contains('d-none');
            if (isEditing) {
                // Spremi
                const newAmt = parseFloat(input.value);
                if (!isNaN(newAmt) && newAmt >= 0) {
                    fetch(`/api/portfolio/${btn.dataset.pfid}/holding/${btn.dataset.hid}/amount`, {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ amount: newAmt })
                    }).then(() => loadPortfolioTab(parseInt(btn.dataset.pfid)));
                }
                input.classList.add('d-none');
                display.classList.remove('d-none');
                btn.textContent = '✎';
            } else {
                // Otvori edit
                display.classList.add('d-none');
                input.classList.remove('d-none');
                input.focus();
                input.select();
                btn.textContent = '✔';
            }
        });
    });

    tbody.querySelectorAll('.pf-amount-input').forEach(input => {
        input.addEventListener('keydown', e => {
            if (e.key === 'Enter') input.closest('td').querySelector('.pf-amount-edit').click();
            if (e.key === 'Escape') {
                input.classList.add('d-none');
                input.closest('td').querySelector('.pf-amount-display').classList.remove('d-none');
                input.closest('td').querySelector('.pf-amount-edit').textContent = '✎';
            }
        });
    });

    tbody.querySelectorAll('.pf-del-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm('Obriši token?')) return;
            await fetch(`/api/portfolio/holding/${btn.dataset.hid}`, { method: 'DELETE' });
            loadPortfolioTab(parseInt(btn.dataset.pfid));
        });
    });
}

// ── Overview filter ───────────────────────────────────────────────────────────

function renderOverviewFilter() {
    const list = document.getElementById('pf-filter-list');
    const btn = document.getElementById('pf-filter-btn');
    if (!list) return;
    list.innerHTML = '';

    _portfolios.forEach(pf => {
        const li = document.createElement('li');
        li.innerHTML = `
            <label class="dropdown-item d-flex align-items-center gap-2" style="cursor:pointer;">
                <input type="checkbox" class="form-check-input pf-filter-chk" data-pfid="${pf.id}"
                    ${_selectedPortfolioIds.has(pf.id) ? 'checked' : ''}>
                <span class="text-white">${escHtml(pf.name)}</span>
            </label>`;
        list.appendChild(li);
    });

    list.querySelectorAll('.pf-filter-chk').forEach(chk => {
        chk.addEventListener('change', () => {
            const id = parseInt(chk.dataset.pfid);
            if (chk.checked) _selectedPortfolioIds.add(id);
            else _selectedPortfolioIds.delete(id);

            // Ažuriraj label gumba
            const total = _portfolios.length;
            const sel = _selectedPortfolioIds.size;
            if (btn) btn.textContent = sel === total ? 'Portfoliji' : `Portfoliji (${sel}/${total})`;

            renderOverview();
        });
    });
}

// ── Overview ─────────────────────────────────────────────────────────────────

async function renderOverview() {
    const loadEl = document.getElementById('overview-loading');
    const contentEl = document.getElementById('overview-content');
    const emptyEl = document.getElementById('overview-empty');

    if (_portfolios.length === 0) {
        loadEl.style.display = 'none';
        emptyEl.style.display = '';
        contentEl.style.display = 'none';
        return;
    }

    loadEl.style.display = '';
    contentEl.style.display = 'none';
    emptyEl.style.display = 'none';

    // Skupi holdinge samo za odabrane portfolije
    const allHoldings = [];
    for (const pf of _portfolios) {
        if (!_selectedPortfolioIds.has(pf.id)) continue;
        try {
            const r = await fetch(`/api/portfolio/${pf.id}/holdings`);
            const h = await r.json();
            h.forEach(x => allHoldings.push({ ...x, pfName: pf.name }));
        } catch {}
    }

    // Agregacija po symbolu
    const bySymbol = {};
    allHoldings.forEach(h => {
        if (!bySymbol[h.symbol]) bySymbol[h.symbol] = { symbol: h.symbol, name: h.name, amount: 0, portfolios: [] };
        bySymbol[h.symbol].amount += h.amount;
        bySymbol[h.symbol].portfolios.push({ name: h.pfName, amount: h.amount });
    });

    // Dohvati cijene
    const symbols = Object.keys(bySymbol);
    if (symbols.length) {
        const prices = await fetchPrices(symbols);
        Object.assign(_prices, prices);
    }

    const rows = Object.values(bySymbol).map(s => ({
        ...s,
        price: _prices[s.symbol] || 0,
        value: s.amount * (_prices[s.symbol] || 0),
    }));
    rows.sort((a, b) => b.value - a.value);

    // Dohvati globalne ciljeve
    let globalTargets = {};
    try {
        const gt = await fetch('/api/global_targets');
        globalTargets = await gt.json();
    } catch {}

    const threshold = parseFloat(document.getElementById('overview-threshold')?.value) || 5;

    // totalValue = svi tokeni (za grand total na vrhu)
    // activeValue = samo oni s include_rebalancing=true (za % i rebalancing)
    const totalValue = rows.reduce((s, r) => s + r.value, 0);
    const activeValue = rows.reduce((s, r) => {
        const gt = globalTargets[r.symbol] || { include_rebalancing: true };
        return s + (gt.include_rebalancing ? r.value : 0);
    }, 0);

    const tbody = document.getElementById('overview-body');
    const tfoot = document.getElementById('overview-foot');
    if (tbody) {
        tbody.innerHTML = '';
        rows.forEach(r => {
            const gt = globalTargets[r.symbol] || { target_pct: 0, include_rebalancing: true };
            const isActive = gt.include_rebalancing;
            const pct = isActive && activeValue > 0 ? (r.value / activeValue * 100) : 0;
            const diff = pct - gt.target_pct;
            const needsRebal = isActive && gt.target_pct > 0 && Math.abs(diff) >= threshold;
            const rebalColor = !needsRebal ? '' : (diff > 0 ? '#ea868f' : '#75b798');
            const rebalAction = needsRebal ? (diff > 0 ? 'Prodaj' : 'Kupi') : '—';
            const targetVal = activeValue * (gt.target_pct / 100);
            const diffUsd = Math.abs(targetVal - r.value);
            const diffQty = r.price > 0 ? diffUsd / r.price : 0;

            const pfBadges = r.portfolios.map(p =>
                `<div class="d-flex justify-content-between align-items-center gap-2" style="min-width:140px;">
                    <span class="badge bg-secondary" style="font-size:0.65rem; white-space:nowrap;">${escHtml(p.name)}</span>
                    <span class="text-white" style="font-size:0.72rem;">${fmt4(p.amount)}</span>
                </div>`
            ).join('<div style="border-top:1px solid #444; margin:2px 0;"></div>');

            const tr = document.createElement('tr');
            if (!isActive) tr.style.cssText = 'opacity:0.35; filter:grayscale(1);';
            tr.innerHTML = `
                <td><div class="fw-bold text-primary" style="font-size:0.85rem;">${escHtml(r.symbol)}</div>
                    <div class="text-white" style="font-size:0.7rem;">${escHtml(r.name)}</div></td>
                <td class="text-end text-white">${fmt4(r.amount)}</td>
                <td class="text-end text-white">${r.price ? '$' + fmt2(r.price) : '—'}</td>
                <td class="text-end text-white">${r.price ? '$' + fmt2(r.value) : '—'}</td>
                <td class="text-end text-white">${isActive ? pct.toFixed(2) + '%' : '—'}</td>
                <td class="text-end">
                    <input type="number" class="form-control form-control-sm text-center px-1 ov-target-input"
                        data-symbol="${r.symbol}" value="${gt.target_pct || ''}"
                        min="0" max="100" step="1" style="width:70px;display:inline-block;">
                </td>
                <td class="text-center">
                    <div class="form-check form-switch d-flex justify-content-center mb-0">
                        <input class="form-check-input ov-rebal-toggle" type="checkbox"
                            data-symbol="${r.symbol}" ${isActive ? 'checked' : ''}>
                    </div>
                </td>
                <td class="text-center fw-bold" style="color:${rebalColor || 'inherit'} !important;">
                    ${needsRebal ? `
                        <div>${rebalAction}</div>
                        <div style="font-size:0.8rem; color:#6ea8fe !important;">$${fmt2(diffUsd)}</div>
                        <div style="font-size:0.75rem; color:${rebalColor} !important;">${fmt4(diffQty)} ${r.symbol}</div>
                    ` : '—'}
                </td>
                <td>${pfBadges}</td>`;
            tbody.appendChild(tr);
        });

        // Wire inputs — bez duplikata listenera
        tbody.querySelectorAll('.ov-target-input').forEach(inp => {
            inp.addEventListener('change', async () => {
                await fetch(`/api/global_targets/${inp.dataset.symbol}/target`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ target_pct: parseFloat(inp.value) || 0 })
                });
                renderOverview();
            });
        });
        tbody.querySelectorAll('.ov-rebal-toggle').forEach(chk => {
            chk.addEventListener('change', async () => {
                await fetch(`/api/global_targets/${chk.dataset.symbol}/toggle`, { method: 'POST' });
                renderOverview();
            });
        });
        const threshEl = document.getElementById('overview-threshold');
        if (threshEl && !threshEl.dataset.wired) {
            threshEl.dataset.wired = '1';
            threshEl.addEventListener('change', renderOverview);
        }
    }

    // Sažetak — activeValue baza, totalValue za grand total na vrhu
    if (tfoot) {
        const usdcRow = rows.find(r => (r.symbol === 'USDC' || r.symbol === 'USDT') &&
            (globalTargets[r.symbol] || { include_rebalancing: true }).include_rebalancing);
        const usdcAvailable = usdcRow ? usdcRow.value : 0;
        const usdcGt = globalTargets[usdcRow?.symbol] || { target_pct: 0 };
        const usdcTargetPct = usdcGt.target_pct;
        const usdcTargetValue = activeValue * (usdcTargetPct / 100);

        let totalBuy = 0, totalSell = 0;
        rows.forEach(r => {
            const gt = globalTargets[r.symbol] || { target_pct: 0, include_rebalancing: true };
            if (!gt.include_rebalancing || gt.target_pct === 0) return;
            const pct = activeValue > 0 ? (r.value / activeValue * 100) : 0;
            const diff = pct - gt.target_pct;
            if (Math.abs(diff) < threshold) return;
            const diffUsd = Math.abs(activeValue * (gt.target_pct / 100) - r.value);
            if (diff > 0) totalSell += diffUsd; else totalBuy += diffUsd;
        });
        const netAfterSell = usdcAvailable + totalSell;
        const remaining = netAfterSell - totalBuy;
        const hasEnough = remaining >= 0;

        tfoot.innerHTML = `
        <tr class="table-secondary fw-bold">
            <td colspan="3" class="text-end text-white small text-uppercase">Ukupno (aktivni)</td>
            <td class="text-end text-white">$${fmt2(activeValue)}</td>
            <td colspan="5"></td>
        </tr>
        ${activeValue !== totalValue ? `
        <tr class="table-secondary" style="opacity:0.5;">
            <td colspan="3" class="text-end text-white small text-uppercase">Ukupno (sve)</td>
            <td class="text-end text-white">$${fmt2(totalValue)}</td>
            <td colspan="5"></td>
        </tr>` : ''}
        <tr class="bg-dark">
            <td colspan="9" class="px-3 py-2">
                <div class="d-flex flex-wrap gap-4 align-items-center">
                    <span class="small text-white fw-bold">Globalni rebalancing sažetak:</span>
                    <span class="small">Za kupiti: <span style="color:#6ea8fe !important;" class="fw-bold">$${fmt2(totalBuy)}</span></span>
                    <span class="small">Od prodaje: <span style="color:#75b798 !important;" class="fw-bold">+$${fmt2(totalSell)}</span></span>
                    <span class="small">USDC dostupno: <span style="color:#75b798 !important;" class="fw-bold">$${fmt2(usdcAvailable)}</span></span>
                    <span class="small fw-bold" style="color:${hasEnough ? '#75b798' : '#ea868f'} !important;">
                        ${hasEnough ? `✓ Dovoljno — ostaje $${fmt2(remaining)} USDC` : `✗ Nedostaje $${fmt2(Math.abs(remaining))} USDC`}
                    </span>
                    ${usdcTargetPct > 0 ? `<span class="small text-white ms-2">| Za ${usdcTargetPct}% rezervu uvijek treba: <span style="color:#6ea8fe !important;" class="fw-bold">$${fmt2(usdcTargetValue)}</span></span>` : ''}
                </div>
            </td>
        </tr>`;
    }

    const totalEl = document.getElementById('overview-total-value');
    if (totalEl) totalEl.textContent = '$' + fmt2(totalValue);

    loadEl.style.display = 'none';
    contentEl.style.display = '';
}

// ── Modali ────────────────────────────────────────────────────────────────────

async function handleCreatePortfolio() {
    const name = document.getElementById('new-pf-name')?.value.trim();
    const threshold = parseFloat(document.getElementById('new-pf-threshold')?.value) || 5;
    if (!name) { showToast('Unesi naziv!', 'warning'); return; }
    const r = await fetch('/api/portfolio/create', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, threshold_pct: threshold })
    });
    const d = await r.json();
    if (d.error) { showToast(d.error, 'danger'); return; }
    getModal('newPortfolioModal').hide();
    await loadPortfolios();
    // Klikni tab novog portfolija
    setTimeout(() => {
        const btn = document.querySelector(`[data-bs-target="#tab-pf-${d.id}"]`);
        btn?.click();
    }, 100);
    showToast('Portfolio stvoren!');
}

async function handleCsvUpload() {
    const file = document.getElementById('csv-file-input')?.files[0];
    const resultEl = document.getElementById('csv-result');
    if (!file) { showToast('Odaberi CSV datoteku', 'warning'); return; }
    const fd = new FormData();
    fd.append('file', file);
    resultEl.style.display = '';
    resultEl.className = 'mt-2 small text-info';
    resultEl.textContent = 'Uvozim...';
    try {
        const r = await fetch(`/api/portfolio/${_csvPortfolioId}/upload_csv`, { method: 'POST', body: fd });
        const d = await r.json();
        if (d.error) {
            resultEl.className = 'mt-2 small text-danger';
            resultEl.textContent = 'Greška: ' + d.error;
        } else {
            resultEl.className = 'mt-2 small text-success';
            resultEl.textContent = `Uvezeno ${d.added} tokena!`;
            setTimeout(() => getModal('csvModal').hide(), 1500);
            if (_csvPortfolioId) loadPortfolioTab(_csvPortfolioId);
        }
    } catch (e) {
        resultEl.className = 'mt-2 small text-danger';
        resultEl.textContent = 'Greška: ' + e.message;
    }
}

async function handleAddToken() {
    const symbol = document.getElementById('add-token-symbol')?.value.trim().toUpperCase();
    const name = document.getElementById('add-token-name')?.value.trim() || symbol;
    const amount = parseFloat(document.getElementById('add-token-amount')?.value) || 0;
    if (!symbol) { showToast('Unesi symbol', 'warning'); return; }
    const r = await fetch(`/api/portfolio/${_addTokenPortfolioId}/holding`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, name, amount })
    });
    const d = await r.json();
    if (d.error) { showToast(d.error, 'danger'); return; }
    getModal('addTokenModal').hide();
    if (_addTokenPortfolioId) loadPortfolioTab(_addTokenPortfolioId);
    showToast('Token dodan!');
}

function escHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function updateLastRefreshTime() {
    const now = new Date().toLocaleTimeString('hr-HR', { hour: '2-digit', minute: '2-digit' });
    document.querySelectorAll('.pf-last-refresh').forEach(el => el.textContent = `Zadnje osvježavanje: ${now}`);
}

async function autoRefresh() {
    // Osvježi aktivni tab (overview ili konkretan portfolio)
    const activePane = document.querySelector('.tab-pane.active');
    if (!activePane) return;
    if (activePane.id === 'tab-overview') {
        await renderOverview();
    } else if (_activePortfolioId) {
        await loadPortfolioTab(_activePortfolioId);
    }
    updateLastRefreshTime();
}

// ── Init ─────────────────────────────────────────────────────────────────────

export async function initPortfolio() {
    await loadCmcKey();

    document.getElementById('cmc-save-btn')?.addEventListener('click', saveCmcKey);
    document.getElementById('btn-new-portfolio')?.addEventListener('click', () => getModal('newPortfolioModal').show());
    document.getElementById('create-portfolio-btn')?.addEventListener('click', handleCreatePortfolio);
    document.getElementById('csv-upload-btn')?.addEventListener('click', handleCsvUpload);
    document.getElementById('add-token-btn')?.addEventListener('click', handleAddToken);
    document.getElementById('overview-refresh-btn')?.addEventListener('click', async () => {
        await renderOverview();
        updateLastRefreshTime();
    });

    await loadPortfolios();
    updateLastRefreshTime();

    // Auto-osvježavanje svaki sat
    setInterval(autoRefresh, 60 * 60 * 1000);
}
