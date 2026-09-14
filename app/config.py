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
    yookassa_return_url: str = "https://my-app-frontend-biz.pages.dev/pricing"

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
