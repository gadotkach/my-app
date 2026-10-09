"""Логирование API-запросов к маркетплейсам через httpx event hooks.

Использование:

    from app.api_logger import log_request, log_response, set_log_context

    set_log_context(user_id=123, marketplace="ozon")
    client = httpx.AsyncClient(
        base_url="...",
        event_hooks={
            "request": [log_request],
            "response": [log_response],
        },
    )

Каждый запрос/ответ пишется в ApiRequestLog (асинхронно, без блокировки).
"""

import contextvars
import logging
import time

import httpx

logger = logging.getLogger(__name__)


# Контекст: user_id + marketplace (устанавливается перед вызовом клиента)
_current_user_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "current_user_id", default=None
)
_current_marketplace: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_marketplace", default="unknown"
)


def set_log_context(user_id: int | None, marketplace: str) -> None:
    """Установить контекст для логирования (user_id, marketplace)."""
    _current_user_id.set(user_id)
    _current_marketplace.set(marketplace)


async def log_request(request: httpx.Request) -> None:
    """Event hook: отмечает время начала запроса."""
    request.extensions["start_time"] = time.monotonic()


async def log_response(response: httpx.Response) -> None:
    """Event hook: логирует ответ в БД (асинхронно)."""
    try:
        request = response.request
        start = request.extensions.get("start_time")
        duration_ms = int((time.monotonic() - start) * 1000) if start else 0

        # Запись в БД — через отдельную сессию (не блокируем основной поток)
        from app.database import AsyncSessionLocal
        from app.models import ApiRequestLog

        async with AsyncSessionLocal() as session:
            log = ApiRequestLog(
                user_id=_current_user_id.get(),
                marketplace=_current_marketplace.get(),
                method=request.method,
                endpoint=str(request.url.path)[:255],
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            session.add(log)
            await session.commit()
    except Exception as e:
        # Логирование не должно ломать основной поток
        logger.warning("api_logger failed: %s", e)
