// --- Helpers ---
function rsiColor(rsi) {
    if (rsi === null) return '';
    if (rsi < 30) return 'color:#75b798;font-weight:bold';
    if (rsi < 45) return 'color:#a3cfbb';
    if (rsi > 70) return 'color:#ea868f;font-weight:bold';
    if (rsi > 55) return 'color:#f0a070';
    return 'color:#ccc';
}

function trendBadge(trend) {
    if (!trend) return '';
    const map = {
        'Sideways':  ['bg-success', '↔ Sideways'],
        'Uptrend':   ['bg-primary', '↑ Uptrend'],
        'Downtrend': ['bg-danger',  '↓ Downtrend'],
    };
    const [cls, label] = map[trend] || ['bg-secondary', trend];
    return `<span class="badge ${cls}">${label}</span>`;
}

function volColor(atr) {
    if (atr === null) return '';
    if (atr > 3)   return 'color:#75b798;font-weight:bold';
    if (atr > 1.5) return 'color:#a3cfbb';
    if (atr < 0.5) return 'color:#ea868f';
    return 'color:#ccc';
}

function bbBar(bbPct) {
    if (bbPct === null) return '';
    const pct = Math.round(bbPct);
    const color = pct < 25 ? '#75b798' : pct > 75 ? '#ea868f' : '#6ea8fe';
    return `
        <div style="font-size:0.7rem;color:#aaa;">${pct}%</div>
        <div style="background:#333;border-radius:3px;height:6px;width:80px;margin:auto;">
            <div style="background:${color};width:${pct}%;height:100%;border-radius:3px;"></div>
        </div>`;
}

function scoreBadge(score, label) {
    const cls = (label === 'Dobar' || label === 'Akumuliraj')
        ? 'bg-success'
        : (label === 'Neutralan' || label === 'Čekaj')
            ? 'bg-warning text-dark'
            : 'bg-danger';
    return `<span class="badge ${cls} fs-6">${score}</span>`;
}

function gridBadge(label) {
    if (label === 'Dobar')    return '<span class="badge bg-success">✓ Dobar</span>';
    if (label === 'Neutralan') return '<span class="badge bg-warning text-dark">~ Neutralan</span>';
    if (label === 'Loš')       return '<span class="badge bg-danger">✗ Loš</span>';
    return '<span class="badge bg-secondary">Greška</span>';
}

function dcaBadge(label) {
    if (label === 'Akumuliraj') return '<span class="badge bg-success">✓ Akumuliraj</span>';
    if (label === 'Čekaj')      return '<span class="badge bg-warning text-dark">~ Čekaj</span>';
    if (label === 'Preskupo')   return '<span class="badge bg-danger">✗ Preskupo</span>';
    return '<span class="badge bg-secondary">Greška</span>';
}

function ma200Color(pct) {
    if (pct === null) return '';
    if (pct < -25) return 'color:#75b798;font-weight:bold';
    if (pct < -10) return 'color:#a3cfbb';
    if (pct < 0)   return 'color:#ccc';
    return 'color:#ea868f';
}

function highColor(pct) {
    if (pct === null) return '';
    if (pct < -50) return 'color:#75b798;font-weight:bold';
    if (pct < -30) return 'color:#a3cfbb';
    if (pct < -15) return 'color:#ccc';
    return 'color:#ea868f';
}

function profitModeBadge(mode) {
    return mode === 'crypto'
        ? '<span class="badge bg-success">crypto</span>'
        : '<span class="badge bg-primary">usdc</span>';
}

function recommendationCell(r) {
    const rec = r.recommended_mode;
    const cur = r.profit_mode;

    // Tekst preporuke
    let recLabel = '';
    if (!rec)           recLabel = '<div class="text-white" style="font-size:0.75rem;">Bez promjene</div>';
    else if (rec === cur) recLabel = '<div class="text-success" style="font-size:0.75rem;">✓ OK</div>';
    else {
        const txt = rec === 'crypto' ? '↑ akumuliraj (crypto)' : '↓ zaštiti (usdc)';
        const cls = rec === 'crypto' ? 'text-success' : 'text-primary';
        recLabel = `<div class="${cls}" style="font-size:0.75rem;">${txt}</div>`;
    }

    // Uvijek prikaži oba gumba — trenutni je disabled
    const usdcDis  = cur === 'usdc'   ? 'disabled' : '';
    const cryptoDis = cur === 'crypto' ? 'disabled' : '';

    return `<td class="text-center">
        ${recLabel}
        <div class="d-flex gap-1 justify-content-center mt-1">
            <button class="btn btn-outline-primary btn-sm py-0 px-1 apply-mode-btn" ${usdcDis}
                data-pair-id="${r.pair_id}" data-mode="usdc" data-symbol="${r.symbol}">usdc</button>
            <button class="btn btn-outline-success btn-sm py-0 px-1 apply-mode-btn" ${cryptoDis}
                data-pair-id="${r.pair_id}" data-mode="crypto" data-symbol="${r.symbol}">crypto</button>
        </div>
    </td>`;
}

function pairCell(symbol, exchange) {
    return `<td>
        <div class="fw-bold text-primary" style="font-size:0.85rem;">${symbol}</div>
        <div class="text-warning" style="font-size:0.7rem;">${exchange}</div>
    </td>`;
}

function nowStr() {
    return new Date().toLocaleTimeString('hr-HR');
}

// --- Grid tab ---
function renderGrid(data) {
    const tbody = document.getElementById('grid-body');
    tbody.innerHTML = '';
    data.forEach(r => {
        const tr = document.createElement('tr');
        if (r.error) {
            tr.innerHTML = `${pairCell(r.symbol, r.exchange)}<td colspan="7" class="text-danger text-center small">${r.error}</td>`;
        } else {
            tr.innerHTML = `
                ${pairCell(r.symbol, r.exchange)}
                <td class="text-end">${r.price}</td>
                <td class="text-center" style="${rsiColor(r.rsi)}">${r.rsi}</td>
                <td class="text-center">${trendBadge(r.trend)}<div class="text-muted" style="font-size:0.65rem;">${r.trend_strength}%</div></td>
                <td class="text-center" style="${volColor(r.atr_pct)}">${r.atr_pct}%</td>
                <td class="text-center">${bbBar(r.bb_pct)}</td>
                <td class="text-center">${scoreBadge(r.score, r.score_label)}</td>
                <td class="text-center">${gridBadge(r.score_label)}</td>`;
        }
        tbody.appendChild(tr);
    });
    document.getElementById('grid-loading').style.display = 'none';
    document.getElementById('grid-table-wrap').style.display = '';
    document.getElementById('grid-timestamp').textContent = `Osvježeno: ${nowStr()}`;
}

function loadGrid() {
    const tf = document.getElementById('analysis-timeframe')?.value || '1h';
    document.getElementById('grid-loading').style.display = '';
    document.getElementById('grid-table-wrap').style.display = 'none';
    document.getElementById('grid-error').style.display = 'none';

    fetch(`/api/market_analysis?timeframe=${tf}`)
        .then(r => r.json())
        .then(data => {
            if (data.error) throw new Error(data.error);
            renderGrid(data);
        })
        .catch(err => {
            document.getElementById('grid-loading').style.display = 'none';
            const el = document.getElementById('grid-error');
            el.textContent = 'Greška: ' + err.message;
            el.style.display = '';
        });
}

// --- DCA tab ---
function renderDca(data) {
    const tbody = document.getElementById('dca-body');
    tbody.innerHTML = '';
    data.forEach(r => {
        const tr = document.createElement('tr');
        if (r.error) {
            tr.innerHTML = `${pairCell(r.symbol, r.exchange)}<td colspan="7" class="text-danger text-center small">${r.error}</td>`;
        } else {
            const ma200Str = r.vs_ma200 >= 0 ? `+${r.vs_ma200}%` : `${r.vs_ma200}%`;
            const highStr  = `${r.dist_from_high}%`;
            tr.innerHTML = `
                ${pairCell(r.symbol, r.exchange)}
                <td class="text-end">${r.price}</td>
                <td class="text-center" style="${rsiColor(r.rsi_daily)}">${r.rsi_daily}</td>
                <td class="text-center" style="${rsiColor(r.rsi_weekly)}">${r.rsi_weekly}</td>
                <td class="text-center" style="${ma200Color(r.vs_ma200)}">${ma200Str}</td>
                <td class="text-center" style="${highColor(r.dist_from_high)}">${highStr}</td>
                <td class="text-center">${scoreBadge(r.score, r.score_label)}</td>
                <td class="text-center">${dcaBadge(r.score_label)}</td>
                <td class="text-center" id="mode-cell-${r.pair_id}">${profitModeBadge(r.profit_mode)}</td>
                ${recommendationCell(r)}`;
        }
        tbody.appendChild(tr);
    });
    document.getElementById('dca-loading').style.display = 'none';
    document.getElementById('dca-table-wrap').style.display = '';
    document.getElementById('dca-timestamp').textContent = `Osvježeno: ${nowStr()}`;

    tbody.querySelectorAll('.apply-mode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const pairId = btn.dataset.pairId;
            const mode   = btn.dataset.mode;
            const symbol = btn.dataset.symbol;
            if (!confirm(`Promijeni profit mod za ${symbol} u "${mode}"?`)) return;
            btn.disabled = true;
            btn.textContent = '...';
            fetch('/api/set_profit_mode', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pair_id: pairId, profit_mode: mode })
            })
            .then(r => r.json())
            .then(data => {
                if (data.error) { alert('Greška: ' + data.error); btn.disabled = false; return; }
                const cell = document.getElementById(`mode-cell-${pairId}`);
                if (cell) cell.innerHTML = profitModeBadge(mode);
                // Osvježi disabled stanje — novi mod je aktivan
                const td = btn.closest('td');
                td.querySelectorAll('.apply-mode-btn').forEach(b => {
                    b.disabled = (b.dataset.mode === mode);
                });
            })
            .catch(() => { btn.disabled = false; btn.textContent = 'Greška'; });
        });
    });
}

let _dcaLoaded = false;

function loadDca() {
    document.getElementById('dca-loading').style.display = '';
    document.getElementById('dca-table-wrap').style.display = 'none';
    document.getElementById('dca-error').style.display = 'none';

    fetch('/api/dca_analysis')
        .then(r => r.json())
        .then(data => {
            if (data.error) throw new Error(data.error);
            _dcaLoaded = true;
            renderDca(data);
        })
        .catch(err => {
            document.getElementById('dca-loading').style.display = 'none';
            const el = document.getElementById('dca-error');
            el.textContent = 'Greška: ' + err.message;
            el.style.display = '';
        });
}

// --- Init ---
export function initAnalysis() {
    window._refreshGrid = loadGrid;
    window._refreshDca  = loadDca;

    document.getElementById('analysis-timeframe')?.addEventListener('change', loadGrid);

    // Učitaj DCA odmah, Grid tek kad se klikne tab
    loadDca();

    let _gridLoaded = false;
    document.getElementById('tab-grid-btn')?.addEventListener('click', () => {
        if (!_gridLoaded) { _gridLoaded = true; loadGrid(); }
    });
}
