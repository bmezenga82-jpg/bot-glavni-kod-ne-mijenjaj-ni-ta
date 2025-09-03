let currentPage = 1;
const itemsPerPage = 20; // Should match backend default or be configurable
let currentTimeframe = 'all';
let currentSort = 'timestamp';
export function loadProfitLogData(page = 1) {
    currentPage = page;
    fetch(`/api/profit_log_entries?page=${currentPage}&per_page=${itemsPerPage}&timeframe=${currentTimeframe}&sort=${currentSort}`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                console.error('Error loading profit log data:', data.error);
                const tbody = document.getElementById('profit-log-body');
                if (tbody) {
                    tbody.innerHTML = `<tr><td colspan="8">Error loading data: ${data.error}</td></tr>`;
                }
                return;
            }

            const tbody = document.getElementById('profit-log-body');
            if (!tbody) {
                console.error('profit-log-body element not found');
                return;
            }
            tbody.innerHTML = ''; // Clear existing rows
            if (!data.entries || data.entries.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8">No profit/loss entries found.</td></tr>';
                updatePaginationControls(data.total_pages || 0, data.current_page || 1);
                return;
            }

            data.entries.forEach(entry => {
                const row = document.createElement('tr');
                // Format numbers to a reasonable number of decimal places
                const buyPrice = typeof entry.buy_price === 'number' ? entry.buy_price.toFixed(4) : 'N/A';
                const sellPrice = typeof entry.sell_price === 'number' ? entry.sell_price.toFixed(4) : 'N/A';
                const assetQty = typeof entry.amount === 'number' ? entry.amount.toFixed(6) : 'N/A';
                const profit = typeof entry.profit_usdt === 'number' ? entry.profit_usdt.toFixed(2) : 'N/A';
                const timestamp = entry.timestamp ? new Date(entry.timestamp).toLocaleString() : 'N/A';

                row.innerHTML = `
                    <td>${timestamp}</td>
                    <td>${entry.symbol || 'N/A'}</td>
                    <td>${entry.exchange || 'N/A'}</td>
                    <td>${entry.trading_mode || 'N/A'}</td>
                    <td>${buyPrice}</td>
                    <td>${sellPrice}</td>
                    <td>${assetQty}</td>
                    <td class="${parseFloat(profit) >= 0 ? 'text-success' : 'text-danger'}">${profit}</td>
                `;
                tbody.appendChild(row);
            });

            updatePaginationControls(data.total_pages, data.current_page);
            // addSorting(); // Sorting might need to be re-evaluated or made server-side with pagination
        })
        .catch(error => {
            console.error('Error loading P/L data:', error);
            const tbody = document.getElementById('profit-log-body');
            if (tbody) {
                tbody.innerHTML = `<tr><td colspan="8">Error loading data. See console.</td></tr>`;
            }
        });
}

export function initTradesPage() {
    const timeframeSelect = document.getElementById('timeframe-select');
    if (timeframeSelect) {
        timeframeSelect.addEventListener('change', (e) => {
            currentTimeframe = e.target.value;
            loadProfitLogData(1);
        });
    }

    const sortSelect = document.getElementById('sort-select');
    if (sortSelect) {
        sortSelect.addEventListener('change', (e) => {
            currentSort = e.target.value;
            loadProfitLogData(1);
        });
    }

    const downloadBtn = document.getElementById('download-profit-btn');
    if (downloadBtn) {
        downloadBtn.addEventListener('click', () => {
            window.location.href = `/download_profit_log?timeframe=${currentTimeframe}&sort=${currentSort}`;
        });
    }

    const resetBtn = document.getElementById('reset-profit-btn');
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            currentTimeframe = 'all';
            currentSort = 'timestamp';
            if (timeframeSelect) timeframeSelect.value = 'all';
            if (sortSelect) sortSelect.value = 'timestamp';
            loadProfitLogData(1);
        });
    }
}

function updatePaginationControls(totalPages, currentPage) {
    const paginationControls = document.getElementById('pagination-controls');
    if (!paginationControls) return;

    paginationControls.innerHTML = ''; // Clear old controls

    if (totalPages <= 1) return; // No controls needed for a single page

    // Previous Button
    const prevLi = document.createElement('li');
    prevLi.classList.add('page-item');
    if (!currentPage || currentPage === 1) {
        prevLi.classList.add('disabled');
    }
    const prevA = document.createElement('a');
    prevA.classList.add('page-link');
    prevA.href = '#';
    prevA.innerText = 'Previous';
    prevA.addEventListener('click', (e) => {
        e.preventDefault();
        if (currentPage > 1) {
            loadProfitLogData(currentPage - 1);
        }
    });
    prevLi.appendChild(prevA);
    paginationControls.appendChild(prevLi);

    // Page Number Buttons (simplified: just current page, could be extended)
    // For simplicity, only show current page. A full pagination would show nearby pages.
    const currentLi = document.createElement('li');
    currentLi.classList.add('page-item', 'active');
    const currentA = document.createElement('a');
    currentA.classList.add('page-link');
    currentA.href = '#';
    currentA.innerText = currentPage;
    currentLi.appendChild(currentA);
    paginationControls.appendChild(currentLi);

    // Next Button
    const nextLi = document.createElement('li');
    nextLi.classList.add('page-item');
    if (!currentPage || currentPage === totalPages) {
        nextLi.classList.add('disabled');
    }
    const nextA = document.createElement('a');
    nextA.classList.add('page-link');
    nextA.href = '#';
    nextA.innerText = 'Next';
    nextA.addEventListener('click', (e) => {
        e.preventDefault();
        if (currentPage < totalPages) {
            loadProfitLogData(currentPage + 1);
        }
    });
    nextLi.appendChild(nextA);
    paginationControls.appendChild(nextLi);
}


// Client-side sorting is problematic with pagination.
// For now, sorting will be disabled. If needed, it should be implemented server-side
// by passing sort parameters to the API.
/*
function addSorting() {
    const headers = document.querySelectorAll('#profit-log-table th[data-sort]'); // Target new table ID
    headers.forEach(header => {
        header.addEventListener('click', () => {
            const key = header.getAttribute('data-sort');
            sortTable(key);
        });
    });
}

function sortTable(key) {
    const tbody = document.getElementById('profit-log-body'); // Target new tbody ID
    const rows = Array.from(tbody.getElementsByTagName('tr'));

    // Define which keys are numeric for proper sorting.
    // Adjust based on the new P/L table columns.
    const numericKeys = ['buy_price', 'sell_price', 'amount', 'profit_usdt'];
    const isNumeric = numericKeys.includes(key);

    // Map keys to their respective cell indices in the new P/L table.
    const indexMap = {
        timestamp: 0,
        symbol: 1,
        exchange: 2,
        trading_mode: 3,
        buy_price: 4,
        sell_price: 5,
        amount: 6, // Asset Qty
        profit_usdt: 7
    };
    const cellIndex = indexMap[key];

    if (typeof cellIndex === 'undefined') {
        console.warn(`Sorting key "${key}" not found in indexMap.`);
        return;
    }

    rows.sort((a, b) => {
        const aText = a.cells[cellIndex].textContent;
        const bText = b.cells[cellIndex].textContent;

        const aValue = isNumeric ? parseFloat(aText) || 0 : aText.toLowerCase();
        const bValue = isNumeric ? parseFloat(bText) || 0 : bText.toLowerCase();

        if (aValue < bValue) return -1;
        if (aValue > bValue) return 1;
        return 0;
    });
    rows.forEach(row => tbody.appendChild(row));
}
*/
