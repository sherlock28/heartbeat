from datetime import datetime, timedelta

from app.notifiers.base import AlertEvent
from app.notifiers.google_chat import build_payload


def _event(**kw):
    base = dict(
        kind="down",
        client_name="ACME",
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


def _texts(payload):
    widgets = payload["cardsV2"][0]["card"]["sections"][0]["widgets"]
    return {w["decoratedText"]["topLabel"]: w["decoratedText"]["text"] for w in widgets}


def test_down_payload():
    p = build_payload(_event())
    assert p["thread"]["threadKey"] == "vm-7"
    assert "CAÍDA" in p["cardsV2"][0]["card"]["header"]["title"]
    texts = _texts(p)
    assert texts["IP / Host"] == "10.0.0.2"
    assert texts["Chequeo"] == "TCP:5432"
    assert texts["Descripción"] == "Base de datos"
    assert "Timeout" in texts["Detalle"]
    assert "db-01" in p["fallbackText"]


def test_up_payload_has_duration():
    at = datetime(2026, 10, 16, 15, 12, 0)
    p = build_payload(_event(kind="up", at=at, down_since=at - timedelta(minutes=12), error=None))
    assert "RECUPERADA" in p["cardsV2"][0]["card"]["header"]["title"]
    assert _texts(p)["Tiempo caída"].startswith("12 min")
    assert p["thread"]["threadKey"] == "vm-7"
