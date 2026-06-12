import json
import os
import secrets
from datetime import datetime, timedelta
from flask import request, redirect, url_for, flash, render_template
from flask_login import UserMixin, login_user, logout_user, current_user
from flask_bcrypt import Bcrypt

bcrypt = Bcrypt()

_KEY_FILE = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'api_keys.json'))


def _load_users():
    try:
        with open(_KEY_FILE) as f:
            keys = json.load(f)
        pw = keys.get('admin_password_hash')
        if pw:
            return {'admin': {'password': pw}}
    except Exception:
        pass
    return {'admin': {'password': bcrypt.generate_password_hash('password').decode('utf-8')}}


users = _load_users()


def _persist_password(hashed: str):
    try:
        try:
            with open(_KEY_FILE) as f:
                keys = json.load(f)
        except Exception:
            keys = {}
        keys['admin_password_hash'] = hashed
        with open(_KEY_FILE, 'w') as f:
            json.dump(keys, f, indent=2)
    except Exception:
        pass

# {token: {'username': str, 'expires': datetime}}
_reset_tokens = {}

class User(UserMixin):
    def __init__(self, username):
        self.id = username

def load_user(username):
    return User(username) if username in users else None

def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in users and bcrypt.check_password_hash(users[username]['password'], password):
            user = User(username)
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('home'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login_route'))

def generate_reset_token(username):
    token = secrets.token_urlsafe(32)
    _reset_tokens[token] = {'username': username, 'expires': datetime.utcnow() + timedelta(hours=1)}
    return token

def validate_reset_token(token):
    entry = _reset_tokens.get(token)
    if not entry:
        return None
    if datetime.utcnow() > entry['expires']:
        del _reset_tokens[token]
        return None
    return entry['username']

def consume_reset_token(token, new_password):
    username = validate_reset_token(token)
    if not username:
        return False
    hashed = bcrypt.generate_password_hash(new_password).decode('utf-8')
    users[username]['password'] = hashed
    _persist_password(hashed)
    del _reset_tokens[token]
    return True
