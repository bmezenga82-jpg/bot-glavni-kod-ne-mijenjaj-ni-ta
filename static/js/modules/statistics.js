let chartInstance = null;

function fmt(n, dec = 2) {
    return Number(n).toLocaleString('hr-HR', { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

function loadChart() {
    const period = document.getElementById('chart-period').value;
    const symbol = document.getElementById('chart-symbol').value;
    const cumulative = document.getElementById('chart-cumulative').checked ? '1' : '0';

    fetch(`/api/stats/chart?period=${period}&symbol=${encodeURIComponent(symbol)}&cumulative=${cumulative}`)
        .then(r => r.json())
        .then(data => {
            // Popuni symbol dropdown samo pri prvom pozivu
            const symSelect = document.getElementById('chart-symbol');
            if (symSelect.options.length === 1 && data.symbols) {
                data.symbols.forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s;
                    opt.textContent = s;
                    symSelect.appendChild(opt);
                });
            }

            const ctx = document.getElementById('profit-chart').getContext('2d');
            if (chartInstance) chartInstance.destroy();

            const isCumulative = cumulative === '1';
            chartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: data.labels,
                    datasets: [{
                        label: isCumulative ? 'Kumulativni profit ($)' : 'Dnevni profit ($)',
                        data: data.values,
                        borderColor: '#6ea8fe',
                        backgroundColor: 'rgba(110,168,254,0.1)',
                        fill: true,
                        tension: 0.3,
                        pointRadius: data.labels.length > 60 ? 0 : 3,
                        borderWidth: 2,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { labels: { color: '#ccc' } },
                        tooltip: {
                            callbacks: {
                                label: ctx => ` ${fmt(ctx.parsed.y, 4)} $`
                            }
                        }
                    },
                    scales: {
                        x: { ticks: { color: '#aaa', maxTicksLimit: 12 }, grid: { color: '#333' } },
                        y: { ticks: { color: '#aaa', callback: v => fmt(v, 2) + ' $' }, grid: { color: '#333' } }
                    }
                }
            });
        })
        .catch(err => console.error('chart load error:', err));
}

function loadSummary() {
    fetch('/api/stats/summary')
        .then(r => r.json())
        .then(data => {
            const tbody = document.getElementById('stats-body');
            const tfoot = document.getElementById('stats-foot');
            tbody.innerHTML = '';

            if (!data.length) {
                tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">Nema podataka (još nema završenih sellova u real modu)</td></tr>';
                return;
            }

            let totalCycles = 0, totalProfit = 0;

            data.forEach(r => {
                totalCycles += r.cycles;
                totalProfit += r.total_profit;

                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>
                        <div class="fw-bold text-primary" style="font-size:0.85rem;">${r.symbol}</div>
                        <div class="text-warning" style="font-size:0.7rem;">${r.exchange}</div>
                    </td>
                    <td class="text-end">${r.cycles}</td>
                    <td class="text-end fw-bold" style="color:#6ea8fe;">${fmt(r.total_profit)} $</td>
                    <td class="text-end" style="color:#75b798;">${fmt(r.avg_profit, 4)} $</td>
                    <td class="text-end" style="color:#ea868f;">${fmt(r.profit_per_day, 4)} $</td>
                    <td class="text-end">${r.days_active}</td>
                    <td class="text-end text-muted" style="font-size:0.8rem;">${r.first_trade}</td>
                    <td class="text-center">
                        <button class="btn btn-outline-danger btn-sm py-0 px-1 delete-pair-btn"
                            data-symbol="${r.symbol}" data-exchange="${r.exchange}"
                            title="Obriši historiju">✕</button>
                    </td>`;
                tbody.appendChild(tr);
            });

            tbody.querySelectorAll('.delete-pair-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const symbol = btn.dataset.symbol;
                    const exchange = btn.dataset.exchange;
                    if (!confirm(`Obrisati svu historiju za ${symbol} (${exchange})?\nOva radnja je nepovratna.`)) return;
                    fetch('/api/stats/delete_pair', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ symbol, exchange })
                    })
                    .then(r => r.json())
                    .then(() => { loadSummary(); loadChart(); })
                    .catch(err => console.error('delete error:', err));
                });
            });

            tfoot.innerHTML = `
                <tr class="table-secondary fw-bold">
                    <td class="text-end text-uppercase small" colspan="1">Ukupno</td>
                    <td class="text-end">${totalCycles}</td>
                    <td class="text-end" style="color:#6ea8fe;">${fmt(totalProfit)} $</td>
                    <td colspan="5"></td>
                </tr>`;
        })
        .catch(err => console.error('summary load error:', err));
}

export function initStatistics() {
    loadChart();
    loadSummary();

    document.getElementById('chart-period').addEventListener('change', loadChart);
    document.getElementById('chart-symbol').addEventListener('change', loadChart);
    document.getElementById('chart-cumulative').addEventListener('change', loadChart);
}
