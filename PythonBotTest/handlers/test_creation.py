from telebot import types

def register_test_creation_handler(bot, conn, cur, test_building):
    @bot.message_handler(func=lambda msg: msg.from_user.id in test_building)
    def handle_test_creation(msg):
        user_id = msg.from_user.id
        state = test_building[user_id]

        if state["stage"] == "awaiting_subject":
            state["subject"] = msg.text.strip()

            # Автоматически добавляем два первых вопроса: ФИО и Группа
            for question_text in ["ФИО:", "Группа (Например, ИСТ-241):"]:
                cur.execute(
                    "INSERT INTO tests (code, question, correct_answer, options, subject) VALUES (?, ?, ?, ?, ?)",
                    (state["code"], question_text, '', '', state["subject"])
                )
            conn.commit()

            state["stage"] = "awaiting_question"
            state["current_q"] = 1  # сбрасываем счётчик

            bot.send_message(msg.chat.id,
                             f'Добавление теста с кодом *{state["code"]}* по предмету "{state["subject"]}"\n\nВопрос 1:',
                             parse_mode="HTML")

        elif state["stage"] == "awaiting_question":
            state["temp_question"] = msg.text
            state["stage"] = "choosing_question_type"

            # Создаем кнопки для выбора типа вопроса
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add(types.KeyboardButton("Свободный ответ"))
            markup.add(types.KeyboardButton("Варианты ответа (2-8)"))

            bot.send_message(msg.chat.id,
                             "Выберите тип вопроса:",
                             reply_markup=markup)

        elif state["stage"] == "choosing_question_type":
            text = msg.text.strip().lower()

            if text == "свободный ответ":
                state["temp_answers"] = []
                state["stage"] = "next_or_end"
                question = state["temp_question"]
                code = state["code"]
                cur.execute(
                    "INSERT INTO tests (code, question, correct_answer, options, subject) VALUES (?, ?, ?, ?, ?)",
                    (code, question, '', '', state["subject"]))
                conn.commit()

                markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
                markup.add(
                    types.KeyboardButton(f"Перейти ко {state['current_q'] + 1} вопросу"),
                    types.KeyboardButton("Закончить тест")
                )
                bot.send_message(msg.chat.id, "Открытый вопрос сохранён. Выберите действие:", reply_markup=markup)
                return

            elif text == "варианты ответа (2-8)":
                state["stage"] = "awaiting_options_count"

                # Создаем кнопки с количеством вариантов
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
                for i in range(2, 9):
                    markup.add(types.KeyboardButton(str(i)))

                bot.send_message(msg.chat.id,
                                 "Сколько будет вариантов ответа? (Выберите от 2 до 8):",
                                 reply_markup=markup)
                return

        elif state["stage"] == "awaiting_options_count":
            try:
                total_options = int(msg.text.strip())
                if total_options < 2 or total_options > 8:
                    bot.send_message(msg.chat.id, "Введите число от 2 до 8.")
                    return

                state["expected_option_count"] = total_options
                state["temp_answers"] = []
                state["stage"] = "collecting_options"
                bot.send_message(msg.chat.id,
                                 f"Введите {total_options} варианта ответа (по одному в сообщении):",
                                 reply_markup=types.ReplyKeyboardRemove())

            except ValueError:
                bot.send_message(msg.chat.id, "Введите число от 2 до 8.")

        elif state["stage"] == "collecting_options":
            state["temp_answers"].append(msg.text.strip())
            if len(state["temp_answers"]) == state["expected_option_count"]:
                state["stage"] = "awaiting_correct"

                # Создаем кнопки с вариантами для выбора правильного ответа
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
                for i, opt in enumerate(state["temp_answers"]):
                    markup.add(types.KeyboardButton(f"{chr(65 + i)}: {opt}"))

                bot.send_message(msg.chat.id,
                                 f"Выберите правильный вариант:",
                                 reply_markup=markup)

        elif state["stage"] == "awaiting_correct":
            # Обработка выбора правильного варианта через кнопку
            selected = msg.text.strip().split(":")[0].upper()
            index_map = {chr(65 + i): i for i in range(len(state["temp_answers"]))}

            if selected not in index_map:
                bot.send_message(msg.chat.id, f"Выберите правильный вариант из предложенных.")
                return

            index = index_map[selected]
            correct_answer = state["temp_answers"][index]
            question = state["temp_question"]
            options = ",".join(state["temp_answers"])
            code = state["code"]

            cur.execute("INSERT INTO tests (code, question, correct_answer, options, subject) VALUES (?, ?, ?, ?, ?)",
                        (code, question, correct_answer, options, state["subject"]))
            conn.commit()

            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add(
                types.KeyboardButton(f"Перейти к {state['current_q'] + 1} вопросу"),
                types.KeyboardButton("Закончить тест")
            )
            state["stage"] = "next_or_end"
            bot.send_message(msg.chat.id, "Вопрос сохранён. Что дальше?", reply_markup=markup)

        elif state["stage"] == "delete_subject":
            subject = msg.text.strip()

            # Получаем все коды тестов по выбранному предмету
            cur.execute("SELECT DISTINCT code FROM tests WHERE subject = ?", (subject,))
            codes = [row[0] for row in cur.fetchall()]

            if not codes:
                bot.send_message(msg.chat.id, "❌ Нет тестов по этому предмету.")
                del test_building[user_id]
                return

            state["subject"] = subject
            state["stage"] = "delete_code"
            state["available_codes"] = codes

            text = f"Доступные тесты по предмету \"{subject}\":\n\n"
            for i, code in enumerate(codes, 1):
                text += f"{i}. Код теста: {code}\n"
            text += "\nВведите номер теста, который хотите удалить:"

            bot.send_message(msg.chat.id, text)

        elif state["stage"] == "delete_code":
            try:
                num = int(msg.text.strip())
                codes = state.get("available_codes", [])

                if 1 <= num <= len(codes):
                    code_to_delete = codes[num - 1]

                    # Удаляем тест и его результаты
                    cur.execute("DELETE FROM tests WHERE code = ?", (code_to_delete,))
                    cur.execute("DELETE FROM results WHERE code = ?", (code_to_delete,))
                    conn.commit()

                    bot.send_message(msg.chat.id, f"✅ Тест с кодом '{code_to_delete}' успешно удалён.")
                else:
                    bot.send_message(msg.chat.id, "❌ Неверный номер теста.")
            except ValueError:
                bot.send_message(msg.chat.id, "❌ Введите корректный номер (число).")

            del test_building[user_id]
            bot.send_message(msg.chat.id, "Удаление завершено.", reply_markup=types.ReplyKeyboardRemove())

        elif state["stage"] == "edit_subject":
            subject = msg.text.strip()
            cur.execute("SELECT DISTINCT code FROM tests WHERE subject = ?", (subject,))
            codes = [row[0] for row in cur.fetchall()]

            if not codes:
                bot.send_message(msg.chat.id, "Нет тестов по этому предмету.")
                del test_building[user_id]
                return

            state["subject"] = subject
            state["stage"] = "edit_code"
            state["available_codes"] = codes

            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            for code in codes:
                markup.add(code)

            bot.send_message(msg.chat.id, "Выберите код теста для редактирования:", reply_markup=markup)

        elif state["stage"] == "edit_code":
            code = msg.text.strip()
            state["code"] = code

            cur.execute("SELECT rowid, question FROM tests WHERE code = ?", (code,))
            questions = cur.fetchall()

            if not questions:
                bot.send_message(msg.chat.id, "❌ Вопросы не найдены.")
                del test_building[user_id]
                return

            state["questions"] = questions
            state["stage"] = "edit_question_number"

            text = f"🔧 Вопросы теста *{code}*:\n\n"
            for i, (rowid, question) in enumerate(questions, 1):
                text += f"{i}. {question}\n"

            text += "\nВведите номер вопроса, который хотите отредактировать:"
            bot.send_message(msg.chat.id, text, parse_mode="Markdown")

        elif state["stage"] == "edit_question_number":
            try:
                num = int(msg.text.strip())
                questions = state["questions"]
                if 1 <= num <= len(questions):
                    state["editing_rowid"] = questions[num - 1][0]
                    state["stage"] = "edit_new_text"
                    bot.send_message(msg.chat.id, "Введите новый текст вопроса:")
                else:
                    bot.send_message(msg.chat.id, "❌ Неверный номер.")
            except ValueError:
                bot.send_message(msg.chat.id, "❌ Введите корректный номер.")

        elif state["stage"] == "edit_new_text":
            new_text = msg.text.strip()
            rowid = state["editing_rowid"]
            state["new_question_text"] = new_text

            # Сохраняем текст, спрашиваем — редактировать ли варианты
            cur.execute("UPDATE tests SET question = ? WHERE rowid = ?", (new_text, rowid))
            conn.commit()

            # Проверим, есть ли варианты вообще
            cur.execute("SELECT options FROM tests WHERE rowid = ?", (rowid,))
            row = cur.fetchone()
            if not row or not row[0]:
                bot.send_message(msg.chat.id, "✅ Вопрос обновлён (это открытый вопрос).",
                                 reply_markup=types.ReplyKeyboardRemove())
                del test_building[user_id]
                return

            # Если варианты есть — спрашиваем, редактировать ли их
            state["stage"] = "edit_options_confirm"
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add("Да", "Нет")
            bot.send_message(msg.chat.id, "Хотите изменить варианты ответов?", reply_markup=markup)

        elif state["stage"] == "edit_options_confirm":
            if msg.text.strip().lower() == "да":
                state["stage"] = "edit_options_count"
                bot.send_message(msg.chat.id, "Сколько будет новых вариантов ответа? (от 2 до 10):",
                                 reply_markup=types.ReplyKeyboardRemove())
            else:
                bot.send_message(msg.chat.id, "✅ Вопрос обновлён без изменения вариантов.",
                                 reply_markup=types.ReplyKeyboardRemove())
                del test_building[user_id]

        elif state["stage"] == "edit_options_count":
            try:
                count = int(msg.text.strip())
                if 2 <= count <= 10:
                    state["option_count"] = count
                    state["option_list"] = []
                    state["stage"] = "edit_collect_options"
                    bot.send_message(msg.chat.id, f"Введите {count} новых вариантов (по одному в сообщении):")
                else:
                    bot.send_message(msg.chat.id, "Введите число от 2 до 10.")
            except ValueError:
                bot.send_message(msg.chat.id, "Введите число.")

        elif state["stage"] == "edit_collect_options":
            state["option_list"].append(msg.text.strip())
            if len(state["option_list"]) == state["option_count"]:
                state["stage"] = "edit_correct_option"
                options_preview = "\n".join([f"{chr(65 + i)}: {opt}" for i, opt in enumerate(state["option_list"])])
                bot.send_message(msg.chat.id,
                                 f"Варианты:\n{options_preview}\n\nУкажите новый правильный вариант (A, B, C и т.д.):")

        elif state["stage"] == "edit_correct_option":
            letter = msg.text.strip().upper()
            index_map = {chr(65 + i): i for i in range(len(state["option_list"]))}

            if letter not in index_map:
                bot.send_message(msg.chat.id, f"Введите правильный вариант: {'/'.join(index_map.keys())}")
                return

            index = index_map[letter]
            correct_answer = state["option_list"][index]
            options_str = ",".join(state["option_list"])
            rowid = state["editing_rowid"]

            cur.execute("UPDATE tests SET options = ?, correct_answer = ? WHERE rowid = ?",
                        (options_str, correct_answer, rowid))
            conn.commit()

            bot.send_message(msg.chat.id, "✅ Вопрос и варианты успешно обновлены.",
                             reply_markup=types.ReplyKeyboardRemove())
            del test_building[user_id]


        elif state["stage"] == "next_or_end":
            if msg.text.startswith("Перейти к"):
                state["current_q"] += 1
                state["stage"] = "awaiting_question"
                state["temp_question"] = ""
                state["temp_answers"] = []
                bot.send_message(msg.chat.id, f"Вопрос {state['current_q']}:", reply_markup=types.ReplyKeyboardRemove())
            elif msg.text == "Закончить тест":
                del test_building[user_id]
                bot.send_message(msg.chat.id, "Тест завершён и сохранён!", reply_markup=types.ReplyKeyboardRemove())
