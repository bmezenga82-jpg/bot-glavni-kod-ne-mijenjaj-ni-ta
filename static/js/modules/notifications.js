export const seenNotifications = new Set();

export function updateNotifications() {
    return fetch('/api/notifications')
        .then(response => response.json())
        .then(data => {
            const countEl = document.getElementById('notification-count');
            const list = document.getElementById('notification-list');
            if (countEl) {
                const count = Object.values(data).flat().length;
                countEl.textContent = count;
            }
            if (list) {
                list.innerHTML = '';
                for (const [symbol, messages] of Object.entries(data)) {
                    messages.forEach(msg => {
                        const id = `${symbol}-${msg.timestamp}`;
                        if (!seenNotifications.has(id)) {
                            seenNotifications.add(id);
                            if (msg.type === 'error') {
                                alert(`${symbol}: ${msg.message}`);
                            }
                        }
                        const li = document.createElement('li');
                        li.innerHTML = `<a class="dropdown-item ${msg.type === 'error' ? 'text-danger' : 'text-success'}">${symbol}: ${msg.message}</a>`;
                        list.appendChild(li);
                    });
                }
                const divider = document.createElement('li');
                divider.innerHTML = '<hr class="dropdown-divider">';
                list.appendChild(divider);
                const clearLi = document.createElement('li');
                clearLi.innerHTML = '<a class="dropdown-item text-center" href="#">Clear All</a>';
                clearLi.addEventListener('click', clearNotifications);
                list.appendChild(clearLi);
            }
            return data;
        })
        .catch(error => {
            console.error('Error fetching notifications:', error);
            return {};
        });
}

export function clearNotifications() {
    return fetch('/clear_notifications', { method: 'POST' })
        .then(response => response.json())
        .then(() => {
            seenNotifications.clear();
            return updateNotifications();
        })
        .catch(error => {
            console.error('Error clearing notifications:', error);
        });
}

export function startNotificationPolling(interval = 10000) {
    updateNotifications();
    setInterval(updateNotifications, interval);
}

// Auto start if navbar is present
if (document.getElementById('notification-dropdown')) {
    startNotificationPolling();
}
