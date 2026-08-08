from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = (
        "postgresql://scholens_app:replace-with-local-runtime-password@"
        "127.0.0.1:55432/sanchezcloud"
    )
