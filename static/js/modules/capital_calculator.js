const LS_KEY = 'capital_calc_inputs';

function loadSaved() {
    try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch { return {}; }
}
function save(key, val) {
    const d = loadSaved();
    d[key] = val;
    localStorage.setItem(LS_KEY, JSON.stringify(d));
}

function calcSteps(dropPct, buyPct) {
    if (dropPct <= 0 || buyPct <= 0) return 0;
    if (dropPct >= 100) dropPct = 99.9;
    return Math.ceil(Math.log(1 - dropPct / 100) / Math.log(1 - buyPct / 100));
}

function fmt(n) {
    return n.toLocaleString('hr-HR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

let _pairData = [];
let _spotTotal = 0;

function getExternalTotal() {
    const d = loadSaved();
    let total = 0;
    for (let i = 0; i < 4; i++) total += parseFloat(d[`ext_amt_${i}`]) || 0;
    return total;
}

// Gradi tablicu jednom — inputi se ne diraju pri recalcu
function renderTable() {
    const tbody = document.getElementById('capital-calc-body');
    if (!tbody) return;
    const saved = loadSaved();
    tbody.innerHTML = '';

    _pairData.forEach(p => {
        const savedPct = parseFloat(saved[`pct_${p.pair_id}`]) || 0;
        const tr = document.createElement('tr');
        tr.dataset.pairId = p.pair_id;
        tr.innerHTML = `
            <td>
                <div class="fw-bold text-primary" style="font-size:0.85rem;">${p.symbol}</div>
                <div class="text-warning" style="font-size:0.7rem;">${p.exchange}</div>
            </td>
            <td class="text-end">${fmt(p.usdc_amount)} $</td>
            <td class="text-end">${p.buy_pct.toFixed(2)}%</td>
            <td class="text-center">
                <input type="number" class="form-control form-control-sm text-center px-1 capital-pct-input"
                    data-pair-id="${p.pair_id}"
                    value="${savedPct || ''}" min="0" max="99" step="1"
                    style="width:80px;display:inline-block;">
            </td>
            <td class="text-end calc-steps"></td>
            <td class="text-end fw-bold calc-needed" style="color:#6ea8fe !important;"></td>
            <td class="text-end" style="color:#75b798 !important;">${fmt(p.invested)} $</td>
            <td class="text-end fw-bold calc-fali" style="color:#ea868f !important;"></td>`;
        tbody.appendChild(tr);
    });

    // Postavi listenere samo jednom pri renderu
    tbody.querySelectorAll('.capital-pct-input').forEach(input => {
        input.addEventListener('input', () => {
            save(`pct_${input.dataset.pairId}`, parseFloat(input.value) || 0);
            recalcValues(); // samo ažurira ćelije, ne dira inpute
        });
    });

    recalcValues();
}

// Ažurira samo izračunate ćelije — inputi se ne diraju
function recalcValues() {
    const saved = loadSaved();
    const tbody = document.getElementById('capital-calc-body');
    const tfoot = document.getElementById('capital-calc-foot');
    if (!tbody || !tfoot) return;

    let totalNeeded = 0;
    let totalInvested = 0;
    let totalFali = 0;

    _pairData.forEach(p => {
        const tr = tbody.querySelector(`tr[data-pair-id="${p.pair_id}"]`);
        if (!tr) return;
        const savedPct = parseFloat(saved[`pct_${p.pair_id}`]) || 0;
        const steps = calcSteps(savedPct, p.buy_pct);
        const needed = steps * p.usdc_amount;
        const fali = Math.max(0, needed - p.invested);

        tr.querySelector('.calc-steps').textContent = steps;
        tr.querySelector('.calc-needed').textContent = fmt(needed) + ' $';
        const faliEl = tr.querySelector('.calc-fali');
        faliEl.textContent = fmt(fali) + ' $';
        faliEl.className = 'text-end fw-bold calc-fali';
        faliEl.style.setProperty('color', '#ea868f', 'important');

        totalNeeded += needed;
        totalInvested += p.invested;
        totalFali += fali;
    });

    tfoot.innerHTML = `
        <tr class="table-secondary fw-bold">
            <td colspan="5" class="text-end text-uppercase small">Ukupno</td>
            <td class="text-end fw-bold" style="color:#6ea8fe !important;">${fmt(totalNeeded)} $</td>
            <td class="text-end fw-bold" style="color:#75b798 !important;">${fmt(totalInvested)} $</td>
            <td class="text-end fw-bold" style="color:#ea868f !important;">${fmt(totalFali)} $</td>
        </tr>`;

    recalcResult(totalFali);
}

function recalcResult(totalFali) {
    const d = loadSaved();
    const earn = parseFloat(d['earn']) || 0;
    const available = _spotTotal + earn + getExternalTotal();
    const finalResult = available - totalFali;

    const resultEl = document.getElementById('capital-result-value');
    if (!resultEl) return;
    if (finalResult >= 0) {
        resultEl.textContent = `+ ${fmt(finalResult)} $`;
        resultEl.className = 'fw-bold fs-5 text-success';
    } else {
        resultEl.textContent = `- ${fmt(Math.abs(finalResult))} $`;
        resultEl.className = 'fw-bold fs-5 text-danger';
    }
}

export function initCapitalCalculator() {
    const d = loadSaved();

    const earnEl = document.getElementById('capital-earn');
    if (earnEl) {
        earnEl.value = d['earn'] || '';
        earnEl.addEventListener('input', () => {
            save('earn', parseFloat(earnEl.value) || 0);
            recalcValues();
        });
    }

    for (let i = 0; i < 4; i++) {
        const amtEl = document.getElementById(`capital-ext-amt-${i}`);
        const noteEl = document.getElementById(`capital-ext-note-${i}`);
        if (amtEl) {
            amtEl.value = d[`ext_amt_${i}`] || '';
            amtEl.addEventListener('input', () => {
                save(`ext_amt_${i}`, parseFloat(amtEl.value) || 0);
                recalcValues();
            });
        }
        if (noteEl) {
            noteEl.value = d[`ext_note_${i}`] || '';
            noteEl.addEventListener('input', () => save(`ext_note_${i}`, noteEl.value));
        }
    }

    loadData();
}

export function refreshCapitalCalculator(accountInfo) {
    let spotSum = 0;
    let spotParts = [];
    if (accountInfo) {
        Object.entries(accountInfo).forEach(([key, info]) => {
            if (key.includes('testnet')) return;
            const bal = parseFloat(info.balance);
            if (!isNaN(bal)) {
                spotSum += bal;
                const [ex] = key.split('_');
                spotParts.push(`<span class="text-white">${ex}:</span> <span style="color:#75b798 !important;">${fmt(bal)} $</span>`);
            }
        });
    }
    _spotTotal = spotSum;
    const spotEl = document.getElementById('capital-spot-display');
    if (spotEl) spotEl.innerHTML = spotParts.length ? spotParts.join(' <span class="text-white">|</span> ') : '0 $';
    recalcValues();
}

function loadData() {
    fetch('/api/capital_calc_data')
        .then(r => r.json())
        .then(data => {
            _pairData = data.filter(p => p.trading_mode !== 'testnet');
            renderTable(); // jednom gradi tablicu s inputima
        })
        .catch(() => {});
}
