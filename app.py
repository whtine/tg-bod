# Импорт библиотек
from flask import Flask, request, abort
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
app = Flask(__name__)

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

# Подключение к базе
def get_db_connection():
    logger.info("Подключение к базе")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        logger.info("База подключена")
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения: {e}")
        return None

# Инициализация базы
def init_db():
    logger.info("Инициализация базы")
    conn = get_db_connection()
    if conn is None:
        logger.error("База недоступна")
        return False
    try:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                chat_id TEXT PRIMARY KEY,
                prefix TEXT,
                subscription_end TEXT,
                username TEXT
            )
        ''')
        c.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users'")
        columns = [row[0] for row in c.fetchall()]
        if 'last_activity' not in columns:
            logger.info("Добавление last_activity")
            c.execute('ALTER TABLE users ADD COLUMN last_activity TEXT')
        if 'ip_hash' not in columns:
            logger.info("Добавление ip_hash")
            c.execute('ALTER TABLE users ADD COLUMN ip_hash TEXT')
        if 'username' not in columns:
            logger.info("Добавление username")
            c.execute('ALTER TABLE users ADD COLUMN username TEXT')
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
        c.execute("DELETE FROM credentials")
        c.execute("DELETE FROM hacked_accounts")
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
    if conn is None:
        if chat_id == ADMIN_CHAT_ID:
            logger.info("Админ без базы")
            return {
                'prefix': 'Создатель',
                'subscription_end': get_current_time() + timedelta(days=3650),
                'last_activity': get_current_time().isoformat(),
                'ip_hash': hash_data(chat_id),
                'username': '@sacoectasy'
            }
        logger.warning("База недоступна")
        return None
    try:
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
                'subscription_end': datetime.fromisoformat(result[1]) if result[1] else None,
                'last_activity': result[2],
                'ip_hash': result[3],
                'username': result[4]
            }
        logger.warning(f"Пользователь {chat_id} не найден")
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
    if conn is None:
        logger.error("База недоступна")
        return
    try:
        c = conn.cursor()
        subscription_end = subscription_end or get_current_time().isoformat()
        ip_hash = hash_data(ip or chat_id)
        last_activity = get_current_time().isoformat()
        c.execute(
            '''
            INSERT INTO users (chat_id, prefix, subscription_end, last_activity, ip_hash, username)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (chat_id) DO UPDATE
            SET prefix = %s,
                subscription_end = %s,
                last_activity = %s,
                ip_hash = %s,
                username = %s
            ''',
            (chat_id, prefix, subscription_end, last_activity, ip_hash, username,
             prefix, subscription_end, last_activity, ip_hash, username)
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
    if tech_mode and chat_id != ADMIN_CHAT_ID:
        end_time_str = format_time(tech_end_time)
        logger.warning(f"Тех. режим: {chat_id}")
        return (
            f"🛠 *Бот на техническом перерыве!*\n"
            f"📝 *Причина*: {tech_reason or 'Не указана'}\n"
            f"🕒 *Окончание*: {end_time_str}\n"
            f"Попробуйте позже."
        )
    user = get_user(chat_id)
    if user is None:
        if command in ['menu', 'support'] and not tech_mode:
            logger.info(f"Регистрация {chat_id}")
            save_user(chat_id, "Посетитель", username="Неизвестно")
            return None
        logger.warning(f"Нет доступа: {chat_id}, {command}")
        return "💳 *Купить подписку у @sacoectasy!*"
    if user['subscription_end'] and user['subscription_end'] < get_current_time():
        logger.info(f"Подписка истекла: {chat_id}")
        save_user(chat_id, 'Посетитель', get_current_time().isoformat(), chat_id, user['username'])
        return "💳 *Подписка истекла! Обратитесь к @sacoectasy.*"
    if user['prefix'] == 'Посетитель':
        if command in ['menu', 'support'] and not tech_mode:
            logger.debug(f"Разрешён {command}")
            return None
        logger.warning(f"Запрещён {command} для Посетителя")
        return "💳 *Купить подписку у @sacoectasy!*"
    if command in ['passwords', 'hacked', 'getchatid', 'site']:
        logger.debug(f"Разрешён {command}")
        return None
    if command == 'database' and user['prefix'] in ['Админ', 'Создатель']:
        logger.debug(f"Разрешён {command} для {user['prefix']}")
        return None
    if command in ['techstop', 'techstopoff', 'adprefix', 'delprefix', 'adduser', 'addcred', 'addhacked', 'broadcast', 'admin']:
        if user['prefix'] != 'Создатель':
            logger.warning(f"Админ-команда {command} от {chat_id}")
            return "🔒 *Эта команда только для Создателя!*"
    logger.debug(f"Разрешён {command}")
    return None

# Очистка ввода
def sanitize_input(text):
    if not text:
        return text
    dangerous_chars = [';', '--', '/*', '*/', 'DROP', 'SELECT', 'INSERT', 'UPDATE', 'DELETE']
    for char in dangerous_chars:
        text = text.replace(char, '')
    logger.debug(f"Очищен: {text}")
    return text

# Список пользователей
def get_all_users():
    logger.info("Запрос пользователей")
    conn = get_db_connection()
    if conn is None:
        logger.error("База недоступна")
        return []
    try:
        c = conn.cursor()
        c.execute("SELECT chat_id, prefix, username FROM users")
        users = c.fetchall()
        logger.info(f"Найдено {len(users)}")
        return users
    except Exception as e:
        logger.error(f"Ошибка пользователей: {e}")
        return []
    finally:
        conn.close()

# Статус бота
def check_bot_status():
    logger.info("Проверка статуса")
    try:
        bot.get_me()
        logger.info("Бот активен")
        return True
    except Exception as e:
        logger.error(f"Бот не отвечает: {e}")
        return False

# Главная страница
@app.route('/')
def index():
    logger.info("Запрос на /")
    if check_bot_status():
        return "Bot is running!", 200
    logger.error("Бот не отвечает")
    return "Bot is down!", 500

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
        bot.process_new_updates([update])
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
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        if user is None:
            save_user(chat_id, "Посетитель", ip=message.from_user.id, username=username)
        else:
            save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id, username)
    except Exception as e:
        logger.error(f"Ошибка /start: {e}")

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
        save_user(chat_id, "Посетитель", ip=message.from_user.id, username=username)
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
        )
    if prefix in ["Админ", "Создатель"]:
        response += f"🗄 /database — Управление базой данных\n"
    if prefix == "Создатель":
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
        logger.info(f"Ответ: {response}")
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id, username)
    except Exception as e:
        logger.error(f"Ошибка /menu: {e}")

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
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id, username)
    except Exception as e:
        logger.error(f"Ошибка /getchatid: {e}")

# /support
@bot.message_handler(commands=['support'])
def support_cmd(message):
    chat_id = str(message.chat.id)
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
        bot.register_next_step_handler(msg, process_support_message)
        logger.info(f"Запрошена проблема от {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка /support: {e}")

def process_support_message(message):
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
            f"📩 *Сообщение в поддержку*\n👤 *От*: {chat_id}\n📜 *Текст*: {text}",
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
    response = (
        "🌐 *Наш официальный сайт*\n"
        "Связь и дополнительная информация: [@sacoectasy](https://t.me/sacoectasy)"
    )
    try:
        bot.reply_to(message, response, parse_mode='Markdown')
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id, username)
    except Exception as e:
        logger.error(f"Ошибка /site: {e}")

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
                f"🕒 *Добавлено*: {format_time(datetime.fromisoformat(hack_date)) if hack_date else 'Неизвестно'}\n\n"
            )
        bot.reply_to(message, response, parse_mode='Markdown')
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id, username)
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
                f"🕒 *Добавлено*: {format_time(datetime.fromisoformat(added_time)) if added_time else 'Неизвестно'}\n\n"
            )
        bot.reply_to(message, response, parse_mode='Markdown')
        user = get_user(chat_id)
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("➕ Добавить в hacked", callback_data="add_to_hacked")
        )
        if user['prefix'] in ["Админ", "Создатель"]:
            keyboard.add(
                types.InlineKeyboardButton("🗑 Удалить пароль", callback_data="delete_cred")
            )
        bot.send_message(
            chat_id,
            "⚙️ *Выберите действие*:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        logger.info(f"Ответ: {response}")
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id, username)
    except Exception as e:
        logger.error(f"Ошибка /passwords: {e}")
        bot.reply_to(message, "❌ *Ошибка при загрузке данных!*", parse_mode='Markdown')
    finally:
        conn.close()

# Кнопки /passwords
@bot.callback_query_handler(func=lambda call: call.data in ['add_to_hacked', 'delete_cred'])
def handle_passwords_buttons(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Кнопка {call.data} от {chat_id}")
    if check_access(chat_id, 'passwords'):
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "🔒 *Доступ запрещён!*", parse_mode='Markdown')
            logger.warning(f"Доступ запрещён")
        except Exception as e:
            logger.error(f"Ошибка кнопки: {e}")
        return
    user = get_user(chat_id)
    if call.data == 'add_to_hacked':
        if user['prefix'] not in ['Админ', 'Создатель']:
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
    elif call.data == 'delete_cred':
        if user['prefix'] not in ['Админ', 'Создатель']:
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
        types.InlineKeyboardButton("✅ Прод",[УДАЛЕНО] callback_data=f"hacked_status_sold_{login}_{new_password}"),
        types.InlineKeyboardButton("⛔ Непродан", callback_data=f"hacked_status_not_sold_{login}_{new_password}")
    )
    try:
        bot.reply_to(message, "📊 *Выберите статус аккаунта*:", reply_markup=keyboard, parse_mode='Markdown')
        logger.info(f"Запрошен статус для {login}")
    except Exception as e:
        logger.error(f"Ошибка статуса: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('hacked_status_'))
def handle_hacked_status(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Статус {call.data} от {chat_id}")
    if check_access(chat_id, 'passwords'):
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "🔒 *Доступ запрещён!*", parse_mode='Markdown')
            logger.warning(f"Доступ запрещён")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    _, status, login, password = call.data.split('_', 3)
    sold_status = "Продан" if status == "sold" else "Непродан"
    conn = get_db_connection()
    if conn is None:
        try:
            bot.send_message(chat_id, "❌ *База данных недоступна!*", parse_mode='Markdown')
            logger.error("База недоступна")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO hacked_accounts (login, password, hack_date, prefix, sold_status, linked_chat_id)
            VALUES (%s, %s, %s, %s, %s, %s)
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
        logger.info(f"Добавлен: {login}, {sold_status}")
    except Exception as e:
        logger.error(f"Ошибка hacked: {e}")
        bot.send_message(chat_id, "❌ *Ошибка добавления!*", parse_mode='Markdown')
    finally:
        conn.close()
    try:
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка кнопки: {e}")

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
        "💻 /hacked — Просмотр взломанных аккаунтов\n"
        "🔑 /passwords — Управление паролями\n"
        "🗄 /database — Управление базой данных\n"
        "🚨 /techstop — Включить техперерыв\n"
        "✅ /techstopoff — Выключить техперерыв\n"
        "📢 /broadcast — Отправить рассылку\n"
        "👑 /adprefix — Выдать подписку\n"
        "🗑 /delprefix — Сбросить подписку\n"
        "➕ /adduser — Добавить пользователя\n"
        "🔐 /addcred — Добавить пароль\n"
        "💾 /addhacked — Добавить взломанный аккаунт\n"
    )
    try:
        bot.reply_to(message, response, parse_mode='Markdown')
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id, username)
    except Exception as e:
        logger.error(f"Ошибка /admin: {e}")
        bot.reply_to(message, "❌ *Ошибка загрузки панели!*", parse_mode='Markdown')

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
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id, username)
    except Exception as e:
        logger.error(f"Ошибка /database: {e}")
        bot.reply_to(message, "❌ *Ошибка загрузки!*", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data in ['db_add', 'db_delete'])
def handle_database_buttons(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Кнопка {call.data} от {chat_id}")
    if check_access(chat_id, 'database'):
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "🔒 *Доступ запрещён!*", parse_mode='Markdown')
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
    elif call.data == 'db_delete':
        try:
            msg = bot.send_message(chat_id, "📝 *Введите логин для удаления*:", parse_mode='Markdown')
            bot.register_next_step_handler(msg, process_db_delete)
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошено удаление")
        except Exception as e:
            logger.error(f"Ошибка db_delete: {e}")

@bot.callback_query_handler(func=lambda call: call.data in ['db_add_hacked', 'db_add_cred', 'db_add_user'])
def handle_db_add_buttons(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Кнопка {call.data} от {chat_id}")
    if check_access(chat_id, 'database'):
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "🔒 *Доступ запрещён!*", parse_mode='Markdown')
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
    elif call.data == 'db_add_cred':
        try:
            msg = bot.send_message(chat_id, "📝 *Введите логин для credentials*:", parse_mode='Markdown')
            bot.register_next_step_handler(msg, process_add_cred_login)
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошен логин для credentials")
        except Exception as e:
            logger.error(f"Ошибка db_add_cred: {e}")
    elif call.data == 'db_add_user':
        try:
            msg = bot.send_message(
                chat_id,
                "📝 *Введите chat_id и префикс (через пробел)*:",
                parse_mode='Markdown'
            )
            bot.register_next_step_handler(msg, process_add_user)
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошен пользователь")
        except Exception as e:
            logger.error(f"Ошибка db_add_user: {e}")

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
        bot.reply_to(message, "❌ *Ошибка запроса!*", parse_mode='Markdown')

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
        logger.info(f"Техперерыв: {tech_reason}, до {format_time(tech_end_time)}")
        user = get_user(chat_id)
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id, username)
    except ValueError:
        logger.warning("Неверный формат")
        bot.reply_to(
            message,
            "❌ *Формат: Причина Часы (например: Обновление 2)*",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка техперерыва: {e}")
        bot.reply_to(message, "❌ *Ошибка активации!*", parse_mode='Markdown')

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
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id, username)
    except Exception as e:
        logger.error(f"Ошибка /techstopoff: {e}")
        bot.reply_to(message, "❌ *Ошибка отключения!*", parse_mode='Markdown')

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
        bot.reply_to(message, "❌ *Ошибка запроса!*", parse_mode='Markdown')

def process_adprefix(message):
    chat_id = str(message.chat.id)
    try:
        target_id, prefix = sanitize_input(message.text).split()
        subscription_end = (get_current_time() + timedelta(days=30)).isoformat()
        user = get_user(target_id)
        username = user['username'] if user else "Неизвестно"
        save_user(target_id, prefix, subscription_end, target_id, username)
        bot.reply_to(
            message,
            f"✅ *Подписка выдана для `{target_id}`!*\n🔑 *Префикс*: `{prefix}`",
            parse_mode='Markdown'
        )
        logger.info(f"Подписка: {target_id}, {prefix}")
    except ValueError:
        logger.warning("Неверный формат")
        bot.reply_to(
            message,
            "❌ *Формат: chat_id префикс*",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка префикса: {e}")
        bot.reply_to(message, "❌ *Ошибка обработки!*", parse_mode='Markdown')

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
        msg = bot.reply_to(message, "📝 *Введите chat_id*:", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_delprefix)
        logger.info(f"Запрошено удаление префикса")
    except Exception as e:
        logger.error(f"Ошибка /delprefix: {e}")
        bot.reply_to(message, "❌ *Ошибка запроса!*", parse_mode='Markdown')

def process_delprefix(message):
    chat_id = str(message.chat.id)
    target_id = sanitize_input(message.text)
    logger.info(f"Сброс: {target_id}")
    if not target_id:
        try:
            bot.reply_to(message, "❌ *ID не может быть пустым!*", parse_mode='Markdown')
            logger.warning("Пустой ID")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    user = get_user(target_id)
    username = user['username'] if user else "Неизвестно"
    save_user(target_id, "Посетитель", get_current_time().isoformat(), target_id, username)
    try:
        bot.reply_to(
            message,
            f"✅ *Подписка для `{target_id}` сброшена до `Посетитель`!*",
            parse_mode='Markdown'
        )
        logger.info(f"Сброшено: {target_id}")
    except Exception as e:
        logger.error(f"Ошибка сброса: {e}")
        bot.reply_to(message, "❌ *Ошибка обработки!*", parse_mode='Markdown')

# /adduser
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
            "📝 *Введите chat_id и префикс (через пробел)*:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_add_user)
        logger.info(f"Запрошен пользователь")
    except Exception as e:
        logger.error(f"Ошибка /adduser: {e}")
        bot.reply_to(message, "❌ *Ошибка запроса!*", parse_mode='Markdown')

def process_add_user(message):
    chat_id = str(message.chat.id)
    try:
        target_id, prefix = sanitize_input(message.text).split()
        save_user(target_id, prefix, get_current_time().isoformat(), target_id, "Неизвестно")
        bot.reply_to(
            message,
            f"✅ *Пользователь `{target_id}` добавлен!*\n🔑 *Префикс*: `{prefix}`",
            parse_mode='Markdown'
        )
        logger.info(f"Добавлен: {target_id}, {prefix}")
    except ValueError:
        logger.warning("Неверный формат")
        bot.reply_to(
            message,
            "❌ *Формат: chat_id префикс*",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка добавления: {e}")
        bot.reply_to(message, "❌ *Ошибка обработки!*", parse_mode='Markdown')

# /addcred
@bot.message_handler(commands=['addcred'])
def addcred_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/addcred от {chat_id}")
    access = check_access(chat_id, 'addcred')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /addcred: {e}")
        return
    try:
        msg = bot.reply_to(
            message,
            "📝 *Введите логин для credentials*:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_add_cred_login)
        logger.info(f"Запрошен логин")
    except Exception as e:
        logger.error(f"Ошибка /addcred: {e}")
        bot.reply_to(message, "❌ *Ошибка запроса!*", parse_mode='Markdown')

def process_add_cred_login(message):
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Логин: {login}")
    if not login:
        try:
            bot.reply_to(message, "❌ *Логин не может быть пустым!*", parse_mode='Markdown')
            logger.warning("Пустой логин")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        msg = bot.reply_to(message, "🔒 *Введите пароль*:", parse_mode='Markdown')
        bot.register_next_step_handler(msg, lambda m: process_add_cred_password(m, login))
        logger.info(f"Запрошен пароль")
    except Exception as e:
        logger.error(f"Ошибка логина: {e}")
        bot.reply_to(message, "❌ *Ошибка запроса!*", parse_mode='Markdown')

def process_add_cred_password(message, login):
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
        c.execute(
            '''
            INSERT INTO credentials (login, password, added_time, added_by)
            VALUES (%s, %s, %s, %s)
            ''',
            (login, password, get_current_time().isoformat(), chat_id)
        )
        conn.commit()
        bot.reply_to(
            message,
            f"✅ *Пароль для `{login}` успешно добавлен!*",
            parse_mode='Markdown'
        )
        logger.info(f"Добавлен: {login}")
    except Exception as e:
        logger.error(f"Ошибка добавления: {e}")
        bot.reply_to(message, "❌ *Ошибка добавления!*", parse_mode='Markdown')
    finally:
        conn.close()

# /addhacked
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
            "📝 *Введите логин для hacked*:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_add_hacked_login)
        logger.info(f"Запрошен логин")
    except Exception as e:
        logger.error(f"Ошибка /addhacked: {e}")
        bot.reply_to(message, "❌ *Ошибка запроса!*", parse_mode='Markdown')

def process_add_hacked_login(message):
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Логин: {login}")
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
        logger.info(f"Запрошен пароль")
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
        types.InlineKeyboardButton("✅ Продан", callback_data=f"hacked_status_sold_{login}_{password}"),
        types.InlineKeyboardButton("⛔ Непродан", callback_data=f"hacked_status_not_sold_{login}_{password}")
    )
    try:
        bot.reply_to(
            message,
            "📊 *Выберите статус аккаунта*:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        logger.info(f"Запрошен статус")
    except Exception as e:
        logger.error(f"Ошибка статуса: {e}")
        bot.reply_to(message, "❌ *Ошибка обработки!*", parse_mode='Markdown')

# /broadcast
@bot.message_handler(commands=['broadcast'])
def broadcast_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/broadcast от {chat_id}")
    access = check_access(chat_id, 'broadcast')
    if access:
        try:
            bot.reply_to(message, access, parse_mode='Markdown')
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /broadcast: {e}")
        return
    try:
        msg = bot.reply_to(
            message,
            "📢 *Введите текст для рассылки*:",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, lambda m: process_broadcast_message(m, username))
        logger.info(f"Запрошен текст")
    except Exception as e:
        logger.error(f"Ошибка /broadcast: {e}")
        bot.reply_to(message, "❌ *Ошибка запроса!*", parse_mode='Markdown')

def process_broadcast_message(message, sender_username):
    chat_id = str(message.chat.id)
    text = sanitize_input(message.text)
    logger.info(f"Текст: {text}")
    if not text:
        try:
            bot.reply_to(message, "❌ *Сообщение не может быть пустым!*", parse_mode='Markdown')
            logger.warning("Пустое сообщение")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    if any(keyword in text.lower() for keyword in ad_keywords):
        try:
            bot.reply_to(message, "🚫 *Сообщение содержит запрещённые слова!*", parse_mode='Markdown')
            logger.warning(f"Реклама: {text}")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    users = get_all_users()
    if not users:
        try:
            bot.reply_to(message, "📢 *Нет пользователей для рассылки!*", parse_mode='Markdown')
            logger.info("Нет пользователей")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    response = (
        f"📢 *Подтвердите рассылку*\n"
        f"👤 *Отправитель*: @{sender_username}\n"
        f"📜 *Текст*:\n{text}\n\n"
        f"👥 *Получателей*: {len(users)}\n"
        f"Нажмите ниже для подтверждения или отмены:"
    )
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ Отправить", callback_data=f"broadcast_confirm_{text}"),
        types.InlineKeyboardButton("⛔ Отменить", callback_data="broadcast_cancel")
    )
    try:
        bot.reply_to(message, response, reply_markup=keyboard, parse_mode='Markdown')
        logger.info(f"Запрошено подтверждение")
    except Exception as e:
        logger.error(f"Ошибка подтверждения: {e}")
        bot.reply_to(message, "❌ *Ошибка обработки!*", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('broadcast_'))
def handle_broadcast_buttons(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Кнопка {call.data} от {chat_id}")
    if check_access(chat_id, 'broadcast'):
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "🔒 *Доступ запрещён!*", parse_mode='Markdown')
            logger.warning(f"Доступ запрещён")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    if call.data == 'broadcast_cancel':
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="❌ *Рассылка отменена!*",
                parse_mode='Markdown'
            )
            bot.answer_callback_query(call.id)
            logger.info(f"Рассылка отменена: {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка отмены: {e}")
            bot.send_message(chat_id, "❌ *Ошибка отмены!*", parse_mode='Markdown')
        return
    if call.data.startswith('broadcast_confirm_'):
        text = call.data.replace('broadcast_confirm_', '', 1)
        users = get_all_users()
        success_count = 0
        fail_count = 0
        logger.info(f"Рассылка для {len(users)}")
        for user_id, _, _ in users:
            try:
                bot.send_message(
                    user_id,
                    f"📢 *Сообщение от Создателя*:\n{text}",
                    parse_mode='Markdown'
                )
                success_count += 1
                logger.debug(f"Отправлено {user_id}")
                time.sleep(0.05)
            except Exception as e:
                logger.error(f"Ошибка {user_id}: {e}")
                fail_count += 1
        response = (
            f"📢 *Рассылка завершена!*\n"
            f"✅ *Успешно*: {success_count}\n"
            f"❌ *Ошибки*: {fail_count}"
        )
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=response,
                parse_mode='Markdown'
            )
            bot.answer_callback_query(call.id)
            logger.info(f"Рассылка: {success_count} ок, {fail_count} ошибок")
        except Exception as e:
            logger.error(f"Ошибка результата: {e}")
            bot.send_message(chat_id, "❌ *Ошибка завершения!*", parse_mode='Markdown')

# Неизвестные команды
@bot.message_handler(func=lambda message: True)
def unknown_command(message):
    chat_id = str(message.chat.id)
    text = sanitize_input(message.text.lower())
    logger.info(f"Неизвестно от {chat_id}: {text}")
    if any(keyword in text for keyword in ad_keywords):
        logger.warning(f"Реклама: {text}")
        try:
            bot.reply_to(message, "🚫 *Реклама заблокирована!*", parse_mode='Markdown')
            bot.send_message(
                ADMIN_CHAT_ID,
                f"🚨 *Попытка рекламы*\n👤 *От*: {chat_id}\n📜 *Текст*: {text}",
                parse_mode='Markdown'
            )
            logger.info("Реклама заблокирована")
        except Exception as e:
            logger.error(f"Ошибка блокировки: {e}")
        return
    response = (
        "❌ *Неизвестная команда!*\n"
        "📖 Используйте /menu для списка команд."
    )
    try:
        bot.reply_to(message, response, parse_mode='Markdown')
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        if user:
            username = sanitize_input(message.from_user.username) or "Неизвестно"
            save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id, username)
    except Exception as e:
        logger.error(f"Ошибка ответа: {e}")

# Мониторинг
def monitor_activity():
    logger.info("Запуск мониторинга")
    while True:
        try:
            conn = get_db_connection()
            if conn:
                c = conn.cursor()
                c.execute(
                    "SELECT chat_id, last_activity FROM users WHERE last_activity < %s",
                    ((get_current_time() - timedelta(days=30)).isoformat(),)
                )
                inactive = c.fetchall()
                for user_id, last_activity in inactive:
                    logger.info(f"Неактивен {user_id}: {last_activity}")
                conn.close()
        except Exception as e:
            logger.error(f"Ошибка мониторинга: {e}")
        time.sleep(3600)

# Статистика
def get_db_stats():
    logger.info("Запрос статистики")
    conn = get_db_connection()
    if conn is None:
        logger.error("База недоступна")
        return None
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        user_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM credentials")
        cred_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM hacked_accounts")
        hacked_count = c.fetchone()[0]
        logger.info(f"Статистика: {user_count} users, {cred_count} creds, {hacked_count} hacked")
        return {'users': user_count, 'credentials': cred_count, 'hacked': hacked_count}
    except Exception as e:
        logger.error(f"Ошибка статистики: {e}")
        return None
    finally:
        conn.close()

# Валидация пароля
def validate_password(password):
    logger.debug(f"Валидация: {password}")
    if len(password) < 6:
        logger.warning("Короткий пароль")
        return False
    if not re.search(r'[A-Za-z0-9]', password):
        logger.warning("Нет букв/цифр")
        return False
    logger.debug("Пароль ок")
    return True

# Запуск
if __name__ == '__main__':
    logger.info("Запуск бота")
    if not init_db():
        logger.error("Ошибка базы")
        raise Exception("Database init failed")
    threading.Thread(target=keep_alive, daemon=True).start()
    logger.info("Keep_alive запущен")
    threading.Thread(target=monitor_activity, daemon=True).start()
    logger.info("Мониторинг запущен")
    try:
        logger.info("Удаление вебхука")
        bot.remove_webhook()
        time.sleep(1)
        webhook_url = f'{SITE_URL}/webhook'
        logger.info(f"Установка вебхука: {webhook_url}")
        bot.set_webhook(url=webhook_url, secret_token=SECRET_WEBHOOK_TOKEN)
        logger.info(f"Вебхук: {SECRET_WEBHOOK_TOKEN}")
    except Exception as e:
        logger.error(f"Ошибка вебхука: {e}")
        raise
    try:
        logger.info("Запуск Flask")
        app.run(
            host='0.0.0.0',
            port=int(os.getenv('PORT', 10000)),
            debug=False
        )
    except Exception as e:
        logger.error(f"Ошибка сервера: {e}")
        raise
