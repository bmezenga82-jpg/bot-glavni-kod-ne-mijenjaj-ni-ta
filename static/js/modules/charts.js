export function renderProfitChart() {
    fetch('/api/profit_data')
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                console.error('Error fetching profit data:', data.error);
                return;
            }
            const ctx = document.getElementById('profitChart').getContext('2d');
            new Chart(ctx, {
                type: 'line',
                data: {
                    labels: data.timestamps,
                    datasets: [{
                        label: 'Cumulative Profit (USDC)',
                        data: data.profits,
                        borderColor: '#F28C38',
                        backgroundColor: 'rgba(242, 140, 56, 0.2)',
                        borderWidth: 2,
                        fill: true
                    }]
                },
                options: {
                    scales: {
                        x: {
                            title: {
                                display: true,
                                text: 'Timestamp (EAT)',
                                color: document.documentElement.className === 'dark' ? '#FFFFFF' : '#000000'
                            },
                            ticks: {
                                color: document.documentElement.className === 'dark' ? '#FFFFFF' : '#000000'
                            }
                        },
                        y: {
                            title: {
                                display: true,
                                text: 'Profit (USDC)',
                                color: document.documentElement.className === 'dark' ? '#FFFFFF' : '#000000'
                            },
                            ticks: {
                                color: document.documentElement.className === 'dark' ? '#FFFFFF' : '#000000'
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            labels: {
                                color: document.documentElement.className === 'dark' ? '#FFFFFF' : '#000000'
                            }
                        }
                    }
                }
            });
        })
        .catch(error => console.error('Error rendering chart:', error));
}
