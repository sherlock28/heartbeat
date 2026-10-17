import html

import httpx

from app.notifiers.base import TITLES, AlertEvent, ConfigField, Notifier, event_rows, register


def build_payload(event: AlertEvent) -> dict:
    title = TITLES.get(event.kind, event.kind)
    widgets = []
    for row in event_rows(event):
        text = html.escape(row.value)
        if row.label == "Máquina":
            text = f"<b>{text}</b>"
        widget: dict = {"topLabel": row.label, "text": text, "wrapText": True}
        if row.icon:
            widget["startIcon"] = {"knownIcon": row.icon}
        widgets.append({"decoratedText": widget})

    summary = f"{title}: {event.vm_name} ({event.host}) · {event.product_name} · {event.client_name}"
    return {
        "fallbackText": summary,
        "cardsV2": [
            {
                "cardId": f"vm-{event.vm_id}-{event.kind}",
                "card": {
                    "header": {"title": title, "subtitle": f"{event.client_name} · {event.product_name}"},
                    "sections": [{"widgets": widgets}],
                },
            }
        ],
        "thread": {"threadKey": f"vm-{event.vm_id}"},
    }


class GoogleChatNotifier(Notifier):
    type = "google_chat"
    label = "Google Chat"
    fields = [
        ConfigField(
            "webhook_url",
            "URL del webhook",
            placeholder="https://chat.googleapis.com/v1/spaces/…/messages?key=…&token=…",
            secret=True,
        )
    ]
    help_html = (
        "<ol>"
        "<li>En Google Chat abre el espacio donde quieres recibir los avisos.</li>"
        "<li>Ve a <em>Apps e integraciones</em> → <em>Webhooks</em> → <em>Agregar webhook</em>.</li>"
        "<li>Copia la URL y pégala en el formulario.</li>"
        "</ol>"
    )

    def validate(self, config: dict) -> list[str]:
        errors = super().validate(config)
        if config.get("webhook_url") and not config["webhook_url"].startswith("https://"):
            errors.append("El webhook debe ser una URL https://")
        return errors

    async def send(self, config: dict, event: AlertEvent) -> None:
        # Agrupa caída y recuperación de una misma VM en el mismo hilo del espacio
        url = httpx.URL(config["webhook_url"]).copy_merge_params(
            {"messageReplyOption": "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"}
        )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=build_payload(event))
            resp.raise_for_status()


register(GoogleChatNotifier())
