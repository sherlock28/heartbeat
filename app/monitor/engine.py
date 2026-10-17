import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Optional

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.config import Settings
from app.models import VM, Event, utcnow
from app.monitor.checks import CheckResult, run_check
from app.notifiers.base import AlertEvent, ChannelTarget, dispatch

log = logging.getLogger(__name__)

Checker = Callable[[str, str, Optional[int]], Awaitable[CheckResult]]
Dispatcher = Callable[[list[ChannelTarget], AlertEvent], Awaitable[bool]]


@dataclass
class Transition:
    kind: str  # "down" | "up"
    previous: str  # estado anterior
    notify: bool


def apply_result(vm: VM, result: CheckResult, now: datetime, settings: Settings) -> Optional[Transition]:
    """Actualiza contadores/estado de la VM y devuelve la transición si hubo cambio de estado."""
    vm.last_check_at = now
    if result.ok:
        vm.consecutive_successes += 1
        vm.consecutive_failures = 0
        vm.last_latency_ms = result.latency_ms
        vm.last_error = None
        if vm.status != "up" and vm.consecutive_successes >= settings.recover_threshold:
            previous = vm.status
            vm.status = "up"
            vm.last_change_at = now
            # unknown -> up es el estado inicial: no se avisa
            return Transition("up", previous, notify=previous == "down")
    else:
        vm.consecutive_failures += 1
        vm.consecutive_successes = 0
        vm.last_latency_ms = None
        vm.last_error = result.error
        if vm.status != "down" and vm.consecutive_failures >= settings.fail_threshold:
            previous = vm.status
            vm.status = "down"
            vm.last_change_at = now
            notify = previous == "up" or settings.notify_initial_down
            return Transition("down", previous, notify=notify)
    return None


class Monitor:
    def __init__(
        self,
        engine: Engine,
        settings: Settings,
        checker: Optional[Checker] = None,
        dispatcher: Dispatcher = dispatch,
    ):
        self.engine = engine
        self.settings = settings
        self.checker = checker or self._default_checker
        self.dispatcher = dispatcher
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_checks)
        self._task: Optional[asyncio.Task] = None
        self._pending: set[asyncio.Task] = set()
        self.last_run_at: Optional[datetime] = None

    async def _default_checker(self, check_type: str, host: str, port: Optional[int]) -> CheckResult:
        return await run_check(check_type, host, port, self.settings.check_timeout, self.settings.icmp_privileged)

    async def _guarded_check(self, check_type: str, host: str, port: Optional[int]) -> CheckResult:
        async with self._semaphore:
            return await self.checker(check_type, host, port)

    async def run_once(self) -> list[tuple[list[ChannelTarget], AlertEvent, int]]:
        """Ejecuta una ronda de chequeos. Devuelve las alertas a enviar (canales, evento, event_id)."""
        with Session(self.engine) as session:
            vms = session.exec(select(VM).where(VM.enabled == True)).all()  # noqa: E712
            targets = [(vm.id, vm.check_type, vm.ip, vm.port) for vm in vms]

        if not targets:
            self.last_run_at = utcnow()
            return []

        results = await asyncio.gather(*(self._guarded_check(t, h, p) for _, t, h, p in targets))
        now = utcnow()
        alerts: list[tuple[list[ChannelTarget], AlertEvent, Event]] = []

        with Session(self.engine) as session:
            for (vm_id, check_type, host, port), result in zip(targets, results):
                vm = session.get(VM, vm_id)
                # La VM pudo borrarse, deshabilitarse o cambiar de destino durante el chequeo
                if vm is None or not vm.enabled or (vm.check_type, vm.ip, vm.port) != (check_type, host, port):
                    continue
                down_since = vm.last_change_at
                transition = apply_result(vm, result, now, self.settings)
                if transition is None:
                    continue

                detail = result.error if transition.kind == "down" else f"Latencia {result.latency_ms} ms"
                if transition.previous == "unknown":
                    detail = f"Estado inicial. {detail or ''}".strip()
                event = Event(vm_id=vm.id, kind=transition.kind, at=now, detail=detail)
                session.add(event)
                log.info("VM %s (%s): %s -> %s", vm.name, vm.ip, transition.previous, transition.kind)

                if transition.notify:
                    product = vm.product
                    client = product.client
                    channels = [
                        ChannelTarget(c.id, c.type, c.name, dict(c.config)) for c in client.channels if c.enabled
                    ]
                    alert = AlertEvent(
                        kind=transition.kind,
                        client_name=client.name,
                        product_name=product.name,
                        vm_id=vm.id,
                        vm_name=vm.name,
                        host=vm.ip,
                        check_label=vm.check_label,
                        description=vm.description,
                        at=now,
                        error=result.error,
                        down_since=down_since if transition.kind == "up" else None,
                    )
                    alerts.append((channels, alert, event))
            session.commit()
            pending = [(channels, alert, event.id) for channels, alert, event in alerts]

        self.last_run_at = now
        return pending

    async def _notify(self, channels: list[ChannelTarget], alert: AlertEvent, event_id: int) -> None:
        try:
            sent = await self.dispatcher(channels, alert)
        except Exception:
            log.exception("Error despachando notificación")
            return
        if sent:
            with Session(self.engine) as session:
                event = session.get(Event, event_id)
                if event:
                    event.notified = True
                    session.add(event)
                    session.commit()

    def _spawn_notifications(self, pending) -> None:
        # Las notificaciones (con reintentos) no deben retrasar la siguiente ronda de chequeos
        for channels, alert, event_id in pending:
            task = asyncio.create_task(self._notify(channels, alert, event_id))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)

    async def run_forever(self) -> None:
        log.info(
            "Monitor iniciado: cada %ss, %d fallos para DOWN, %d éxitos para UP",
            self.settings.check_interval,
            self.settings.fail_threshold,
            self.settings.recover_threshold,
        )
        loop = asyncio.get_running_loop()
        while True:
            started = loop.time()
            try:
                self._spawn_notifications(await self.run_once())
            except Exception:
                log.exception("Error en la ronda de chequeos")
            elapsed = loop.time() - started
            await asyncio.sleep(max(self.settings.check_interval - elapsed, 1))

    def start(self) -> None:
        self._task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._pending:
            await asyncio.wait(self._pending, timeout=5)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()
