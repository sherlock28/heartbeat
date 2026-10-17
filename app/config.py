import logging
import secrets
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Panel
    admin_user: str = "admin"
    admin_password: str = "admin"
    secret_key: str = ""

    # Base de datos
    data_dir: str = "./data"

    # Monitor
    check_interval: int = 30  # segundos entre rondas de chequeo
    check_timeout: float = 2.0  # segundos por chequeo
    fail_threshold: int = 3  # fallos seguidos para considerar DOWN
    recover_threshold: int = 1  # éxitos seguidos para considerar UP
    notify_initial_down: bool = True  # avisar si una VM nueva/desconocida arranca caída
    max_concurrent_checks: int = 100
    icmp_privileged: bool = True  # en Docker corre como root: True

    # Presentación
    tz: str = "America/Argentina/Buenos_Aires"

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.secret_key:
        settings.secret_key = secrets.token_urlsafe(32)
        log.warning("SECRET_KEY no definido: se generó uno temporal (las sesiones se pierden al reiniciar)")
    if settings.admin_password == "admin":
        log.warning("ADMIN_PASSWORD usa el valor por defecto 'admin': cámbialo en .env")
    return settings
