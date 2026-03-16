from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Only TRUE secrets and infrastructure constants live here.
    Runtime-editable settings (domain, tz, bot_lang) are stored exclusively
    in the AppSetting DB table — seeded from data/init.json on first startup.
    The first user to send /start to the bot becomes the admin (no ADMIN_IDS needed).
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Telegram ───────────────────────────────────────────────────────────────
    bot_token: str = ""

    # ── API auth (shared secrets, never change after install) ──────────────────
    internal_token: str = "change_internal_token"
    jwt_secret: str = "change_jwt_secret_32chars"
    jwt_expire_minutes: int = 60 * 24 * 7          # 7 days

    # ── Web UI — initial credentials (web_users table takes over after first run)
    web_admin_user: str = "admin"
    web_admin_password: str = "changeme"

    # ── Sing-Box ───────────────────────────────────────────────────────────────
    singbox_config_path: str = "/etc/sing-box/config.json"
    singbox_container: str = "singbox_core"

    # ── AdGuard ────────────────────────────────────────────────────────────────
    adguard_url: str = "http://adguard:3000"
    adguard_user: str = "admin"
    adguard_password: str = "changeme"
    adguard_container: str = "singbox_adguard"
    adguard_config_path: str = "/app/config/adguard/AdGuardHome.yaml"

    # ── Federation ────────────────────────────────────────────────────────────
    federation_secret: str = "change_federation_secret"
    bot_public_url: str = ""

    # ── Security ──────────────────────────────────────────────────────────────
    secret_key: str = "change_secret_key_32chars"

    # ── Webhook (infrastructure, not runtime-editable) ───────────────────────
    webhook_host: str = ""
    webhook_path: str = "/webhook"
    webhook_port: int = 8080
    webhook_secret: str = ""

    @property
    def use_webhook(self) -> bool:
        return bool(self.webhook_host)

    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_host}{self.webhook_path}"


settings = Settings()
