from dotenv import load_dotenv
import os

load_dotenv("info.env")  # Загружает переменные из .env

ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("❌ Токен бота не найден! Проверьте info.env")
if not ADMIN_PASSWORD_HASH:
    raise ValueError("❌ Хэш пароля не найден! Проверьте info.env")