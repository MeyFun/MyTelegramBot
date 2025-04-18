import telebot
import sqlite3
from telebot import types
from config import BOT_TOKEN, ADMIN_PASSWORD_HASH
from password_utils import verify_password
from handlers.test_passage import handle_test, register_answer_handlers
from handlers.test_creation import register_test_creation_handler
import threading
import requests
import time

def keep_alive():
    while True:
        try:
            requests.get(
                "https://google.com",
                timeout=10  # Таймаут 10 секунд
            )
        except Exception as e:
            print(f"Keep-alive error: {e}")
        time.sleep(300)  # 5 минут

threading.Thread(target=keep_alive, daemon=True).start()

bot = telebot.TeleBot(BOT_TOKEN)

conn = sqlite3.connect('tests.db', check_same_thread=False)
cur = conn.cursor()

cur.execute("CREATE TABLE IF NOT EXISTS tests (code TEXT, question TEXT, correct_answer TEXT, options TEXT, subject TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS results (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, code TEXT, question TEXT, answer TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
cur.execute("""CREATE TABLE IF NOT EXISTS registration_attempts (user_id INTEGER, username TEXT, first_name TEXT, last_name TEXT, success INTEGER, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
conn.commit()

user_states = {}
test_building = {}
pending_unregistrations = set()
attempts = {} 

def is_admin(user_id):
    cur.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
    return cur.fetchone() is not None

@bot.message_handler(commands=['start'])
def start(msg):
    bot.send_message(msg.chat.id, "Привет! Чтобы начать тестирование, введи /start_test. Для справки — /info")

@bot.message_handler(commands=['register'])
def register(msg):
    user_id = msg.from_user.id
    username = msg.from_user.username
    first_name = msg.from_user.first_name
    last_name = msg.from_user.last_name or ""

    # 🔒 Проверяем количество попыток
    if attempts.get(user_id, 0) >= 3:
        bot.send_message(msg.chat.id, "❌ Слишком много попыток. Попробуйте позже.")
        return

    args = msg.text.strip().split()
    success = 0

    # 🔒 Проверяем пароль
    if len(args) == 2 and verify_password(ADMIN_PASSWORD_HASH, args[1]):
        cur.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
        conn.commit()
        success = 1
        response = "✅ Вы зарегистрированы как преподаватель."
    else:
        attempts[user_id] = attempts.get(user_id, 0) + 1
        remaining_attempts = 3 - attempts[user_id]
        response = f"❌ Неверный код. Осталось попыток: {remaining_attempts}"

    # Записываем попытку в базу (для логов)
    cur.execute("""
        INSERT INTO registration_attempts 
        (user_id, username, first_name, last_name, success) 
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, username, first_name, last_name, success))
    conn.commit()

    bot.send_message(msg.chat.id, response)

@bot.message_handler(commands=['unregister'])
def unregister(msg):
    user_id = msg.from_user.id
    if not is_admin(user_id):
        bot.send_message(msg.chat.id, "У вас нет прав использовать эту команду.")
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("✅ Подтвердить выход", "❌ Отменить")
    pending_unregistrations.add(user_id)

    bot.send_message(
        msg.chat.id,
        "Вы уверены, что хотите выйти из роли преподавателя?",
        reply_markup=markup
    )

@bot.message_handler(func=lambda m: m.from_user.id in pending_unregistrations)
def confirm_unregister(msg):
    user_id = msg.from_user.id
    text = msg.text.strip()

    if text == "✅ Подтвердить выход":
        cur.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        conn.commit()
        pending_unregistrations.remove(user_id)

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("/start_test", "/info")
        bot.send_message(msg.chat.id, "Вы понижены до ученика.", reply_markup=markup)

    elif text == "❌ Отменить":
        pending_unregistrations.remove(user_id)
        bot.send_message(msg.chat.id, "Вы остались преподавателем.", reply_markup=types.ReplyKeyboardRemove())

    else:
        bot.send_message(msg.chat.id, "Пожалуйста, используйте кнопки для подтверждения.")

@bot.message_handler(commands=['admin_list'])
def admin_list(msg):
        user_id = msg.from_user.id
        if not is_admin(user_id):
            bot.send_message(msg.chat.id, "У вас нет прав.")
            return

        cur.execute("SELECT user_id FROM admins")
        ids = [row[0] for row in cur.fetchall()]

        if not ids:
            bot.send_message(msg.chat.id, "Нет зарегистрированных преподавателей.")
            return

        text = "*Преподаватели:*\n"
        for uid in ids:
            try:
                user = bot.get_chat(uid)
                name = f"@{user.username}" if user.username else f"{user.first_name} {user.last_name or ''}"
                text += f"• {name.strip()}\n"
            except Exception:
                text += f"• ID: {uid} (недоступен)\n"

        bot.send_message(msg.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['RegLog'])
def reg_log(msg):
        user_id = msg.from_user.id
        if not is_admin(user_id):
            bot.send_message(msg.chat.id, "❌ У вас нет прав для просмотра логов.")
            return

        cur.execute("SELECT user_id, username, first_name, last_name, success, timestamp FROM registration_attempts ORDER BY timestamp DESC")
        attempts = cur.fetchall()

        if not attempts:
            bot.send_message(msg.chat.id, "Логов регистрации пока нет.")
            return

        log_text = "📝 *Логи попыток регистрации:*\n"
        for attempt in attempts:
            user_id, username, first_name, last_name, success, timestamp = attempt
            name = f"@{username}" if username else f"{first_name} {last_name}".strip()
            status = "✅" if success else "❌"
            log_text += f"{status} {name} (ID: {user_id}) - {timestamp}\n"

        bot.send_message(msg.chat.id, log_text, parse_mode="Markdown")

@bot.message_handler(commands=['remove_teacher'])
def remove_teacher_start(msg):
    user_id = msg.from_user.id

    if not is_admin(user_id):
        bot.send_message(msg.chat.id, "❌ Эта команда доступна только администраторам.")
        return

    cur.execute("SELECT user_id FROM admins")
    teachers = cur.fetchall()

    if not teachers:
        bot.send_message(msg.chat.id, "❌ В системе нет преподавателей.")
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)

    for teacher in teachers:
        try:
            chat = bot.get_chat(teacher[0])
            name = f"@{chat.username}" if chat.username else f"{chat.first_name} {chat.last_name or ''}"
            markup.add(f"{name} (ID: {teacher[0]})")
        except:
            markup.add(f"ID: {teacher[0]}")

    markup.add("❌ Отмена")

    user_states[user_id] = {
        'stage': 'removing_teacher',
        'teachers': [t[0] for t in teachers]
    }
    bot.send_message(msg.chat.id, "Выберите преподавателя для удаления:", reply_markup=markup)

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get('stage') == 'removing_teacher')
def remove_teacher_selected(msg):
    user_id = msg.from_user.id
    state = user_states[user_id]

    if msg.text == "❌ Отмена":
        del user_states[user_id]
        bot.send_message(msg.chat.id, "Отмена удаления.", reply_markup=types.ReplyKeyboardRemove())
        return

    # Парсим ID из текста (формат: "Имя (ID: 123456)")
    try:
        selected_id = int(msg.text.split("ID: ")[1].rstrip(")"))
    except (IndexError, ValueError):
        bot.send_message(msg.chat.id, "❌ Ошибка выбора. Попробуйте еще раз.")
        return

    # Проверяем, что выбранный ID есть в списке
    if selected_id not in state['teachers']:
        bot.send_message(msg.chat.id, "❌ Преподаватель не найден в списке.")
        return

    # Удаляем преподавателя
    cur.execute("DELETE FROM admins WHERE user_id = ?", (selected_id,))
    conn.commit()

    # Удаляем состояние
    del user_states[user_id]

    try:
        chat = bot.get_chat(selected_id)
        name = f"@{chat.username}" if chat.username else f"{chat.first_name} {chat.last_name or ''}"
        bot.send_message(msg.chat.id, f"✅ Преподаватель {name} (ID: {selected_id}) удален.",
                         reply_markup=types.ReplyKeyboardRemove())
    except:
        bot.send_message(msg.chat.id, f"✅ Преподаватель (ID: {selected_id}) удален.",
                         reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(commands=['all_commands'])
def all_commands(msg):
    user_id = msg.from_user.id
    if not is_admin(user_id):
        bot.send_message(msg.chat.id, "❌ Команда доступна только преподавателям.")
        return

    text = (
        "📚 *Полный список команд преподавателя:*\n\n"
        "/add_test — создать тест\n"
        "/test_list — список всех тестов по предметам\n"
        "/delete_test — удалить тест\n"
        "/edit_test — редактировать вопрос\n"
        "/admin_list — список преподавателей\n"
        "/RegLog — логи регистрации\n"
        "/unregister — выйти из роли преподавателя\n"
        "/start_test — пройти тест как студент\n"
        "/info — показать основные команды\n"
        "/answers - показать ответы студентов\n"
        "/delete_answers - Удалить ответы на тест\n"
        "/all_commands — показать все команды"
    )
    bot.send_message(msg.chat.id, text, parse_mode="HTML")

@bot.message_handler(commands=['test_list'])
def test_list(msg):
        user_id = msg.from_user.id
        if not is_admin(user_id):
            bot.send_message(msg.chat.id, "❌ У вас нет прав для просмотра списка тестов.")
            return

        cur.execute("SELECT DISTINCT subject FROM tests ORDER BY subject")
        subjects = [row[0] for row in cur.fetchall() if row[0]]

        if not subjects:
            bot.send_message(msg.chat.id, "❌ Пока нет созданных тестов.")
            return

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        for subj in subjects:
            markup.add(subj)

        user_states[user_id] = {'stage': 'choosing_subject_for_list'}
        bot.send_message(msg.chat.id, "Выберите предмет:", reply_markup=markup)

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get('stage') == 'choosing_subject_for_list')
def choose_subject(msg):
        user_id = msg.from_user.id
        subject = msg.text.strip()

        cur.execute("SELECT DISTINCT code FROM tests WHERE subject = ?", (subject,))
        tests = cur.fetchall()
        if not tests:
            bot.send_message(msg.chat.id, "По этому предмету тесты не найдены.")
            return

        message = f"📚 Тесты по предмету *{subject}*:\n\n"
        for (code,) in tests:
            cur.execute("SELECT COUNT(*) FROM tests WHERE code = ?", (code,))
            count = cur.fetchone()[0]
            message += f"🔹 Код: *{code}* — {count} вопросов\n"

        del user_states[user_id]
        bot.send_message(msg.chat.id, message, parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(commands=['answers'])
def show_answers(msg):
    user_id = msg.from_user.id
    if not is_admin(user_id):
        bot.send_message(msg.chat.id, "Команда доступна только преподавателям.")
        return

    cur.execute("SELECT DISTINCT subject FROM tests ORDER BY subject")
    subjects = [row[0] for row in cur.fetchall() if row[0]]

    if not subjects:
        bot.send_message(msg.chat.id, "Нет доступных тестов.")
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for subject in subjects:
        markup.add(subject)
    markup.add("⬅️ Назад")

    user_states[user_id] = {
        'stage': 'choosing_subject_for_answers'
    }
    bot.send_message(msg.chat.id, "Выберите предмет:", reply_markup=markup)

@bot.message_handler(commands=['edit_test'])
def edit_test_start(msg):
        user_id = msg.from_user.id
        if not is_admin(user_id):
            bot.send_message(msg.chat.id, "Команда доступна только преподавателям.")
            return

        cur.execute("SELECT DISTINCT subject FROM tests ORDER BY subject")
        subjects = [row[0] for row in cur.fetchall() if row[0]]

        if not subjects:
            bot.send_message(msg.chat.id, "Нет доступных предметов с тестами.")
            return

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        for subj in subjects:
            markup.add(subj)

        test_building[user_id] = {"stage": "edit_subject"}
        bot.send_message(msg.chat.id, "Выберите предмет, содержащий нужный тест:", reply_markup=markup)

@bot.message_handler(commands=['delete_answers'])
def delete_answers(msg):
        user_id = msg.from_user.id
        if not is_admin(user_id):
            bot.send_message(msg.chat.id, "❌ У вас нет прав использовать эту команду.")
            return

        cur.execute("SELECT DISTINCT code FROM results")
        codes = [row[0] for row in cur.fetchall()]

        if not codes:
            bot.send_message(msg.chat.id, "❌ Нет тестов с результатами.")
            return

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        for code in codes:
            markup.add(code)

        user_states[user_id] = {'stage': 'delete_answers'}
        bot.send_message(msg.chat.id, "Выберите код теста, чьи ответы нужно удалить:", reply_markup=markup)

@bot.message_handler(commands=['add_test'])
def add_test(msg):
        user_id = msg.from_user.id
        if not is_admin(user_id):
            bot.send_message(msg.chat.id, "У вас нет прав для создания тестов.")
            return

        args = msg.text.split()
        if len(args) != 2:
            bot.send_message(msg.chat.id, "Использование: /add_test <код теста>")
            bot.send_message(msg.chat.id, "Рекомендация: введите код теста в формате 'Название предмета' + 'Код', чтобы не было пересечений с паролем")
            return

        code = args[1]
        cur.execute("SELECT 1 FROM tests WHERE code = ? LIMIT 1", (code,))
        if cur.fetchone():
            bot.send_message(msg.chat.id, f"⚠️ Тест с кодом '{code}' уже существует. Пожалуйста, выберите другой код.")
            return

        test_building[user_id] = {
            "code": code,
            "subject": "",
            "current_q": 1,
            "stage": "awaiting_subject",
            "temp_question": "",
            "temp_answers": []
        }
        bot.send_message(msg.chat.id, "Введите название предмета:")

@bot.message_handler(commands=['delete_test'])
def delete_test_start(msg):
    user_id = msg.from_user.id
    if not is_admin(user_id):
        bot.send_message(msg.chat.id, "❌ У вас нет прав использовать эту команду.")
        return

    cur.execute("SELECT DISTINCT subject FROM tests ORDER BY subject")
    subjects = [row[0] for row in cur.fetchall() if row[0]]

    if not subjects:
        bot.send_message(msg.chat.id, "❌ Нет доступных тестов для удаления.")
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for subj in subjects:
        markup.add(subj)

    # Используем test_building для хранения состояния
    test_building[user_id] = {"stage": "delete_subject"}
    bot.send_message(msg.chat.id, "Выберите предмет, тест из которого нужно удалить:", reply_markup=markup)

@bot.message_handler(commands=['info'])
def info(msg):
    user_id = msg.from_user.id
    cur.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
    is_admin = cur.fetchone() is not None

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("/start_test"))

    if is_admin:
        markup.add(
            types.KeyboardButton("/add_test"),
            types.KeyboardButton("/test_list"),
            types.KeyboardButton("/delete_test"),
            types.KeyboardButton("/edit_test"),
            types.KeyboardButton("/all_commands")
        )

    if is_admin:
        text = (
            "👨‍🏫 *Вы преподаватель.*\n\n"
            "📋 Основные команды:\n"
            "/add_test — создать тест\n"
            "/test_list — список тестов по предметам\n"
            "/delete_test — удалить тест\n"
            "/edit_test — редактировать вопрос\n"
            "/all_commands — показать все команды\n"
        )
    else:
        text = (
            "🎓 *Вы студент.*\n\n"
            "📋 Доступные команды:\n"
            "/start_test — начать тест\n"
            "/info — показать команды"
        )

    bot.send_message(msg.chat.id, text, parse_mode="HTML", reply_markup=markup)

@bot.message_handler(commands=['start_test'])
def start_test(msg):
    user_id = msg.from_user.id
    user_states[user_id] = {'stage': 'awaiting_code'}
    bot.send_message(msg.chat.id, "Введите код доступа к тесту:")

register_test_creation_handler(bot, conn, cur, test_building)
register_answer_handlers(bot, cur, user_states)

@bot.message_handler(func=lambda m: m.from_user.id in user_states)
def handle_user_test(msg):
    handle_test(bot, msg, cur, conn, user_states)

bot.polling(none_stop=True)
