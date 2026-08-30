from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    app_name: str = "DELTA 时空交易终端"
    app_version: str = "0.1.0"
    environment: str = "development"
    cors_origins: str = "http://localhost:5184,http://127.0.0.1:5184"
    news_enabled: bool = True
    news_cache_ttl_seconds: int = 900
    news_rss_timeout_seconds: int = 15
    news_cnbc_enabled: bool = True
    news_marketwatch_enabled: bool = True
    finnhub_api_key: str = ""
    twelve_data_api_key: str = ""
    fred_api_key: str = ""
    sec_user_agent: str = "DELTA-Research-Terminal/0.1 research@example.invalid"
    options_enabled: bool = True
    stock_pool_enabled: bool = True
    model_config = SettingsConfigDict(env_file="../.env", env_prefix="DELTA_", case_sensitive=False, extra="ignore")
    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
@lru_cache
def get_settings() -> Settings:
    return Settings()
