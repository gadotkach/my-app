from cryptography.fernet import Fernet

from app.config import settings

_fernet = Fernet(settings.encryption_key.encode())


def encrypt(plain: str) -> str:
    """Зашифровать секретную строку (например, Api-Key Ozon)."""
    return _fernet.encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    """Расшифровать секретную строку из БД."""
    return _fernet.decrypt(token.encode()).decode()
