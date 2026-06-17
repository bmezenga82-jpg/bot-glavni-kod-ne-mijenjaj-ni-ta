/* Long-term technical analysis — Chart tab + Scanner tab */

let _ltChart = null, _ltRsiChart = null, _ltMacdChart = null;
let _ltSeries = {};

export function initLongTerm() {
    document.getElementById('lt-run-btn')?.addEventListener('click', runLongTermAnalysis);
    document.getElementById('lt-scan-btn')?.addEventListener('click', () => runScanner(false));
    document.getElementById('lt-scan-force-btn')?.addEventListener('click', () => runScanner(true));
    document.getElementById('lt-symbol')?.addEventListener('keydown', e => {
        if (e.key === 'Enter') runLongTermAnalysis();
    });
}

// ── LONG-TERM CHART ──────────────────────────────────────────────────────────

async function runLongTermAnalysis() {
    const sym = (document.getElementById('lt-symbol')?.value || 'BTC/USDT').trim().toUpperCase();
    const range = document.getElementById('lt-range')?.value || '1Y';

    const wrap = document.getElementById('lt-chart-wrap');
    const spinner = document.getElementById('lt-spinner');
    const errEl = document.getElementById('lt-error');
    const expEl = document.getElementById('lt-explanation');

    wrap.style.display = 'none';
    errEl.style.display = 'none';
    expEl.innerHTML = '';
    spinner.style.display = 'block';

    try {
        const res = await fetch(`/api/long_term_analysis?symbol=${encodeURIComponent(sym)}&range=${range}`);
        const data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || 'Greška');
        spinner.style.display = 'none';
        wrap.style.display = 'block';
        renderChart(data);
        renderIndicatorBadges(data);
        renderHalving(data.halving);
        renderExplanation(data.explanation);
    } catch (e) {
        spinner.style.display = 'none';
        errEl.textContent = `Greška: ${e.message}`;
        errEl.style.display = 'block';
    }
}

function renderChart(data) {
    // Destroy previous charts
    destroyCharts();

    const isDark = document.documentElement.classList.contains('dark');
    const bg = isDark ? '#1a1a2e' : '#ffffff';
    const textColor = isDark ? '#d1d5db' : '#1f2937';
    const gridColor = isDark ? '#2d2d44' : '#e5e7eb';

    const baseOpts = {
        layout: { background: { color: bg }, textColor },
        grid: { vertLines: { color: gridColor }, horzLines: { color: gridColor } },
        crosshair: { mode: 1 },
        timeScale: { timeVisible: true, borderColor: gridColor },
        rightPriceScale: { borderColor: gridColor },
    };

    // ── Main chart ──
    const mainEl = document.getElementById('lt-main-chart');
    mainEl.innerHTML = '';
    _ltChart = LightweightCharts.createChart(mainEl, { ...baseOpts, height: 380 });

    // Candlesticks
    const candleSeries = _ltChart.addCandlestickSeries({
        upColor: '#26a69a', downColor: '#ef5350',
        borderUpColor: '#26a69a', borderDownColor: '#ef5350',
        wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    });
    candleSeries.setData(data.candles);

    // SMA 50
    if (data.sma50?.length) {
        const s = _ltChart.addLineSeries({ color: '#f59e0b', lineWidth: 1, title: 'MA50' });
        s.setData(data.sma50);
    }
    // SMA 200
    if (data.sma200?.length) {
        const s = _ltChart.addLineSeries({ color: '#6366f1', lineWidth: 2, title: 'MA200' });
        s.setData(data.sma200);
    }
    // Bollinger Bands
    if (data.bb_upper?.length) {
        const upper = _ltChart.addLineSeries({ color: 'rgba(99,179,237,0.5)', lineWidth: 1, lineStyle: 2, title: 'BB+' });
        upper.setData(data.bb_upper);
        const lower = _ltChart.addLineSeries({ color: 'rgba(99,179,237,0.5)', lineWidth: 1, lineStyle: 2, title: 'BB-' });
        lower.setData(data.bb_lower);
        const mid = _ltChart.addLineSeries({ color: 'rgba(99,179,237,0.3)', lineWidth: 1, lineStyle: 3 });
        mid.setData(data.bb_mid);
    }
    // Fibonacci retracement lines
    if (data.fib_retracement) {
        const fibColors = { '0.236': '#a78bfa', '0.382': '#818cf8', '0.5': '#60a5fa', '0.618': '#34d399', '0.786': '#fbbf24' };
        for (const [lvl, price] of Object.entries(data.fib_retracement)) {
            if (lvl === '0.0' || lvl === '1.0') continue;
            const color = fibColors[lvl] || '#888';
            _ltChart.addLineSeries({
                color, lineWidth: 1, lineStyle: 2, title: `Fib ${lvl}`,
            }).setData(data.candles.map(c => ({ time: c.time, value: price })));
        }
    }

    // ── RSI chart ──
    const rsiEl = document.getElementById('lt-rsi-chart');
    rsiEl.innerHTML = '';
    _ltRsiChart = LightweightCharts.createChart(rsiEl, { ...baseOpts, height: 120 });
    const rsiSeries = _ltRsiChart.addLineSeries({ color: '#818cf8', lineWidth: 2, title: 'RSI 14' });
    rsiSeries.setData(data.rsi);
    // RSI 30/70 lines
    _ltRsiChart.addLineSeries({ color: 'rgba(52,211,153,0.5)', lineWidth: 1, lineStyle: 2 })
        .setData(data.rsi.map(d => ({ time: d.time, value: 30 })));
    _ltRsiChart.addLineSeries({ color: 'rgba(239,68,68,0.5)', lineWidth: 1, lineStyle: 2 })
        .setData(data.rsi.map(d => ({ time: d.time, value: 70 })));

    // ── MACD chart ──
    const macdEl = document.getElementById('lt-macd-chart');
    macdEl.innerHTML = '';
    _ltMacdChart = LightweightCharts.createChart(macdEl, { ...baseOpts, height: 100 });
    const macdLine = _ltMacdChart.addLineSeries({ color: '#60a5fa', lineWidth: 2, title: 'MACD' });
    macdLine.setData(data.macd_line);
    const macdSig = _ltMacdChart.addLineSeries({ color: '#f97316', lineWidth: 1, title: 'Signal' });
    macdSig.setData(data.macd_signal);
    const macdHist = _ltMacdChart.addHistogramSeries({ title: 'Hist' });
    macdHist.setData(data.macd_hist);

    // Sync time scales
    _ltChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        _ltRsiChart.timeScale().setVisibleLogicalRange(range);
        _ltMacdChart.timeScale().setVisibleLogicalRange(range);
    });

    _ltChart.timeScale().fitContent();
}

function renderIndicatorBadges(data) {
    const ind = data.indicators;
    const el = document.getElementById('lt-badges');
    if (!el) return;

    const rsiD = ind.rsi_daily;
    const rsiW = ind.rsi_weekly;
    const vs200 = ind.vs_200ma;
    const ath = ind.ath_pct;
    const corr = ind.btc_correlation;
    const score = ind.score;

    function rsiClass(v) {
        if (v < 30) return 'bg-success';
        if (v < 45) return 'bg-info text-dark';
        if (v > 70) return 'bg-danger';
        if (v > 55) return 'bg-warning text-dark';
        return 'bg-secondary';
    }
    function vs200Class(v) {
        if (v < -30) return 'bg-success';
        if (v < 0) return 'bg-info text-dark';
        if (v < 20) return 'bg-warning text-dark';
        return 'bg-danger';
    }
    function scoreClass(v) {
        if (v >= 70) return 'bg-success';
        if (v >= 50) return 'bg-warning text-dark';
        return 'bg-danger';
    }

    el.innerHTML = `
        <span class="badge ${rsiClass(rsiD)} me-1">RSI(D) ${rsiD}</span>
        ${rsiW !== null ? `<span class="badge ${rsiClass(rsiW)} me-1">RSI(W) ${rsiW}</span>` : ''}
        <span class="badge ${vs200Class(vs200)} me-1">vs 200MA ${vs200 > 0 ? '+' : ''}${vs200}%</span>
        <span class="badge bg-secondary me-1">Od ATH ${ath}%</span>
        ${corr !== null ? `<span class="badge bg-secondary me-1">BTC korr. ${corr}</span>` : ''}
        <span class="badge ${scoreClass(score)} fs-6 ms-2">Score ${score}/100</span>
        <span class="badge ${ind.macd_bull ? 'bg-success' : 'bg-danger'} me-1 ms-2">MACD ${ind.macd_bull ? '↑ Bull' : '↓ Bear'}</span>
    `;
}

function renderHalving(h) {
    const el = document.getElementById('lt-halving');
    if (!el || !h) return;
    const phaseColors = { early_bull: 'text-success', bull: 'text-warning', post_peak: 'text-danger', bear: 'text-info' };
    const color = phaseColors[h.phase] || 'text-secondary';
    el.innerHTML = `
        <div class="d-flex flex-wrap gap-3 align-items-center py-2 px-3 rounded" style="background:rgba(255,255,255,0.04);">
            <div><small class="text-muted">Zadnji BTC halving</small><br><strong>${h.last_date}</strong></div>
            <div><small class="text-muted">Sljedeći halving</small><br><strong>${h.next_date}</strong> (za ${h.months_to_next.toFixed(0)} mj.)</div>
            <div><small class="text-muted">Faza ciklusa</small><br><strong class="${color}">${h.phase_hr}</strong> (${h.months_since} mj. od halvinga)</div>
            <div class="flex-fill"><small class="text-muted">Historijski outlook</small><br><span class="${color}">${h.outlook}</span></div>
        </div>`;
}

function renderExplanation(text) {
    const el = document.getElementById('lt-explanation');
    if (!el) return;
    el.innerHTML = text.split('\n').map(line => {
        if (!line.trim()) return '<br>';
        return `<div class="mb-1">${line}</div>`;
    }).join('');
}

function destroyCharts() {
    if (_ltChart) { try { _ltChart.remove(); } catch(e){} _ltChart = null; }
    if (_ltRsiChart) { try { _ltRsiChart.remove(); } catch(e){} _ltRsiChart = null; }
    if (_ltMacdChart) { try { _ltMacdChart.remove(); } catch(e){} _ltMacdChart = null; }
}

// ── SCANNER ──────────────────────────────────────────────────────────────────

async function runScanner(force = false) {
    const scanBody = document.getElementById('lt-scan-body');
    const spinner = document.getElementById('lt-scan-spinner');
    const spinnerMsg = document.getElementById('lt-scan-spinner-msg');
    const errEl = document.getElementById('lt-scan-error');
    const wrap = document.getElementById('lt-scan-wrap');

    scanBody.innerHTML = '';
    errEl.style.display = 'none';
    wrap.style.display = 'none';
    spinner.style.display = 'block';
    document.getElementById('lt-scan-cache-note').style.display = 'none';

    try {
        // Check if cache already ready (no need to start)
        const pollCheck = await fetch('/api/long_term_scan/poll');
        const checkState = await pollCheck.json();

        if (checkState.ready && !force) {
            spinner.style.display = 'none';
            renderScanResults(checkState.data, checkState.age_min);
            return;
        }

        // Start scan in background
        await fetch('/api/long_term_scan/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({force})
        });

        // Poll until done
        let elapsed = 0;
        while (true) {
            await new Promise(r => setTimeout(r, 2500));
            elapsed += 2.5;
            if (spinnerMsg) spinnerMsg.textContent = `Skeniram top 25 coinova... ${elapsed.toFixed(0)}s`;

            const pollRes = await fetch('/api/long_term_scan/poll');
            const state = await pollRes.json();

            if (state.error) throw new Error(state.error);
            if (state.ready) {
                spinner.style.display = 'none';
                renderScanResults(state.data, state.age_min);
                return;
            }
            if (elapsed > 180) throw new Error('Timeout — pokušaj ponovo');
        }
    } catch (e) {
        spinner.style.display = 'none';
        errEl.textContent = `Greška: ${e.message}`;
        errEl.style.display = 'block';
    }
}

function renderScanResults(data, ageMins) {
    const scanBody = document.getElementById('lt-scan-body');
    const wrap = document.getElementById('lt-scan-wrap');
    const cacheNote = document.getElementById('lt-scan-cache-note');

    wrap.style.display = 'block';
    if (ageMins !== null) {
        cacheNote.textContent = `Podaci stari ${ageMins} min (osvježavaju se svaki sat)`;
        cacheNote.style.display = '';
    }

    function rC(v) {
        if (v < 30) return 'text-success fw-bold';
        if (v < 45) return 'text-info';
        if (v > 70) return 'text-danger fw-bold';
        return '';
    }
    function sC(v) {
        if (v >= 65) return 'text-success fw-bold';
        if (v >= 45) return 'text-warning';
        return 'text-danger';
    }

    scanBody.innerHTML = data.map(coin => {
        const rsiD = coin.rsi_daily;
        const rsiW = coin.rsi_weekly;
        const vs200 = coin.vs_200ma;
        const score = coin.score;
        return `<tr style="cursor:pointer;" onclick="window._ltOpenCoin('${coin.symbol}')">
            <td><strong>${coin.symbol.replace('/USDT','')}</strong></td>
            <td class="text-end">${coin.price}</td>
            <td class="text-center ${rC(rsiD)}">${rsiD}</td>
            <td class="text-center ${rsiW !== null ? rC(rsiW) : 'text-muted'}">${rsiW !== null ? rsiW : '—'}</td>
            <td class="text-center ${vs200 < 0 ? 'text-success' : 'text-danger'}">${vs200 > 0 ? '+' : ''}${vs200}%</td>
            <td class="text-center">${coin.ath_pct}%</td>
            <td class="text-center ${sC(score)} fs-6">${score}</td>
            <td>${coin.signal_hr}</td>
        </tr>`;
    }).join('');
}

// Called from inline onclick in scanner rows
window._ltOpenCoin = function(symbol) {
    const mainBtn = document.getElementById('tab-longterm-btn');
    const chartBtn = document.getElementById('lt-tab-chart-btn');
    if (mainBtn) mainBtn.click();
    setTimeout(() => {
        if (chartBtn) chartBtn.click();
        setTimeout(() => {
            const input = document.getElementById('lt-symbol');
            if (input) input.value = symbol;
            runLongTermAnalysis();
        }, 50);
    }, 100);
};
