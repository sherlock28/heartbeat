import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.config import get_settings
from app.utils import fmt_dt, human_duration

log = logging.getLogger(__name__)


@dataclass
class AlertEvent:
    kind: str  # "down" | "up" | "test"
    client_name: str
    product_name: str
    vm_id: int
    vm_name: str
    host: str
    check_label: str
    at: datetime  # UTC naive
    description: Optional[str] = None
    error: Optional[str] = None
    down_since: Optional[datetime] = None  # solo en "up": cuándo se cayó


TITLES = {
    "down": "🔴 MÁQUINA CAÍDA",
    "up": "🟢 MÁQUINA RECUPERADA",
    "test": "🧪 Mensaje de prueba",
}


@dataclass
class Row:
    label: str
    value: str
    icon: Optional[str] = None  # icono conocido de Google Chat, opcional


def event_rows(event: AlertEvent) -> list[Row]:
    """Contenido común de los mensajes, independiente de la integración."""
    zone = get_settings().zone
    rows = [
        Row("Máquina", event.vm_name, "DESCRIPTION"),
        Row("IP / Host", event.host),
        Row("Chequeo", event.check_label),
        Row("Producto", event.product_name),
        Row("Cliente", event.client_name, "PERSON"),
    ]
    if event.description:
        rows.append(Row("Descripción", event.description))
    if event.kind == "down":
        rows.append(Row("Caída detectada", fmt_dt(event.at, zone), "CLOCK"))
        if event.error:
            rows.append(Row("Detalle", event.error))
    elif event.kind == "up":
        rows.append(Row("Recuperada", fmt_dt(event.at, zone), "CLOCK"))
        if event.down_since:
            duration = human_duration((event.at - event.down_since).total_seconds())
            rows.append(Row("Tiempo caída", f"{duration} (desde {fmt_dt(event.down_since, zone)})"))
    else:
        rows.append(Row("Enviado", fmt_dt(event.at, zone), "CLOCK"))
    return rows


@dataclass
class ConfigField:
    name: str
    label: str
    placeholder: str = ""
    help: str = ""
    secret: bool = False


@dataclass
class ChannelTarget:
    id: int
    type: str
    name: str
    config: dict = field(default_factory=dict)


class NotifierError(Exception):
    """Error de envío con un mensaje legible para el usuario."""


class Notifier(ABC):
    type: str
    label: str
    fields: list[ConfigField] = []
    help_html: str = ""  # instrucciones de configuración para el panel

    def clean_config(self, raw: dict) -> dict:
        return {f.name: (raw.get(f.name) or "").strip() for f in self.fields}

    def validate(self, config: dict) -> list[str]:
        return [f"«{f.label}» es obligatorio" for f in self.fields if not config.get(f.name)]

    @abstractmethod
    async def send(self, config: dict, event: AlertEvent) -> None:
        """Envía el evento. Lanza una excepción si falla."""


REGISTRY: dict[str, Notifier] = {}


def register(notifier: Notifier) -> Notifier:
    REGISTRY[notifier.type] = notifier
    return notifier


async def send_with_retry(channel: ChannelTarget, event: AlertEvent, attempts: int = 3) -> Optional[str]:
    """Devuelve None si se envió, o el último error."""
    notifier = REGISTRY.get(channel.type)
    if notifier is None:
        log.error("Canal %s: tipo de integración desconocido '%s'", channel.name, channel.type)
        return f"Integración desconocida: {channel.type}"
    error = None
    for attempt in range(1, attempts + 1):
        try:
            await notifier.send(channel.config, event)
            log.info("Notificación '%s' de %s enviada a %s", event.kind, event.vm_name, channel.name)
            return None
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            log.warning("Fallo enviando a %s (intento %d/%d): %s", channel.name, attempt, attempts, error)
            if attempt < attempts:
                await asyncio.sleep(2**attempt)
    log.error("No se pudo notificar a %s tras %d intentos", channel.name, attempts)
    return error


async def dispatch(channels: list[ChannelTarget], event: AlertEvent) -> bool:
    if not channels:
        log.info("Evento '%s' de %s sin canales configurados", event.kind, event.vm_name)
        return False
    errors = await asyncio.gather(*(send_with_retry(c, event) for c in channels))
    return any(e is None for e in errors)
