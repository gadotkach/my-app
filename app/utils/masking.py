"""Утилиты маскирования ПДн для логов (152-ФЗ)."""


def mask_email(email: str | None) -> str:
    """Маскирует email: a***@example.com."""
    if not email:
        return "***"
    local, _, domain = email.partition("@")
    if not local or not domain:
        return "***"
    return f"{local[0]}***@{domain}"


def mask_phone(phone: str | None) -> str:
    """Маскирует телефон: +7***1234."""
    if not phone:
        return "***"
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) < 4:
        return "***"
    return f"+{digits[0]}***{digits[-4:]}"


def mask_name(name: str | None) -> str:
    """Маскирует имя: И***."""
    if not name:
        return "***"
    return f"{name[0]}***"


def mask_ip(ip: str | None) -> str:
    """Маскирует IP: 192.168.***."""
    if not ip:
        return "***"
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.***.***"
    return "***"
