from flask import request, redirect, url_for, flash, render_template
from flask_login import UserMixin, login_user, logout_user, current_user
from flask_bcrypt import Bcrypt

bcrypt = Bcrypt()

users = {'admin': {'password': bcrypt.generate_password_hash('password').decode('utf-8')}}

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
    return redirect(url_for('login'))
