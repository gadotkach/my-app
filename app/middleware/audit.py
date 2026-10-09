"""Middleware для логирования доступа к ПДн (152-ФЗ).

Логирует только чувствительные эндпоинты:
login, register, logout, refresh, consent/*, users/me/export,
users/me (DELETE), integrations/*.

Запись в AuditLog — асинхронно, не блокирует ответ.
"""

import logging
import re
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


# Эндпоинты для логирования: (regex, action)
AUDIT_PATHS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^/auth/login$"), "login"),
    (re.compile(r"^/auth/register$"), "register"),
    (re.compile(r"^/auth/logout$"), "logout"),
    (re.compile(r"^/auth/refresh$"), "refresh"),
    (re.compile(r"^/auth/consent/"), "consent"),
    (re.compile(r"^/users/me/export$"), "export"),
    (re.compile(r"^/users/me$"), "delete_account"),
    (re.compile(r"^/integrations/"), "integration"),
]

# Служебные пути — не логируем
SKIP_PATHS = re.compile(r"^/(health|docs|openapi|redoc|static)")


class AuditMiddleware(BaseHTTPMiddleware):
    """Логирует доступ к ПДн в таблицу audit_logs."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)

        path = request.url.path

        if SKIP_PATHS.match(path):
            return response

        # Найти action
        action: str | None = None
        for pattern, act in AUDIT_PATHS:
            if pattern.match(path):
                action = act
                break

        if action is None:
            return response

        # Для DELETE /users/me — action delete_account, для GET — export
        if path == "/users/me" and request.method != "DELETE":
            return response

        # Извлечь user_id (установлен в deps.get_current_user)
        user_id: int | None = getattr(request.state, "user_id", None)
        client_ip: str | None = request.client.host if request.client else None
        user_agent_raw = request.headers.get("user-agent", "")
        user_agent = user_agent_raw[:500] if user_agent_raw else None

        # Записать в БД (best-effort, не блокируем)
        try:
            from app.models import AuditLog

            # session-maker из app.state (overridable в тестах)
            session_maker = getattr(request.app.state, "session_maker", None)
            if session_maker is None:
                from app.database import AsyncSessionLocal

                session_maker = AsyncSessionLocal

            async with session_maker() as session:
                log = AuditLog(
                    user_id=user_id,
                    action=action,
                    resource=path,
                    ip_address=client_ip,
                    user_agent=user_agent,
                    metadata_json={
                        "method": request.method,
                        "status": response.status_code,
                    },
                )
                session.add(log)
                await session.commit()
        except Exception as e:
            logger.warning("audit_log failed for %s: %s", path, e)

        return response
