from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str = "redis://redis:6379/0"

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60

    internal_api_key: str
    crypto_key: str

    heartbeat_grace_seconds: int = 300
    charge_interval_seconds: int = 20
    provisioning_interval_seconds: int = 15


settings = Settings()