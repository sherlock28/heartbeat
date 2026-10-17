import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

from app.db import init_db, make_engine
from app.models import VM, Client, Product
from app.routes.products import VMS_PER_PAGE, search_vms
from app.web import highlight


@pytest.fixture
def session():
    eng = make_engine("sqlite://", poolclass=StaticPool)
    init_db(eng)
    with Session(eng) as s:
        client = Client(name="ACME")
        s.add(client)
        s.commit()
        product = Product(client_id=client.id, name="Portal")
        other = Product(client_id=client.id, name="Otro")
        s.add_all([product, other])
        s.commit()
        for i in range(23):
            s.add(VM(product_id=product.id, name=f"app-{i:02d}", ip=f"10.0.0.{i}"))
        s.add(VM(product_id=product.id, name="DB_Main", ip="192.168.1.50"))
        s.add(VM(product_id=other.id, name="app-ajena", ip="10.9.9.9"))
        s.commit()
        yield s, product.id


def test_pagination(session):
    s, pid = session
    first = search_vms(s, pid)
    assert first.total == 24 and first.pages == 3 and len(first.items) == VMS_PER_PAGE
    last = search_vms(s, pid, page=99)  # se ajusta a la última página
    assert last.page == 3 and len(last.items) == 4 and (last.start, last.end) == (21, 24)


def test_search_by_name_ip_case_insensitive_and_scoped(session):
    s, pid = session
    assert [v.name for v in search_vms(s, pid, "db_").items] == ["DB_Main"]
    assert [v.name for v in search_vms(s, pid, "168.1").items] == ["DB_Main"]
    assert search_vms(s, pid, "app").total == 23  # no incluye la VM del otro producto
    assert search_vms(s, pid, "%").total == 0  # comodines tratados como texto
    empty = search_vms(s, pid, "nada")
    assert empty.total == 0 and (empty.start, empty.end) == (0, 0)


def test_highlight_escapes_html():
    assert str(highlight("App-01", "app")) == "<mark>App</mark>-01"
    assert str(highlight("<b>x</b>", "x")) == "&lt;b&gt;<mark>x</mark>&lt;/b&gt;"
    assert str(highlight("abc", None)) == "abc"


def test_client_products_and_channels_pages(session):
    from app.models import NotificationChannel
    from app.routes.clients import CHANNELS_PER_PAGE, channels_page, products_page

    s, pid = session
    cid = s.get(Product, pid).client_id
    for i in range(CHANNELS_PER_PAGE + 2):
        s.add(NotificationChannel(client_id=cid, name=f"canal-{i}", type="telegram", config={}))
    s.commit()
    prods = products_page(s, cid)
    assert prods.total == 2 and [p.name for p in prods.items] == ["Otro", "Portal"]
    chans = channels_page(s, cid, page=2)
    assert chans.pages == 2 and chans.total == CHANNELS_PER_PAGE + 2 and len(chans.items) == 2


def test_vm_events_newest_first_paginated(session):
    from datetime import timedelta

    from app.models import Event, utcnow
    from app.routes.vms import EVENTS_PER_PAGE, _events

    s, pid = session
    vm = search_vms(s, pid, "DB_Main").items[0]
    now = utcnow()
    for i in range(EVENTS_PER_PAGE + 3):
        s.add(Event(vm_id=vm.id, kind="down" if i % 2 else "up", at=now + timedelta(minutes=i), detail=str(i)))
    s.commit()
    first = _events(s, vm.id)
    assert first.total == EVENTS_PER_PAGE + 3 and first.items[0].detail == str(EVENTS_PER_PAGE + 2)
    assert len(_events(s, vm.id, page=2).items) == 3


def test_vm_events_date_filter(session, monkeypatch):
    from datetime import datetime

    from app.config import Settings
    from app.models import Event
    from app.routes import vms
    from app.routes.vms import EventFilter, _events

    monkeypatch.setattr(vms, "get_settings", lambda: Settings(_env_file=None, secret_key="x", tz="UTC"))
    s, pid = session
    vm = search_vms(s, pid, "DB_Main").items[0]
    for day, hour in [(15, 10), (16, 9), (16, 18), (17, 2)]:
        s.add(Event(vm_id=vm.id, kind="up", at=datetime(2026, 10, day, hour, 0, 30)))
    s.commit()

    def hours(**kw):
        return [(e.at.day, e.at.hour) for e in _events(s, vm.id, filt=EventFilter.parse(**kw)).items]

    assert hours(desde="2026-10-16T09:00") == [(17, 2), (16, 18), (16, 9)]
    assert hours(hasta="2026-10-16T09:00") == [(16, 9), (15, 10)]  # incluye todo el minuto de "hasta"
    assert hours(desde="2026-10-16T00:00", hasta="2026-10-16T23:59") == [(16, 18), (16, 9)]
    assert EventFilter.parse(desde="2026-10-17T00:00", hasta="2026-10-16T00:00").error
    assert EventFilter.parse(desde="basura").error


def test_dashboard_puts_down_vms_first(session):
    from app.routes.dashboard import DASHBOARD_VMS_PER_PAGE, dashboard_vms

    s, pid = session
    vms = {v.name: v for v in search_vms(s, pid, page=1).items + search_vms(s, pid, page=3).items}
    vms["app-22"].status = "down"  # quedaría en la última página por nombre
    vms["app-00"].enabled = False
    s.commit()
    first = dashboard_vms(s, pid)
    assert first.items[0].name == "app-22" and len(first.items) == DASHBOARD_VMS_PER_PAGE
    assert dashboard_vms(s, pid, page=first.pages).items[-1].name == "app-00"  # pausadas al final


def test_client_vms_spans_all_products_of_the_client(session):
    from app.routes.dashboard import client_vms

    s, pid = session
    cid = s.get(Product, pid).client_id
    other = Client(name="Otro cliente")
    s.add(other)
    s.commit()
    names = {v.name for v in client_vms(s, cid)}
    assert len(names) == 25 and "app-ajena" in names  # 24 de "Portal" + 1 de "Otro"
    assert client_vms(s, other.id) == []
