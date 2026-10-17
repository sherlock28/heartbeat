import ipaddress
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$")


def is_valid_host(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return bool(_HOSTNAME_RE.match(value))


def to_local(dt: datetime | None, zone: ZoneInfo) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(zone)


def fmt_dt(dt: datetime | None, zone: ZoneInfo) -> str:
    local = to_local(dt, zone)
    return local.strftime("%d/%m/%Y %H:%M:%S") if local else "—"


def human_duration(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} d")
    if hours:
        parts.append(f"{hours} h")
    if minutes:
        parts.append(f"{minutes} min")
    if secs and not days and not hours:
        parts.append(f"{secs} s")
    return " ".join(parts) or "0 s"


def parse_local_input(value: str | None, zone: ZoneInfo) -> datetime | None:
    """Convierte un <input type="datetime-local"> (hora local del panel) a UTC naive, como se guarda en la DB.

    Lanza ValueError si el texto no es una fecha válida.
    """
    value = (value or "").strip()
    if not value:
        return None
    local = datetime.fromisoformat(value).replace(tzinfo=zone)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def end_of_input_minute(value: str) -> timedelta:
    """El input sin segundos ("2026-10-17T02:07") representa todo ese minuto: el "hasta" lo incluye entero."""
    return timedelta(minutes=1) if len(value.strip()) <= 16 else timedelta(seconds=1)
