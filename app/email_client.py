"""Email-клиент для отправки транзакционных писем.

Использует Yandex Cloud Postbox HTTP API (AWS SES v2-совместимый).
Авторизация — AWS Signature v4 через статический ключ S3.

Почему HTTP API, а не SMTP:
- VPS-провайдер блокирует исходящий порт 465 (SMTP).
- HTTP API работает через порт 443 — не блокируется.
"""

import logging
from typing import Any

import boto3
from botocore.config import Config

from app.config import settings

logger = logging.getLogger(__name__)


def _get_ses_client() -> Any:
    """Создаёт boto3-клиент для Yandex Cloud Postbox (SES v2 API)."""
    return boto3.client(
        "sesv2",
        endpoint_url=settings.postbox_endpoint,
        region_name="ru-central1",
        aws_access_key_id=settings.yandex_s3_access_key,
        aws_secret_access_key=settings.yandex_s3_secret_key,
        config=Config(
            signature_version="v4",
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


async def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> None:
    """Отправляет email через Yandex Cloud Postbox HTTP API.

    Синхронный boto3 вызов оборачивается в asyncio.to_thread.
    """
    import asyncio

    if not settings.yandex_s3_access_key or not settings.yandex_s3_secret_key:
        logger.warning("Postbox API не настроен — письмо не отправлено (to=%s)", to)
        raise RuntimeError("Postbox API is not configured")

    def _send() -> dict[str, Any]:
        client = _get_ses_client()
        body: dict[str, Any] = {
            "Text": {"Data": text_body or "Просмотрите письмо в HTML-совместимом клиенте."},
        }
        if html_body:
            body["Html"] = {"Data": html_body}

        response: dict[str, Any] = dict(
            client.send_email(
                FromEmailAddress=f"{settings.smtp_from_name} <{settings.smtp_from}>",
                Destination={"ToAddresses": [to]},
                Content={
                    "Simple": {
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": body,
                    }
                },
            )
        )
        return response

    result = await asyncio.to_thread(_send)
    logger.info("Email sent to %s (MessageId=%s)", to, result.get("MessageId"))


async def send_password_reset_email(to: str, reset_url: str) -> None:
    """Отправляет письмо для сброса пароля."""
    subject = "Восстановление доступа к Agregators"
    html = f"""\
<!DOCTYPE html>
<html lang="ru">
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #2563eb;">Восстановление пароля</h2>
  <p>Вы запросили сброс пароля для аккаунта Agregators.</p>
  <p>Нажмите кнопку ниже, чтобы установить новый пароль:</p>
  <p style="margin: 24px 0;">
    <a href="{reset_url}"
       style="display: inline-block; padding: 12px 24px; background: #2563eb;
              color: #fff; text-decoration: none; border-radius: 6px;">
      Установить новый пароль
    </a>
  </p>
  <p style="color: #6b7280; font-size: 14px;">
    Ссылка действует <strong>1 час</strong>.<br>
    Если вы не запрашивали сброс пароля — просто проигнорируйте это письмо.
  </p>
  <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
  <p style="color: #9ca3af; font-size: 12px;">
    Это автоматическое письмо от Agregators. Не отвечайте на него.
  </p>
</body>
</html>
"""
    text = f"""\
Восстановление пароля Agregators

Вы запросили сброс пароля. Перейдите по ссылке:
{reset_url}

Ссылка действует 1 час.

Если вы не запрашивали сброс — проигнорируйте письмо.
"""
    await send_email(to=to, subject=subject, html_body=html, text_body=text)


async def send_password_changed_email(to: str) -> None:
    """Отправляет уведомление об успешной смене пароля."""
    subject = "Пароль Agregators изменён"
    html = """\
<!DOCTYPE html>
<html lang="ru">
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #2563eb;">Пароль изменён</h2>
  <p>Пароль от вашего аккаунта Agregators был успешно изменён.</p>
  <p style="color: #6b7280; font-size: 14px;">
    Если это были не вы — <strong>срочно</strong> напишите в поддержку:
    <a href="mailto:support@agregators.su">support@agregators.su</a>
  </p>
</body>
</html>
"""
    text = """\
Пароль Agregators изменён.

Если это были не вы — срочно напишите: support@agregators.su
"""
    await send_email(to=to, subject=subject, html_body=html, text_body=text)
