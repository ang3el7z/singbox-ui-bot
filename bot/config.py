from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List, Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Telegram
    bot_token: str
    admin_ids: str = ""

    # s-ui API
    sui_url: str = "http://sui:2095"
    sui_username: str = "admin"
    sui_password: str = "admin"
    sui_token: str = ""

    # AdGuard
    adguard_url: str = "http://adguard:3000"
    adguard_user: str = "admin"
    adguard_password: str = "changeme"

    # Nginx / SSL
    domain: str = ""
    email: str = ""

    # Federation
    federation_secret: str = "change_this_secret"
    bot_public_url: str = ""

    # Security
    secret_key: str = "change_this_key"

    # Misc
    tz: str = "UTC"
    bot_lang: str = "ru"

    # Webhook
    webhook_host: str = ""
    webhook_path: str = "/webhook"
    webhook_port: int = 8080

    @property
    def admin_ids_list(self) -> List[int]:
        if not self.admin_ids:
            return []
        return [int(x.strip()) for x in self.admin_ids.split(",") if x.strip().isdigit()]

    @property
    def use_webhook(self) -> bool:
        return bool(self.webhook_host)

    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_host}{self.webhook_path}"


settings = Settings()
