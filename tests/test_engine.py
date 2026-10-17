import asyncio
from datetime import timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, select

from app.config import Settings
from app.db import init_db, make_engine
from app.models import VM, Client, Event, NotificationChannel, Product, utcnow
from app.monitor.checks import CheckResult
from app.monitor.engine import Monitor, apply_result

OK = CheckResult(True, latency_ms=1.5)
FAIL = CheckResult(False, error="Sin respuesta a ping")


def settings(**kw) -> Settings:
    base = dict(_env_file=None, fail_threshold=3, recover_threshold=1, notify_initial_down=True, secret_key="x")
    base.update(kw)
    return Settings(**base)


# ---------- máquina de estados pura ----------

def run_sequence(vm: VM, seq, cfg: Settings):
    out = []
    now = utcnow()
    for i, res in enumerate(seq):
        t = apply_result(vm, res, now + timedelta(seconds=30 * i), cfg)
        out.append((t.kind, t.notify) if t else None)
    return out


def test_initial_up_is_silent():
    vm = VM(product_id=1, name="a", ip="1.1.1.1")
    assert run_sequence(vm, [OK, OK], settings()) == [("up", False), None]
    assert vm.status == "up"


def test_down_requires_threshold_and_notifies_once():
    vm = VM(product_id=1, name="a", ip="1.1.1.1", status="up")
    result = run_sequence(vm, [FAIL, FAIL, FAIL, FAIL, FAIL], settings())
    assert result == [None, None, ("down", True), None, None]


def test_flapping_below_threshold_never_notifies():
    vm = VM(product_id=1, name="a", ip="1.1.1.1", status="up")
    result = run_sequence(vm, [FAIL, FAIL, OK, FAIL, FAIL, OK], settings())
    assert all(r is None for r in result)
    assert vm.status == "up"


def test_recovery_notifies_once():
    vm = VM(product_id=1, name="a", ip="1.1.1.1", status="down")
    assert run_sequence(vm, [OK, OK, OK], settings()) == [("up", True), None, None]


def test_recover_threshold():
    vm = VM(product_id=1, name="a", ip="1.1.1.1", status="down")
    assert run_sequence(vm, [OK, FAIL, OK, OK], settings(recover_threshold=2)) == [None, None, None, ("up", True)]


def test_initial_down_respects_setting():
    vm = VM(product_id=1, name="a", ip="1.1.1.1")
    assert run_sequence(vm, [FAIL] * 3, settings(notify_initial_down=False))[-1] == ("down", False)
    vm = VM(product_id=1, name="a", ip="1.1.1.1")
    assert run_sequence(vm, [FAIL] * 3, settings(notify_initial_down=True))[-1] == ("down", True)


# ---------- monitor completo con DB en memoria ----------

@pytest.fixture
def engine():
    eng = make_engine("sqlite://", poolclass=StaticPool)
    init_db(eng)
    with Session(eng) as s:
        client = Client(name="ACME")
        s.add(client)
        s.commit()
        product = Product(client_id=client.id, name="Portal")
        s.add(product)
        s.commit()
        s.add(
            NotificationChannel(
                client_id=client.id, name="tg", type="telegram", config={"bot_token": "1:x", "chat_id": "42"}
            )
        )
        s.add(VM(product_id=product.id, name="app-01", ip="10.0.0.1", description="API + Front"))
        s.add(VM(product_id=product.id, name="db-01", ip="10.0.0.2", check_type="tcp", port=5432))
        s.commit()
    return eng


def test_monitor_notifies_only_on_transitions(engine):
    state = {"10.0.0.1": OK, "10.0.0.2": OK}
    sent = []

    async def checker(check_type, host, port):
        return state[host]

    async def dispatcher(channels, alert):
        assert [c.config["chat_id"] for c in channels] == ["42"]
        sent.append((alert.vm_name, alert.kind, alert.down_since is not None))
        return True

    async def scenario():
        mon = Monitor(engine, settings(), checker=checker, dispatcher=dispatcher)

        async def tick():
            for args in await mon.run_once():
                await mon._notify(*args)

        await tick()  # estado inicial: ambas up, sin avisos
        assert sent == []

        state["10.0.0.2"] = FAIL
        for _ in range(5):
            await tick()
        assert sent == [("db-01", "down", False)]

        state["10.0.0.2"] = OK
        for _ in range(3):
            await tick()
        assert sent == [("db-01", "down", False), ("db-01", "up", True)]

    asyncio.run(scenario())

    with Session(engine) as s:
        events = s.exec(select(Event).order_by(Event.id)).all()
        assert [(e.kind, e.notified) for e in events] == [
            ("up", False),
            ("up", False),
            ("down", True),
            ("up", True),
        ]


def test_monitor_skips_disabled_vms(engine):
    with Session(engine) as s:
        for vm in s.exec(select(VM)).all():
            vm.enabled = False
            s.add(vm)
        s.commit()

    called = []

    async def checker(*args):
        called.append(args)
        return OK

    asyncio.run(Monitor(engine, settings(), checker=checker).run_once())
    assert called == []
