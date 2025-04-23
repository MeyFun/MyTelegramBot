import subprocess
import sys
import os

requirements_file = os.path.join(os.path.dirname(__file__), "requirements.txt")

if os.path.exists(requirements_file):
    print("📦 Установка зависимостей из requirements.txt...")
    subprocess.call([sys.executable, "-m", "pip", "install", "-r", requirements_file])
else:
    print("⚠️ requirements.txt не найден!")
