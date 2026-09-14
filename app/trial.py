import hashlib


def hash_identity(ip: str, user_agent: str) -> str:
    """Хеш от IP + User-Agent. Используется для одного trial на устройство/сеть."""
    raw = f"{ip}|{user_agent}".encode()
    return hashlib.sha256(raw).hexdigest()


def hash_email(email: str) -> str:
    """Хеш от email в нижнем регистре. Чтобы хранить, не раскрывая сам email."""
    return hashlib.sha256(email.lower().encode()).hexdigest()
