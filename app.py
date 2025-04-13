from flask import Flask, request
import telebot
from telebot import types
import psycopg2
import os
import requests
import threading
import time
from datetime import datetime, timedelta

# Настройки
TOKEN = '8028944732:AAFsvb4csGSRwtmEFYLGbnTKsCq1hOH6rm0'  # Новый токен
ADMIN_CHAT_ID = '6956377285'
DATABASE_URL = 'postgresql://roblox_db_user:vjBfo3Vwigs5pnm107BhEkXe6AOy3FWF@dpg-cvr25cngi27c738j8c50-a.oregon-postgres.render.com/roblox_db'
SITE_URL = os.getenv('SITE_URL', 'https://tg-bod.onrender.com')

app = Flask(__name__)
bot = telebot.TeleBot(TOKEN)

processed_updates = set()
ad_keywords = ['подписка', 'заработок', 'реклама', 'продвижение', 'бесплатно', 'акция', 'промо', 'скидка', 'casino', 'bet']

def get_current_time():
    print("Время UTC+2")
    return datetime.now() + timedelta(hours=2)

def get_db_connection():
    print("Подключение к БД")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        print("БД подключена")
        return conn
    except Exception as e:
        print(f"Ошибка БД: {e}")
        return None

def init_db():
    print("Инициализация БД")
    conn = get_db_connection()
    if conn is None:
        print("Ошибка БД")
        return False
    try:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                     (chat_id TEXT PRIMARY KEY, prefix TEXT, subscription_end TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS credentials 
                     (login TEXT PRIMARY KEY, password TEXT, added_time TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS hacked_accounts 
                     (login TEXT PRIMARY KEY, password TEXT, hack_date TEXT, prefix TEXT, sold_status TEXT, linked_chat_id TEXT)''')
        print("Очистка credentials и hacked_accounts")
        c.execute("DELETE FROM credentials")
        c.execute("DELETE FROM hacked_accounts")
        subscription_end = (get_current_time() + timedelta(days=3650)).isoformat()
        c.execute("INSERT INTO users (chat_id, prefix, subscription_end) VALUES (%s, %s, %s) "
                  "ON CONFLICT (chat_id) DO UPDATE SET prefix = EXCLUDED.prefix, subscription_end = EXCLUDED.subscription_end",
                  (ADMIN_CHAT_ID, "Создатель", subscription_end))
        conn.commit()
        conn.close()
        print("БД готова")
        return True
    except Exception as e:
        print(f"Ошибка инициализации: {e}")
        conn.close()
        return False

def keep_alive():
    print("Запуск keep_alive")
    while True:
        try:
            requests.get(SITE_URL)
            print(f"Пинг {SITE_URL}")
        except Exception as e:
            print(f"Ошибка keep_alive: {e}")
        time.sleep(60)

def get_user(chat_id):
    print(f"Пользователь {chat_id}")
    conn = get_db_connection()
    if conn is None:
        if chat_id == ADMIN_CHAT_ID:
            return {'prefix': 'Создатель', 'subscription_end': get_current_time() + timedelta(days=3650)}
        return None
    try:
        c = conn.cursor()
        c.execute("SELECT prefix, subscription_end FROM users WHERE chat_id = %s", (chat_id,))
        result = c.fetchone()
        conn.close()
        if result:
            return {'prefix': result[0], 'subscription_end': datetime.fromisoformat(result[1]) if result[1] else None}
        return None
    except Exception as e:
        print(f"Ошибка get_user: {e}")
        conn.close()
        return None

def save_user(chat_id, prefix, subscription_end=None):
    print(f"Сохранение {chat_id}")
    conn = get_db_connection()
    if conn is None:
        return
    try:
        c = conn.cursor()
        subscription_end = subscription_end or get_current_time().isoformat()
        c.execute("INSERT INTO users (chat_id, prefix, subscription_end) VALUES (%s, %s, %s) "
                  "ON CONFLICT (chat_id) DO UPDATE SET prefix = %s, subscription_end = %s",
                  (chat_id, prefix, subscription_end, prefix, subscription_end))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Ошибка save_user: {e}")
        conn.close()

def check_access(chat_id, command):
    print(f"Доступ для {chat_id} на {command}")
    user = get_user(chat_id)
    if user is None and command in ['start', 'menu', 'getchatid']:
        save_user(chat_id, "Посетитель")
        user = get_user(chat_id)
    if not user or user['prefix'] == 'Посетитель':
        if command in ['start', 'menu', 'getchatid']:
            return None
        return "🔒 Доступ ограничен! Подписка: @sacoectasy"
    if user['subscription_end'] and user['subscription_end'] < get_current_time():
        save_user(chat_id, 'Посетитель', get_current_time())
        return "🔒 Подписка истекла! @sacoectasy"
    if command in ['database', 'db'] and user['prefix'] != 'Создатель':
        return "🔒 Только для Создателя!"
    return None

@app.route('/')
def index():
    print("Запрос на /")
    return "Bot is running!"

@app.route('/webhook', methods=['POST'])
def webhook():
    print("Запрос на /webhook")
    try:
        if request.headers.get('content-type') == 'application/json':
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            if update and (update.message or update.callback_query):
                update_id = update.update_id
                if update_id in processed_updates:
                    print(f"Повтор update_id: {update_id}")
                    return 'OK', 200
                processed_updates.add(update_id)
                print(f"Обработка: {update}")
                bot.process_new_updates([update])
            return 'OK', 200
        print("Неверный content-type")
        return 'Неверный запрос', 400
    except Exception as e:
        print(f"Ошибка вебхука: {e}")
        return 'OK', 200

@bot.message_handler(commands=['start'])
def start_cmd(message):
    chat_id = str(message.chat.id)
    print(f"/start для {chat_id}")
    access = check_access(chat_id, 'start')
    if access:
        try:
            print(f"Отправка: {access}")
            bot.reply_to(message, access)
        except Exception as e:
            print(f"Ошибка /start: {e}")
        return
    response = "✨ Добро пожаловать! /menu для команд."
    try:
        print(f"Отправка: {response}")
        bot.reply_to(message, response)
    except Exception as e:
        print(f"Ошибка отправки /start: {e}")

@bot.message_handler(commands=['menu'])
def menu_cmd(message):
    chat_id = str(message.chat.id)
    print(f"/menu для {chat_id}")
    access = check_access(chat_id, 'menu')
    if access:
        try:
            print(f"Отправка: {access}")
            bot.reply_to(message, access)
        except Exception as e:
            print(f"Ошибка /menu: {e}")
        return
    user = get_user(chat_id)
    response = f"👤 Статус: {user['prefix']}\n📋 Команды:\n/start\n/menu\n/getchatid"
    if user['prefix'] == 'Создатель':
        response += "\n/db\n/database"
    try:
        print(f"Отправка: {response}")
        bot.reply_to(message, response)
    except Exception as e:
        print(f"Ошибка отправки /menu: {e}")

@bot.message_handler(commands=['getchatid'])
def getchatid_cmd(message):
    chat_id = str(message.chat.id)
    print(f"/getchatid для {chat_id}")
    access = check_access(chat_id, 'getchatid')
    if access:
        try:
            print(f"Отправка: {access}")
            bot.reply_to(message, access)
        except Exception as e:
            print(f"Ошибка /getchatid: {e}")
        return
    username = message.from_user.username or "Нет юзернейма"
    response = f"👤 ID: `{chat_id}`\nЮзернейм: @{username}"
    try:
        print(f"Отправка: {response}")
        bot.reply_to(message, response, parse_mode='Markdown')
    except Exception as e:
        print(f"Ошибка отправки /getchatid: {e}")

@bot.message_handler(commands=['database'])
def database_cmd(message):
    chat_id = str(message.chat.id)
    print(f"/database для {chat_id}")
    access = check_access(chat_id, 'database')
    if access:
        try:
            print(f"Отправка: {access}")
            bot.reply_to(message, access)
        except Exception as e:
            print(f"Ошибка /database: {e}")
        return
    response = "📊 База данных:\nПока пусто."
    try:
        print(f"Отправка: {response}")
        bot.reply_to(message, response)
    except Exception as e:
        print(f"Ошибка отправки /database: {e}")

@bot.message_handler(commands=['db'])
def db_cmd(message):
    chat_id = str(message.chat.id)
    print(f"/db для {chat_id}")
    access = check_access(chat_id, 'db')
    if access:
        try:
            print(f"Отправка: {access}")
            bot.reply_to(message, access)
        except Exception as e:
            print(f"Ошибка /db: {e}")
        return
    response = "📊 Краткая база:\nПока пусто."
    try:
        print(f"Отправка: {response}")
        bot.reply_to(message, response)
    except Exception as e:
        print(f"Ошибка отправки /db: {e}")

@bot.message_handler(func=lambda message: True)
def unknown_command(message):
    chat_id = str(message.chat.id)
    text = message.text.lower()
    print(f"Неизвестная команда для {chat_id}: {text}")
    if any(keyword in text for keyword in ad_keywords):
        print(f"Реклама от {chat_id}: {text}")
        try:
            bot.reply_to(message, "🚫 Реклама заблокирована!")
            bot.send_message(ADMIN_CHAT_ID, f"🚨 Реклама от {chat_id}: {text}")
            return
        except Exception as e:
            print(f"Ошибка блокировки рекламы: {e}")
    response = "❌ Неизвестная команда!\nИспользуйте /menu."
    try:
        print(f"Отправка: {response}")
        bot.reply_to(message, response)
    except Exception as e:
        print(f"Ошибка отправки: {e}")

# Инициализация
print("Запуск бота")
init_db()
threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == '__main__':
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=f'{SITE_URL}/webhook')
        print(f"Вебхук установлен: {SITE_URL}/webhook")
    except Exception as e:
        print(f"Ошибка установки вебхука: {e}")
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 10000)))
