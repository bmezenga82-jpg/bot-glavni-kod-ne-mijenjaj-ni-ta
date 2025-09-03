export function toggleBot(pairId, symbol, exchange, mode, btnId = null) {
    const btn = document.getElementById(btnId || `control-btn-${pairId}`);
    const label = btn.innerText.trim();
    const action = label === 'Start' ? 'start' : 'stop';
    
    const startPromise = action === 'start'
        ? fetch('/api/clear_open_positions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol, exchange, trading_mode: mode })
          })
        : Promise.resolve();

    return startPromise.then(() => fetch('/api/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: action, pair_id: pairId })
    }))
    .then(response => {
        if (!response.ok) {
            throw new Error('Control API error: ' + response.statusText);
        }
        return response.json();
    })
    .then(data => {
        if (data.status && data.status.toLowerCase().includes('invalid')) {
            alert(data.status);
            throw new Error(data.status);
        }
        // Use the actual status from the backend response
        const isRunning = data.bot_is_running;
        btn.innerText = isRunning ? 'Stop' : 'Start';
        btn.classList.toggle('btn-success', !isRunning);
        btn.classList.toggle('btn-danger', isRunning);
        const editActionBtn = btnId ? document.getElementById("edit-" + btnId) : null;
        if (editActionBtn) {
            if (isRunning) { // Use isRunning here
                editActionBtn.classList.add("disabled");
            } else {
                editActionBtn.classList.remove("disabled");
            }
        }

        return data;
    })
    .catch(error => {
        const editActionBtn = btnId ? document.getElementById("edit-" + btnId) : null;
        if (editActionBtn) {
            editActionBtn.classList.remove("disabled");
        }
        alert('Trade error: ' + error.message);
        console.error('Error toggling bot:', error);
        throw error;
    });
}

export function updateAllBotStatuses() {
    fetch('/api/bot_statuses')
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to fetch bot statuses: ' + response.statusText);
            }
            return response.json();
        })
        .then(statuses => {
            for (const pairId in statuses) {
                const btn = document.getElementById(`action-${pairId}`);
                if (btn) {
                    const isRunning = statuses[pairId];
                    btn.innerText = isRunning ? 'Stop' : 'Start';
                    btn.classList.toggle('btn-success', !isRunning);
                    btn.classList.toggle('btn-danger', isRunning);

                    // Also update the edit button's disabled state
                    const editBtn = document.getElementById(`edit-action-${pairId}`);
                    if (editBtn) {
                        if (isRunning) {
                            editBtn.classList.add("disabled");
                        } else {
                            editBtn.classList.remove("disabled");
                        }
                    }
                }
            }
        })
        .catch(error => {
            console.error('Error updating bot statuses:', error);
            // Optionally, display a subtle error to the user that status updates might be delayed
        });
}
