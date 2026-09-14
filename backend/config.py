from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dev.db"

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    device_token_pepper: str = "dev-only-pepper-change-me"

    pairing_code_ttl_seconds: int = 300
    pairing_max_attempts: int = 5
    device_token_ttl_days: int = 30
    dashboard_session_secret: str = "dev-only-secret-change-me"

    # Ràng buộc cứng theo CLAUDE.md: mặc định tắt hành động thật cho adapter
    # chưa kiểm thử, không được bật ngầm bằng cấu hình sai.
    live_actions_enabled: bool = False
    yahoo_adapter: str = "mock"
    default_unknown_cost_policy: str = "BLOCK"

    # Chỉ dùng khi yahoo_adapter=mock: file JSON dùng chung để API và
    # worker (hai tiến trình riêng) thấy cùng dữ liệu seed. Để trống =
    # mỗi tiến trình giữ state riêng trong bộ nhớ (đủ cho unit test).
    mock_adapter_state_file: str = ""

    yahoo_playwright_profile_dir: str = "./.playwright-profile"
    yahoo_adapter_headless: bool = True
    yahoo_allowed_nav_domains: str = "auctions.yahoo.co.jp,login.yahoo.co.jp,payment.yahoo.co.jp"

    preview_ttl_seconds: int = 180
    worker_poll_interval_seconds: float = 2.0
    worker_heartbeat_seconds: float = 10.0

    log_level: str = "INFO"

    @property
    def allowed_nav_domains(self) -> list[str]:
        return [d.strip() for d in self.yahoo_allowed_nav_domains.split(",") if d.strip()]


settings = Settings()
