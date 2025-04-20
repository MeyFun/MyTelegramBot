from telebot import types
from datetime import datetime, timedelta

def format_time_to_msk(timestamp):
    try:
        if isinstance(timestamp, str):
            db_time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        else:
            db_time = timestamp
        msk_time = db_time + timedelta(hours=6)
        return msk_time.strftime("%d.%m.%Y %H:%M")
    except Exception as e:
        print(f"Ошибка форматирования времени: {e}")
        return str(timestamp)

def send_next_question(bot, chat_id, user_id, user_states):
    state = user_states[user_id]
    questions = state['questions']
    current = state['current']

    if current >= len(questions):
        bot.send_message(chat_id, "Вы завершили тест. Спасибо!")
        del user_states[user_id]
        return

    question_text, _, options = questions[current]
    state['current'] += 1

    if options:
        opt = options.split(',')
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(*opt)
        bot.send_message(chat_id, question_text, reply_markup=markup)
    else:
        bot.send_message(chat_id, question_text, reply_markup=types.ReplyKeyboardRemove())

def handle_test(bot, msg, cur, conn, user_states):
    user_id = msg.from_user.id

    if user_id not in user_states or 'stage' not in user_states[user_id]:
        # Если нет - просто выходим, так как это сообщение не относится к тесту
        return

    state = user_states[user_id]

    if state['stage'] == 'awaiting_code':
        code = msg.text.strip()

        if code.lower() == "отмена":
            del user_states[user_id]
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("/start_test", "/info")
            bot.send_message(msg.chat.id, "❌ Ввод кода отменён. Возвращаюсь в меню.", reply_markup=markup)
            return

        code = code

        cur.execute("SELECT question, correct_answer, options FROM tests WHERE code = ?", (code,))
        questions = cur.fetchall()

        if not questions:
            bot.send_message(msg.chat.id, "Код неверный или тест не найден.")
            return
        state.update({
            'code': code,
            'questions': questions,
            'current': 0,
            'answers': [],
            'stage': 'in_test'
        })
        send_next_question(bot, msg.chat.id, user_id, user_states)

    elif state['stage'] == 'in_test':
        current_q = state['questions'][state['current'] - 1]
        cur.execute("SELECT MAX(attempt) FROM results WHERE user_id = ? AND code = ?", (user_id, state['code']))
        last_attempt = cur.fetchone()[0] or 0
        attempt = state.get("attempt", last_attempt + 1)
        state["attempt"] = attempt

        cur.execute("""
            INSERT INTO results (user_id, code, question, answer, attempt)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, state['code'], current_q[0], msg.text, attempt))
        conn.commit()

        send_next_question(bot, msg.chat.id, user_id, user_states)

    elif state['stage'] == 'choosing_code_for_answers':
        code = msg.text.strip()
        cur.execute("SELECT DISTINCT user_id FROM results WHERE code = ?", (code,))
        users = [row[0] for row in cur.fetchall()]

        if not users:
            bot.send_message(msg.chat.id, "Ответов по данному тесту нет.")
            del user_states[user_id]
            return

        user_states[user_id] = {
            'stage': 'viewing_results',
            'code': code,
            'users': users
        }

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        message = f"📋 Попытки по тесту *{code}*:\n\n"

        for uid in users:
            cur.execute("""
                SELECT answer, timestamp FROM results 
                WHERE user_id = ? AND code = ? 
                ORDER BY attempt, rowid LIMIT 2
            """, (uid, code))
            rows = cur.fetchall()
            fio = rows[0][0] if rows else "Неизвестно"
            group = rows[1][0] if len(rows) > 1 else "Неизвестно"
            timestamp = rows[0][1] if rows and rows[0][1] else "Без времени"
            # Получаем username через get_chat
            try:
                user = bot.get_chat(uid)
                user_link = f"@{user.username}" if user.username else f"ID: {uid}"
            except Exception:
                user_link = f"ID: {uid}"
            label = f"{fio} ({group}) - {user_link}"
            markup.add(label)
            message += (
                f"👤 *{fio}* ({group}) 🕓 {timestamp}\n"
            )
        markup.add("⬅️ Назад")
        bot.send_message(msg.chat.id, message, parse_mode="HTML", reply_markup=markup)

    elif state['stage'] == 'delete_answers':
        code = msg.text.strip()
        cur.execute("DELETE FROM results WHERE code = ?", (code,))
        conn.commit()
        bot.send_message(msg.chat.id, f"✅ Ответы на тест с кодом {code} удалены.", reply_markup=types.ReplyKeyboardRemove())
        del user_states[user_id]

    elif state['stage'] == 'view_attempt':
        if msg.text.strip() == "⬅️ Назад":
            # Возвращаемся к списку студентов
            code = state['code']
            cur.execute("SELECT DISTINCT user_id FROM results WHERE code = ?", (code,))
            users = [row[0] for row in cur.fetchall()]

            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            message = f"📋 Попытки по тесту *{code}*:\n\n"

            for uid in users:
                cur.execute("""
                    SELECT answer, timestamp FROM results 
                    WHERE user_id = ? AND code = ? 
                    ORDER BY attempt, rowid LIMIT 2
                """, (uid, code))
                rows = cur.fetchall()
                fio = rows[0][0] if rows else "Неизвестно"
                group = rows[1][0] if len(rows) > 1 else "Неизвестно"
                timestamp = rows[0][1] if rows and rows[0][1] else "Без времени"
                try:
                    user = bot.get_chat(uid)
                    user_link = f"@{user.username}" if user.username else f"ID: {uid}"
                except Exception:
                    user_link = f"ID: {uid}"
                label = f"{fio} ({group}) - {user_link}"
                markup.add(label)
                message += f"👤 *{fio}* ({group}) 🕓 {timestamp}\n"

            markup.add("⬅️ Назад")
            user_states[user_id] = {
                'stage': 'viewing_results',
                'code': code,
                'users': users
            }
            bot.send_message(msg.chat.id, message, parse_mode="HTML", reply_markup=markup)
            return

        # Обработка выбора попытки
        if "Попытка" in msg.text.strip():
            try:
                attempt = int(msg.text.strip().split()[1])
                if attempt in state['attempts']:
                    # Показываем результаты выбранной попытки
                    uid = state['user_id']
                    code = state['code']

                    cur.execute("""
                        SELECT question, answer FROM results 
                        WHERE user_id = ? AND code = ? AND attempt = ?
                        ORDER BY rowid
                    """, (uid, code, attempt))
                    qa = cur.fetchall()

                    fio = qa[0][1] if len(qa) > 0 else "??"
                    group = qa[1][1] if len(qa) > 1 else "??"

                    try:
                        user = bot.get_chat(uid)
                        username = f"@{user.username}" if user.username else f"ID: {uid}"
                    except Exception:
                        username = f"ID: {uid}"

                    message = f"📄 Попытка {attempt} — 👤 {username} — *{fio}* ({group}):\n"

                    for i, (question, answer) in enumerate(qa[2:], start=1):
                        cur.execute("SELECT correct_answer FROM tests WHERE code = ? AND question = ?",
                                    (code, question))
                        row = cur.fetchone()

                        if not row or row[0] == '':
                            emoji = "❓"
                        elif row[0].strip().lower() == answer.strip().lower():
                            emoji = "✅"
                        else:
                            emoji = "❌"

                        message += f"{i}) {question}\nОтвет: {answer} {emoji}\n"

                    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
                    markup.add("⬅️ Назад")
                    bot.send_message(msg.chat.id, message, parse_mode="HTML", reply_markup=markup)

                    user_states[user_id] = {
                        'stage': 'view_single_attempt',
                        'code': code,
                        'user_id': uid,
                        'attempt': attempt
                    }
            except (IndexError, ValueError):
                bot.send_message(msg.chat.id, "Неверный формат попытки")

def register_answer_handlers(bot, cur, user_states):
    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get('stage') == 'choosing_subject_for_answers')
    def handle_subject_for_answers(msg):
        user_id = msg.from_user.id
        if msg.text.strip() == "⬅️ Назад":
            del user_states[user_id]
            bot.send_message(msg.chat.id, "Выберите команду:", reply_markup=types.ReplyKeyboardRemove())
            return

        subject = msg.text.strip()
        cur.execute("SELECT DISTINCT code FROM tests WHERE subject = ?", (subject,))
        codes = [row[0] for row in cur.fetchall()]

        if not codes:
            bot.send_message(msg.chat.id, "Нет тестов по выбранному предмету.")
            del user_states[user_id]
            return

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        for code in codes:
            markup.add(code)
        markup.add("⬅️ Назад")

        user_states[user_id] = {
            'stage': 'choosing_code_for_answers',
            'selected_subject': subject
        }

        bot.send_message(msg.chat.id, f"Выбран предмет: *{subject}*\n\nТеперь выберите код теста:",
                         parse_mode=""
                                    "HTML", reply_markup=markup)

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get('stage') == 'choosing_code_for_answers')
    def handle_code_for_answers(msg):
        user_id = msg.from_user.id
        if msg.text.strip() == "⬅️ Назад":
            # Возвращаемся к выбору предмета
            user_states[user_id] = {'stage': 'choosing_subject_for_answers'}
            cur.execute("SELECT DISTINCT subject FROM tests ORDER BY subject")
            subjects = [row[0] for row in cur.fetchall() if row[0]]

            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            for subject in subjects:
                markup.add(subject)
            markup.add("⬅️ Назад")

            bot.send_message(msg.chat.id, "Выберите предмет:", reply_markup=markup)
            return

        code = msg.text.strip()
        cur.execute("""
            SELECT DISTINCT r.answer 
            FROM results r
            JOIN (
                SELECT user_id, MIN(rowid) as min_rowid
                FROM results
                WHERE code = ?
                GROUP BY user_id
            ) t ON r.user_id = t.user_id AND r.rowid = t.min_rowid + 1
            WHERE r.code = ?
        """, (code, code))
        groups = [row[0] for row in cur.fetchall() if row[0]]

        if not groups:
            bot.send_message(msg.chat.id, "Нет данных по группам для этого теста.")
            del user_states[user_id]
            return

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        for group in sorted(groups):
            markup.add(group)
        markup.add("⬅️ Назад")

        user_states[user_id] = {
            'stage': 'choosing_group_for_answers',
            'code': code,
            'selected_subject': user_states[user_id]['selected_subject']
        }

        bot.send_message(msg.chat.id, f"Выбран тест: *{code}*\n\nТеперь выберите группу:",
                         parse_mode="HTML", reply_markup=markup)

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get('stage') == 'choosing_group_for_answers')
    def handle_group_for_answers(msg):
        user_id = msg.from_user.id
        state = user_states[user_id]

        if msg.text.strip() == "⬅️ Назад":
            # Возвращаемся к выбору кода теста
            user_states[user_id] = {
                'stage': 'choosing_code_for_answers',
                'selected_subject': state['selected_subject']
            }
            cur.execute("SELECT DISTINCT code FROM tests WHERE subject = ?", (state['selected_subject'],))
            codes = [row[0] for row in cur.fetchall()]

            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            for code in codes:
                markup.add(code)
            markup.add("⬅️ Назад")

            bot.send_message(msg.chat.id,
                             f"Выбран предмет: *{state['selected_subject']}*\n\nТеперь выберите код теста:",
                             parse_mode="HTML", reply_markup=markup)
            return

        group = msg.text.strip()
        code = state['code']

        # Получаем список студентов в группе
        cur.execute("""
            SELECT DISTINCT r.user_id, 
                   (SELECT answer FROM results WHERE user_id = r.user_id AND code = r.code ORDER BY rowid LIMIT 1) as fio,
                   (SELECT answer FROM results WHERE user_id = r.user_id AND code = r.code ORDER BY rowid LIMIT 1 OFFSET 1) as group_name
            FROM results r
            WHERE r.code = ? AND (SELECT answer FROM results WHERE user_id = r.user_id AND code = r.code ORDER BY rowid LIMIT 1 OFFSET 1) = ?
            GROUP BY r.user_id
            ORDER BY fio
        """, (code, group))

        students = [(row[0], row[1], row[2]) for row in cur.fetchall()]

        if not students:
            bot.send_message(msg.chat.id, "Нет студентов в этой группе.")
            return

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        for uid, fio, group_name in students:
            try:
                user = bot.get_chat(uid)
                username = f"@{user.username}" if user.username else f"{user.first_name} {user.last_name or ''}"
            except Exception:
                username = f"ID: {uid}"
            # Измененный формат: @username + ФИО
            markup.add(f"{username} - {fio}")
        markup.add("⬅️ Назад")

        user_states[user_id] = {
            'stage': 'choosing_student_for_answers',
            'code': code,
            'group': group,
            'students': students,
            'selected_subject': state['selected_subject']
        }

        bot.send_message(msg.chat.id, f"Выбрана группа: *{group}*\n\nТеперь выберите студента:",
                         parse_mode="HTML", reply_markup=markup)

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get('stage') == 'choosing_student_for_answers')
    def handle_student_for_answers(msg):
        user_id = msg.from_user.id
        state = user_states[user_id]

        if msg.text.strip() == "⬅️ Назад":
            # Возвращаемся к выбору группы
            user_states[user_id] = {
                'stage': 'choosing_group_for_answers',
                'code': state['code'],
                'selected_subject': state['selected_subject']
            }

            cur.execute("""
                SELECT DISTINCT 
                    (SELECT answer FROM results WHERE user_id = r.user_id AND code = r.code ORDER BY rowid LIMIT 1 OFFSET 1) as group_name
                FROM results r
                WHERE r.code = ?
            """, (state['code'],))
            groups = [row[0] for row in cur.fetchall() if row[0]]

            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            for group in sorted(groups):
                markup.add(group)
            markup.add("⬅️ Назад")

            bot.send_message(msg.chat.id, f"Выбран тест: *{state['code']}*\n\nТеперь выберите группу:",
                             parse_mode="HTML", reply_markup=markup)
            return

        # Находим выбранного студента
        selected_text = msg.text.strip()
        selected_uid = None
        selected_fio = None

        for uid, fio, group_name in state['students']:
            try:
                user = bot.get_chat(uid)
                username = f"@{user.username}" if user.username else f"{user.first_name} {user.last_name or ''}"
            except Exception:
                username = f"ID: {uid}"

            if f"{username} - {fio}" == selected_text:
                selected_uid = uid
                selected_fio = fio
                break

        if not selected_uid:
            bot.send_message(msg.chat.id, "Студент не найден.")
            return

        # Получаем список попыток
        cur.execute("""
            SELECT attempt, MAX(timestamp) as timestamp
            FROM results 
            WHERE user_id = ? AND code = ?
            GROUP BY attempt
            ORDER BY attempt
        """, (selected_uid, state['code']))

        attempts = [(row[0], row[1]) for row in cur.fetchall()]

        if not attempts:
            bot.send_message(msg.chat.id, "Нет попыток у этого студента.")
            return

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        for attempt, timestamp in attempts:
            # Форматируем время в локальный часовой пояс (МСК)
            try:
                time_str = format_time_to_msk(timestamp)
            except:
                time_str = timestamp
            markup.add(f"Попытка {attempt} ({time_str})")
        markup.add("⬅️ Назад")

        user_states[user_id] = {
            'stage': 'viewing_attempt',
            'code': state['code'],
            'group': state['group'],
            'student_id': selected_uid,
            'student_name': selected_fio,
            'student_username': selected_text.split(' - ')[0],
            'attempts': attempts,
            'selected_subject': state['selected_subject']
        }

        bot.send_message(msg.chat.id, f"Выбран студент: *{selected_text}*\n\nВыберите попытку:",
                         parse_mode="HTML", reply_markup=markup)

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get('stage') == 'viewing_attempt')
    def handle_viewing_attempt(msg):
        user_id = msg.from_user.id
        state = user_states[user_id]

        if msg.text.strip() == "⬅️ Назад":
            # Возвращаемся к выбору студента
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            for uid, fio, group_name in state.get('students', []):
                try:
                    user = bot.get_chat(uid)
                    username = f"@{user.username}" if user.username else f"{user.first_name} {user.last_name or ''}"
                except Exception:
                    username = f"ID: {uid}"
                markup.add(f"{username} - {fio}")
            markup.add("⬅️ Назад")

            user_states[user_id] = {
                'stage': 'choosing_student_for_answers',
                'code': state['code'],
                'group': state['group'],
                'students': state.get('students', []),
                'selected_subject': state['selected_subject']
            }

            bot.send_message(msg.chat.id, f"Выбрана группа: *{state['group']}*\n\nТеперь выберите студента:",
                             parse_mode="HTML", reply_markup=markup)
            return

        # Обрабатываем выбор попытки
        try:
            attempt = int(msg.text.strip().split()[1])
            timestamp = next((t for a, t in state['attempts'] if a == attempt), None)

            # Получаем результаты попытки
            cur.execute("""
                SELECT question, answer 
                FROM results 
                WHERE user_id = ? AND code = ? AND attempt = ?
                ORDER BY rowid
            """, (state['student_id'], state['code'], attempt))

            answers = cur.fetchall()

            if len(answers) < 2:
                bot.send_message(msg.chat.id, "Недостаточно данных для отображения попытки.")
                return

            fio = answers[0][1]
            group = answers[1][1]

            # Форматируем время в локальный часовой пояс (МСК)
            try:
                time_str = format_time_to_msk(timestamp)
            except:
                time_str = timestamp

            message = f"📄 *{fio}* ({group})\n"
            message += f"🔹 Тест: {state['code']}\n"
            message += f"🔹 Группа: {state['group']}\n"
            message += f"🔹 Попытка: {attempt}\n"
            message += f"🔹 Время выполнения: {time_str}\n\n"

            for i, (question, answer) in enumerate(answers[2:], start=1):
                cur.execute("SELECT correct_answer FROM tests WHERE code = ? AND question = ?",
                            (state['code'], question))
                correct = cur.fetchone()

                if correct and correct[0]:
                    if correct[0].strip().lower() == answer.strip().lower():
                        emoji = "✅"
                    else:
                        emoji = "❌"
                else:
                    emoji = "❓"

                message += f"{i}. {question}\nОтвет: {answer} {emoji}\n\n"

            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add("⬅️ Назад")

            bot.send_message(msg.chat.id, message, parse_mode="HTML", reply_markup=markup)

            user_states[user_id] = {
                'stage': 'viewing_attempt_details',
                'code': state['code'],
                'group': state['group'],
                'student_id': state['student_id'],
                'student_name': state['student_name'],
                'attempt': attempt,
                'selected_subject': state['selected_subject']
            }

        except (IndexError, ValueError):
            bot.send_message(msg.chat.id, "Неверный формат попытки. Пожалуйста, используйте кнопки.")

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get('stage') == 'viewing_attempt_details')
    def handle_attempt_details(msg):
        if msg.text.strip() == "⬅️ Назад":
            user_id = msg.from_user.id
            state = user_states[user_id]

            # Возвращаемся к списку попыток
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            for attempt, timestamp in state.get('attempts', []):
                try:
                    time_str = format_time_to_msk(timestamp)
                except:
                    time_str = timestamp
                markup.add(f"Попытка {attempt} ({time_str})")
            markup.add("⬅️ Назад")

            user_states[user_id] = {
                'stage': 'viewing_attempt',
                'code': state['code'],
                'group': state['group'],
                'student_id': state['student_id'],
                'student_name': state['student_name'],
                'attempts': state.get('attempts', []),
                'selected_subject': state['selected_subject']
            }

            bot.send_message(msg.chat.id, f"Выбран студент: *{state['student_name']}*\n\nВыберите попытку:",
                             parse_mode="HTML", reply_markup=markup)
