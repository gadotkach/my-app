"""Email-клиент для отправки транзитных писем через Yandex Cloud Postbox SMTP.

Особенности Yandex Postbox SMTP:
- SMTP_USER = key_id API-ключа (например, aje70ab4gnu64mpqcsga), НЕ "postbox" и НЕ email.
- SMTP_PASSWORD = secret API-ключа (AQVN...), 40 символов.
- Порт 465 = SMTPS (SSL).
"""

import logging
from email.message import EmailMessage

import aiosmtplib

from app.config import settings

logger = logging.getLogger(__name__)


async def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> None:
    """Отправляет email через Yandex Postbox SMTP."""
    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("SMTP не настроен — письмо не отправлено (to=%s)", to)
        raise RuntimeError("SMTP is not configured")

    msg = EmailMessage()
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from}>"
    msg["To"] = to
    msg["Subject"] = subject

    msg.set_content(text_body or "Просмотрите это письмо в HTML-совместимом клиенте.")
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        use_tls=True,
    )
    logger.info("Email sent to %s (subject=%s)", to, subject)


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
