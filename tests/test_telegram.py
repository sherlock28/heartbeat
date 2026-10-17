import asyncio
from datetime import datetime, timedelta

import httpx
import pytest

from app.notifiers import REGISTRY
from app.notifiers.base import AlertEvent, NotifierError
from app.notifiers import telegram
from app.notifiers.telegram import build_text, discover_chats

TOKEN = "123456789:AAHabcdefghijklmnopqrstuvwxyz012345"


def _event(**kw):
    base = dict(
        kind="down",
        client_name="ACME <S.A.>",
        product_name="Portal",
        vm_id=7,
        vm_name="db-01",
        host="10.0.0.2",
        check_label="TCP:5432",
        at=datetime(2026, 10, 16, 15, 0, 0),
        description="Base de datos",
        error="Timeout conectando a 10.0.0.2:5432",
    )
    base.update(kw)
    return AlertEvent(**base)


def test_down_text_is_escaped_html():
    text = build_text(_event())
    assert text.startswith("<b>🔴 MÁQUINA CAÍDA</b>")
    assert "Máquina: <b>db-01</b>" in text
    assert "IP / Host: <code>10.0.0.2</code>" in text
    assert "Cliente: ACME &lt;S.A.&gt;" in text  # sin HTML inyectado
    assert "Detalle: <i>Timeout" in text


def test_up_text_has_duration():
    at = datetime(2026, 10, 16, 15, 12, 0)
    text = build_text(_event(kind="up", at=at, down_since=at - timedelta(minutes=12), error=None))
    assert "RECUPERADA" in text
    assert "Tiempo caída: 12 min" in text


def test_validation():
    n = REGISTRY["telegram"]
    assert n.validate({"bot_token": TOKEN, "chat_id": "123456"}) == []
    assert n.validate({"bot_token": TOKEN, "chat_id": "-1001234567890"}) == []
    assert n.validate({"bot_token": TOKEN, "chat_id": "@mi_canal"}) == []
    assert len(n.validate({"bot_token": "", "chat_id": ""})) == 2
    assert len(n.validate({"bot_token": "nope", "chat_id": "abc"})) == 2


def _mock_transport(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(telegram.httpx, "AsyncClient", factory)


def test_send_posts_html_message(monkeypatch):
    seen = {}

    def handler(request: httpx.Request):
        seen["path"] = request.url.path
        seen["json"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    _mock_transport(monkeypatch, handler)
    asyncio.run(REGISTRY["telegram"].send({"bot_token": TOKEN, "chat_id": "42"}, _event()))
    assert seen["path"] == f"/bot{TOKEN}/sendMessage"
    assert seen["json"]["chat_id"] == "42"
    assert seen["json"]["parse_mode"] == "HTML"


def test_api_error_is_readable_and_hides_token(monkeypatch):
    _mock_transport(
        monkeypatch, lambda r: httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})
    )
    with pytest.raises(NotifierError) as exc:
        asyncio.run(REGISTRY["telegram"].send({"bot_token": TOKEN, "chat_id": "1"}, _event()))
    assert "chat not found" in str(exc.value)
    assert TOKEN not in str(exc.value)


def test_discover_chats(monkeypatch):
    updates = [
        {"update_id": 1, "message": {"chat": {"id": 42, "type": "private", "first_name": "Rodo"}}},
        {"update_id": 2, "message": {"chat": {"id": 42, "type": "private", "first_name": "Rodo"}}},
        {"update_id": 3, "my_chat_member": {"chat": {"id": -100555, "type": "supergroup", "title": "Soporte"}}},
    ]
    _mock_transport(monkeypatch, lambda r: httpx.Response(200, json={"ok": True, "result": updates}))
    chats = asyncio.run(discover_chats(TOKEN))
    assert chats == [
        {"id": "42", "name": "Rodo", "type": "private"},
        {"id": "-100555", "name": "Soporte", "type": "supergroup"},
    ]
