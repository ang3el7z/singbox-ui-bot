from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Telegram
    bot_token: str = ""
    admin_ids: str = ""

    # API auth
    internal_token: str = "change_internal_token"   # X-Internal-Token for bot → api
    jwt_secret: str = "change_jwt_secret_32chars"
    jwt_expire_minutes: int = 60 * 24 * 7           # 7 days

    # Web UI admin (initial credentials, changed via API)
    web_admin_user: str = "admin"
    web_admin_password: str = "changeme"

    # Sing-Box
    singbox_config_path: str = "/etc/sing-box/config.json"
    singbox_container: str = "singbox_core"          # docker exec target

    # AdGuard
    adguard_url: str = "http://adguard:3000"
    adguard_user: str = "admin"
    adguard_password: str = "changeme"

    # Nginx / SSL
    domain: str = ""
    email: str = ""

    # Federation
    federation_secret: str = "change_federation_secret"
    bot_public_url: str = ""

    # Security
    secret_key: str = "change_secret_key_32chars"

    # App
    tz: str = "UTC"
    bot_lang: str = "ru"
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
