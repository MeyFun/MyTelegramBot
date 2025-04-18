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
                             parse_mode="Markdown")

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
