import json
import os
import pandas as pd
from collections import defaultdict
from flask import jsonify

NOTIFICATIONS_FILE = 'notifications.json'

def load_notifications():
    if os.path.exists(NOTIFICATIONS_FILE):
        with open(NOTIFICATIONS_FILE, 'r') as f:
            return defaultdict(list, json.load(f))
    return defaultdict(list)

def save_notifications(notifications):
    with open(NOTIFICATIONS_FILE, 'w') as f:
        json.dump(dict(notifications), f)

notifications = load_notifications()

def add_notification(symbol, message, msg_type):
    notifications[symbol].append({
        'message': message,
        'type': msg_type,
        'timestamp': pd.Timestamp.now().isoformat()
    })
    save_notifications(notifications)

def get_notifications():
    return dict(notifications)

def clear_notifications():
    global notifications
    notifications.clear()
    save_notifications(notifications)
    return jsonify({'status': 'Notifications cleared'})
