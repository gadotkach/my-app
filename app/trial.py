import hashlib


def hash_identity(ip: str, user_agent: str) -> str:
    """Хеш от IP + User-Agent. Используется для одного trial на устройство/сеть."""
    raw = f"{ip}|{user_agent}".encode()
    return hashlib.sha256(raw).hexdigest()


def hash_email(email: str) -> str:
    """Хеш от email в нижнем регистре. Чтобы хранить, не раскрывая сам email."""
    return hashlib.sha256(email.lower().encode()).hexdigest()


def hash_marketplace_identity(marketplace_code: str, identity: str) -> str:
    """Хеш от (marketplace_code, client_id или api_key).

    Используется для UsedMarketplaceIdentity — защиты от вечного trial.
    marketplace_code включается в хеш, чтобы client_id "ozon" и "wb"
    не могли случайно совпасть.
    """
    raw = f"{marketplace_code}:{identity}".encode()
    return hashlib.sha256(raw).hexdigest()
