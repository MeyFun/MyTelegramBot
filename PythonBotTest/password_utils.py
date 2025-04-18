import hashlib
import os
import binascii


def hash_password(password: str) -> str:
    """Генерирует хеш пароля с солью"""
    # Генерируем соль
    salt = hashlib.sha256(os.urandom(60)).hexdigest()

    # Хешируем пароль с солью
    pwdhash = hashlib.pbkdf2_hmac(
        'sha512',
        password.encode('utf-8'),
        salt.encode('ascii'),
        100000
    )

    # Преобразуем хеш в hex-строку
    pwdhash = binascii.hexlify(pwdhash).decode('ascii')

    # Возвращаем соль и хеш в виде строки
    return salt + pwdhash


def verify_password(stored_hash: str, provided_password: str) -> bool:
    """Проверяет, совпадает ли пароль с хешем"""
    salt = stored_hash[:64]  # Первые 64 символа - соль
    stored_password = stored_hash[64:]  # Остальное - хеш

    # Хешируем предоставленный пароль с той же солью
    pwdhash = hashlib.pbkdf2_hmac(
        'sha512',
        provided_password.encode('utf-8'),
        salt.encode('ascii'),
        100000
    )

    # Сравниваем хеши
    return binascii.hexlify(pwdhash).decode('ascii') == stored_password


def generate_strong_password(length=16) -> str:
    """Генерирует случайный сложный пароль"""
    import secrets
    import string

    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))