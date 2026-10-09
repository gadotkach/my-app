from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    test_database_url: str = ""
    jwt_secret: str = "CHANGE_ME"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    jwt_refresh_expire_days: int = 30
    encryption_key: str = "CHANGE_ME"
    cookie_secure: bool = False
    cookie_domain: str | None = None

    trial_period_days: int = 30
    subscription_period_days: int = 30
    subscription_price_rub: int = 990
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""

    # Telegram bot
    telegram_bot_token: str = ""
    telegram_proxy_url: str = ""  # Cloudflare Worker

    # Yandex OAuth (Яндекс ID)
    yandex_oauth_client_id: str = ""
    yandex_oauth_client_secret: str = ""
    yandex_oauth_redirect_uri: str = "https://api.agregators.su/auth/yandex/callback"

    # Frontend base URL (для редиректов после OAuth)
    frontend_base_url: str = "https://agregators.su"
    yookassa_return_url: str = "https://my-app-frontend-biz.pages.dev/pricing"

    # Email (Yandex Cloud Postbox SMTP)
    # ВАЖНО: SMTP_USER = key_id API-ключа (НЕ "postbox", НЕ email!)
    # SMTP_PASSWORD = secret API-ключа
    smtp_host: str = "postbox.cloud.yandex.net"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@agregators.su"
    smtp_from_name: str = "Agregators"

    # Yandex Cloud Postbox HTTP API (SigV4 через статический ключ S3)
    # Используется ВМЕСТО SMTP (VPS блокирует 465).
    postbox_endpoint: str = "https://postbox.cloud.yandex.net"
    yandex_s3_access_key: str = ""
    yandex_s3_secret_key: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def async_database_url(self) -> str:
        url = self.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if "?" in url:
            url = url.split("?", 1)[0]
        return url


settings = Settings()
