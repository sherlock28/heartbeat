import html
import re

import httpx

from app.notifiers.base import TITLES, AlertEvent, ConfigField, Notifier, NotifierError, event_rows, register

API = "https://api.telegram.org/bot{token}/{method}"
TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
CHAT_ID_RE = re.compile(r"^(-?\d+|@[A-Za-z][A-Za-z0-9_]{3,})$")


def build_text(event: AlertEvent) -> str:
    """Mensaje en HTML (parse_mode=HTML) de Telegram."""
    esc = html.escape
    lines = [f"<b>{TITLES.get(event.kind, event.kind)}</b>", ""]
    for row in event_rows(event):
        value = esc(row.value)
        if row.label == "Máquina":
            value = f"<b>{value}</b>"
        elif row.label == "IP / Host":
            value = f"<code>{value}</code>"
        elif row.label == "Detalle":
            value = f"<i>{value}</i>"
        lines.append(f"{esc(row.label)}: {value}")
    return "\n".join(lines)


async def _call(token: str, method: str, payload: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(API.format(token=token, method=method), json=payload or {})
        except httpx.HTTPError as exc:
            raise NotifierError(f"No se pudo conectar con Telegram: {exc}") from exc
    try:
        data = resp.json()
    except ValueError:
        resp.raise_for_status()
        raise NotifierError(f"Respuesta inesperada de Telegram (HTTP {resp.status_code})")
    if not data.get("ok"):
        # No incluir la URL: contiene el token del bot
        raise NotifierError(f"Telegram: {data.get('description', 'error desconocido')}")
    return data["result"]


async def discover_chats(token: str) -> list[dict]:
    """Chats que escribieron recientemente al bot (o a los que fue agregado)."""
    updates = await _call(token, "getUpdates", {"allowed_updates": ["message", "channel_post", "my_chat_member"]})
    chats: dict[int, dict] = {}
    for upd in updates:
        for key in ("message", "channel_post", "my_chat_member"):
            chat = (upd.get(key) or {}).get("chat")
            if chat:
                name = chat.get("title") or " ".join(
                    p for p in (chat.get("first_name"), chat.get("last_name")) if p
                ) or chat.get("username") or str(chat["id"])
                chats[chat["id"]] = {"id": str(chat["id"]), "name": name, "type": chat.get("type", "")}
    return list(chats.values())


class TelegramNotifier(Notifier):
    type = "telegram"
    label = "Telegram"
    fields = [
        ConfigField(
            "bot_token",
            "Token del bot",
            placeholder="123456789:AAH…",
            secret=True,
        ),
        ConfigField(
            "chat_id",
            "Chat ID",
            placeholder="123456789 o -100123… (grupos)",
        ),
    ]
    help_html = (
        "<ol>"
        "<li>En Telegram habla con <b>@BotFather</b>, envía <code>/newbot</code> y copia el token.</li>"
        "<li>Abre el chat con tu bot y envíale <code>/start</code> (o agrégalo a un grupo y escribe algo).</li>"
        "<li>Pega el token y pulsa <b>Detectar</b> para completar el Chat ID.</li>"
        "</ol>"
    )

    def validate(self, config: dict) -> list[str]:
        errors = super().validate(config)
        if config.get("bot_token") and not TOKEN_RE.match(config["bot_token"]):
            errors.append("El token del bot no tiene el formato esperado (123456789:AAH…)")
        if config.get("chat_id") and not CHAT_ID_RE.match(config["chat_id"]):
            errors.append("El Chat ID debe ser numérico (p. ej. 123456789 o -100123…) o @canal")
        return errors

    async def send(self, config: dict, event: AlertEvent) -> None:
        await _call(
            config["bot_token"],
            "sendMessage",
            {
                "chat_id": config["chat_id"],
                "text": build_text(event),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )


register(TelegramNotifier())
