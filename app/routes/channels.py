from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session

from app.auth import require_login
from app.db import get_session
from app.models import Client, NotificationChannel, utcnow
from app.notifiers import REGISTRY, AlertEvent, ChannelTarget, send_with_retry
from app.notifiers.base import NotifierError
from app.notifiers.telegram import discover_chats
from app.web import clean, flash, get_or_404, redirect, render

router = APIRouter(dependencies=[Depends(require_login)])

DEFAULT_TYPE = "telegram"


async def _read_form(request: Request) -> dict:
    """Lee el formulario. Los campos de cada integración vienen como <tipo>__<campo>."""
    form = await request.form()
    ch_type = form.get("type") or DEFAULT_TYPE
    notifier = REGISTRY.get(ch_type)
    raw = {k.split("__", 1)[1]: v for k, v in form.items() if k.startswith(f"{ch_type}__")}
    return {
        "name": form.get("name", ""),
        "type": ch_type,
        "enabled": form.get("enabled") == "true",
        "config": notifier.clean_config(raw) if notifier else {},
    }


def _validate(values: dict) -> list[str]:
    errors = []
    if not clean(values["name"]):
        errors.append("El nombre es obligatorio")
    notifier = REGISTRY.get(values["type"])
    if notifier is None:
        errors.append("Tipo de integración inválido")
    else:
        errors += notifier.validate(values["config"])
    return errors


def _form_values(channel: NotificationChannel) -> dict:
    return {"name": channel.name, "type": channel.type, "enabled": channel.enabled, "config": dict(channel.config)}


@router.get("/clients/{client_id}/channels/new")
def new_channel(request: Request, client_id: int, session: Session = Depends(get_session)):
    client = get_or_404(session, Client, client_id)
    values = {"type": DEFAULT_TYPE, "enabled": True, "config": {}}
    return render(request, "channel.html", client=client, channel=None, values=values, errors=[])


@router.post("/clients/{client_id}/channels")
async def create_channel(request: Request, client_id: int, session: Session = Depends(get_session)):
    client = get_or_404(session, Client, client_id)
    values = await _read_form(request)
    errors = _validate(values)
    if errors:
        return render(request, "channel.html", 422, client=client, channel=None, values=values, errors=errors)
    channel = NotificationChannel(
        client_id=client.id,
        name=clean(values["name"]),
        type=values["type"],
        config=values["config"],
        enabled=values["enabled"],
    )
    session.add(channel)
    session.commit()
    flash(request, f"Canal «{channel.name}» creado. Usa «Enviar prueba» para validarlo.")
    return redirect(f"/clients/{client.id}")


@router.get("/channels/{channel_id}")
def channel_detail(request: Request, channel_id: int, session: Session = Depends(get_session)):
    channel = get_or_404(session, NotificationChannel, channel_id)
    return render(request, "channel.html", client=channel.client, channel=channel, values=_form_values(channel), errors=[])


@router.post("/channels/{channel_id}")
async def update_channel(request: Request, channel_id: int, session: Session = Depends(get_session)):
    channel = get_or_404(session, NotificationChannel, channel_id)
    values = await _read_form(request)
    errors = _validate(values)
    if errors:
        return render(request, "channel.html", 422, client=channel.client, channel=channel, values=values, errors=errors)
    channel.name = clean(values["name"])
    channel.type = values["type"]
    channel.config = values["config"]
    channel.enabled = values["enabled"]
    session.add(channel)
    session.commit()
    flash(request, "Canal actualizado")
    return redirect(f"/clients/{channel.client_id}")


@router.post("/channels/{channel_id}/delete")
def delete_channel(request: Request, channel_id: int, session: Session = Depends(get_session)):
    channel = get_or_404(session, NotificationChannel, channel_id)
    client_id = channel.client_id
    name = channel.name
    session.delete(channel)
    session.commit()
    flash(request, f"Canal «{name}» eliminado")
    return redirect(f"/clients/{client_id}")


@router.post("/channels/{channel_id}/test")
async def test_channel(request: Request, channel_id: int, session: Session = Depends(get_session)):
    channel = get_or_404(session, NotificationChannel, channel_id)
    client = channel.client
    event = AlertEvent(
        kind="test",
        client_name=client.name,
        product_name="(prueba)",
        vm_id=0,
        vm_name="Mensaje de prueba",
        host="0.0.0.0",
        check_label="—",
        at=utcnow(),
        description="Si ves este mensaje, el canal está bien configurado.",
    )
    target = ChannelTarget(channel.id, channel.type, channel.name, dict(channel.config))
    error = await send_with_retry(target, event, attempts=1)
    if error is None:
        flash(request, f"Mensaje de prueba enviado a «{channel.name}»")
    else:
        flash(request, f"No se pudo enviar a «{channel.name}»: {error}", "error")
    return redirect(f"/clients/{client.id}")


@router.post("/channels/telegram/chats")
async def telegram_chats(request: Request, telegram__bot_token: str = Form("")):
    """Parcial HTMX: lista los chats que escribieron al bot para elegir el Chat ID."""
    token = telegram__bot_token.strip()
    chats, error = [], None
    if not token:
        error = "Primero pega el token del bot."
    else:
        try:
            chats = await discover_chats(token)
        except NotifierError as exc:
            error = str(exc)
    return render(request, "_telegram_chats.html", flash=None, chats=chats, error=error)
