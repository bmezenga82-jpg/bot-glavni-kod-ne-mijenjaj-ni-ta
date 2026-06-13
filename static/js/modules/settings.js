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
                const unreal = result.unrealized_pnl ?? 0;
                resultText += `Unrealized P&L:      ${unreal.toFixed(4)} USDC`;
                resultText += unreal >= 0 ? ' ✓\n' : ' ⚠ (pozicije ispod kupovne cijene)\n';
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
    })
    .catch(error => {
        resultsEl.textContent = 'Error running backtest: ' + error;
    });
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
        const m = data.meta || {};
        let text = '═══ TOP 5 KOMBINACIJA (sortirano po ukupnom P&L) ═══\n';
        if (m.symbol) {
            text += `Valuta:    ${m.symbol} na ${m.exchange}\n`;
            const sd = m.start_date || '2023-01-01 (default)';
            const ed = m.end_date   || 'danas (default)';
            text += `Period:    ${sd} → ${ed} (${m.timeframe})\n`;
            if (m.normalize_amount) {
                text += `Iznos:     SKALIRAN — referenca ${m.amount} USDC pri ${m.buy_pct_ref}%  |  Kapital: ${m.total_capital} USDC\n`;
                text += `           → npr. 0.8% koristi ${(m.amount * 0.8 / m.buy_pct_ref).toFixed(0)} USDC, 2% koristi ${(m.amount * 2 / m.buy_pct_ref).toFixed(0)} USDC\n`;
            } else {
                text += `Per-trade: ${m.amount} USDC (fiksno)  |  Kapital: ${m.total_capital} USDC\n`;
            }
        }
        const fmtCombo = (c, i, sortLabel) => {
            const amtStr = c.amount != null ? ` [iznos: ${c.amount} USDC]` : '';
            let s = `#${i + 1}  Buy: ${c.buy_pct}%  /  Sell: ${c.sell_pct}%${amtStr}\n`;
            s += `     Realizirano:     ${c.net_profit >= 0 ? '+' : ''}${c.net_profit.toFixed(4)} USDC\n`;
            s += `     Nerealizirano:   ${c.unrealized_pnl >= 0 ? '+' : ''}${c.unrealized_pnl.toFixed(4)} USDC\n`;
            s += `     Ukupni P&L:      ${c.total_pnl >= 0 ? '+' : ''}${c.total_pnl.toFixed(4)} USDC (${c.roi_pct.toFixed(2)}% ROI)\n`;
            if (c.annualized_roi != null)
                s += `     Godišnji ROI:    ${c.annualized_roi >= 0 ? '+' : ''}${c.annualized_roi.toFixed(2)}% / god\n`;
            s += `     Trades: ${c.trade_count}   |   Otvorenih pozicija: ${c.open_positions}\n`;
            return s;
        };

        text += '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n';
        text += '  TOP 5 po UKUPNOM P&L (realized + unrealized)\n';
        text += '  ⚠ Varira s tržištem — u bull marketu izgleda bolje\n';
        text += '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n';
        data.top_combos.forEach((c, i) => { text += fmtCombo(c, i) + '\n'; });

        text += '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n';
        text += '  TOP 5 po REALIZIRANOM PROFITU (samo zatvoreni ciklusi)\n';
        text += '  ✓ Stabilan pokazatelj — ne ovisi o smjeru tržišta\n';
        text += '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n';
        (data.top_by_realized || []).forEach((c, i) => { text += fmtCombo(c, i) + '\n'; });

        text += '═══════════════════════════════════════════════════\n';
        text += 'Savjet: za stabilan prihod gledaj TOP 5 po realiziranom.\n';
        text += 'Ukupni P&L je koristan za bull market procjenu, ali\n';
        text += 'pazi na broj otvorenih pozicija (rizik u bear marketu).\n';
        resultsEl.textContent = text;
    })
    .catch(error => {
        resultsEl.textContent = 'Greška: ' + error;
    });
}
