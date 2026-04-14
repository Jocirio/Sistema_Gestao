from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    # Banco de dados
    database_url: str

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 30

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # E-mail
    mail_username: str = ""
    mail_password: str = ""
    mail_from: str = ""
    mail_from_name: str = "Sistema de Gestão"
    mail_server: str = "smtp.sendgrid.net"
    mail_port: int = 587
    mail_starttls: bool = True
    mail_ssl_tls: bool = False

    # Storage (buckets do Supabase)
    storage_bucket_photos: str = "report-photos"
    storage_bucket_signatures: str = "report-signatures"
    storage_bucket_documents: str = "documents"
    storage_bucket_logos: str = "company-logos"

    # Ambiente
    environment: str = "development"
    debug: bool = True
    allowed_origins: str = "http://localhost:3000"

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
