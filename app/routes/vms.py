from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session, col, select

from app.auth import require_login
from app.config import get_settings
from app.db import get_session
from app.models import VM, Event, Product
from app.pagination import Page, paginate
from app.utils import end_of_input_minute, is_valid_host, parse_local_input
from app.web import clean, flash, get_or_404, redirect, render

router = APIRouter(dependencies=[Depends(require_login)])


def _validate(values: dict) -> tuple[list[str], int | None]:
    errors = []
    if not clean(values["name"]):
        errors.append("El nombre es obligatorio")
    if not is_valid_host((values["ip"] or "").strip()):
        errors.append("La IP o el hostname no son válidos")
    if values["check_type"] not in ("icmp", "tcp"):
        errors.append("Tipo de chequeo inválido")
    port = None
    if values["check_type"] == "tcp":
        try:
            port = int(values["port"])
            if not 1 <= port <= 65535:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("Para chequeo TCP indica un puerto entre 1 y 65535")
    return errors, port


EVENTS_PER_PAGE = 10


@dataclass
class EventFilter:
    """Rango de fechas del historial. `desde`/`hasta` son los valores crudos de los inputs (hora local)."""

    desde: str = ""
    hasta: str = ""
    since: datetime | None = None  # UTC, inclusive
    until: datetime | None = None  # UTC, exclusivo
    error: str | None = None

    @classmethod
    def parse(cls, desde: str = "", hasta: str = "") -> "EventFilter":
        f = cls(desde=(desde or "").strip(), hasta=(hasta or "").strip())
        zone = get_settings().zone
        try:
            f.since = parse_local_input(f.desde, zone)
            if f.hasta:
                f.until = parse_local_input(f.hasta, zone) + end_of_input_minute(f.hasta)
        except ValueError:
            f.since = f.until = None
            f.error = "Fecha inválida"
            return f
        if f.since and f.until and f.since >= f.until:
            f.error = "La fecha «Desde» debe ser anterior a «Hasta»"
        return f

    @property
    def active(self) -> bool:
        return bool(self.desde or self.hasta)


def _events(session: Session, vm_id: int, page: int = 1, filt: EventFilter | None = None) -> Page:
    query = select(Event).where(Event.vm_id == vm_id)
    if filt and filt.since:
        query = query.where(Event.at >= filt.since)
    if filt and filt.until:
        query = query.where(Event.at < filt.until)
    return paginate(session, query, page, EVENTS_PER_PAGE, col(Event.at).desc())


@router.get("/products/{product_id}/vms/new")
def new_vm(request: Request, product_id: int, session: Session = Depends(get_session)):
    product = get_or_404(session, Product, product_id)
    values = {"check_type": "icmp", "enabled": True}
    return render(request, "vm.html", product=product, vm=None, values=values, errors=[], events=[])


@router.post("/products/{product_id}/vms")
def create_vm(
    request: Request,
    product_id: int,
    name: str = Form(""),
    ip: str = Form(""),
    description: str = Form(""),
    check_type: str = Form("icmp"),
    port: str = Form(""),
    enabled: bool = Form(False),
    session: Session = Depends(get_session),
):
    product = get_or_404(session, Product, product_id)
    values = dict(name=name, ip=ip, description=description, check_type=check_type, port=port, enabled=enabled)
    errors, port_num = _validate(values)
    if errors:
        return render(request, "vm.html", 422, product=product, vm=None, values=values, errors=errors, events=[])
    vm = VM(
        product_id=product.id,
        name=clean(name),
        ip=ip.strip(),
        description=clean(description),
        check_type=check_type,
        port=port_num,
        enabled=enabled,
    )
    session.add(vm)
    session.commit()
    flash(request, f"VM «{vm.name}» registrada. Se chequeará en la próxima ronda.")
    return redirect(f"/products/{product.id}")


@router.get("/vms/{vm_id}")
def vm_detail(request: Request, vm_id: int, session: Session = Depends(get_session)):
    vm = get_or_404(session, VM, vm_id)
    values = dict(
        name=vm.name,
        ip=vm.ip,
        description=vm.description or "",
        check_type=vm.check_type,
        port=vm.port or "",
        enabled=vm.enabled,
    )
    return render(
        request,
        "vm.html",
        product=vm.product,
        vm=vm,
        values=values,
        errors=[],
        events=_events(session, vm.id),
        filt=EventFilter(),
    )


@router.get("/vms/{vm_id}/events")
def vm_events(
    request: Request,
    vm_id: int,
    page: int = 1,
    desde: str = "",
    hasta: str = "",
    session: Session = Depends(get_session),
):
    vm = get_or_404(session, VM, vm_id)
    filt = EventFilter.parse(desde, hasta)
    events = Page() if filt.error else _events(session, vm.id, page, filt)
    return render(request, "_vm_events.html", vm=vm, events=events, filt=filt, flash=None)


@router.post("/vms/{vm_id}")
def update_vm(
    request: Request,
    vm_id: int,
    name: str = Form(""),
    ip: str = Form(""),
    description: str = Form(""),
    check_type: str = Form("icmp"),
    port: str = Form(""),
    enabled: bool = Form(False),
    session: Session = Depends(get_session),
):
    vm = get_or_404(session, VM, vm_id)
    values = dict(name=name, ip=ip, description=description, check_type=check_type, port=port, enabled=enabled)
    errors, port_num = _validate(values)
    if errors:
        return render(
            request,
            "vm.html",
            422,
            product=vm.product,
            vm=vm,
            values=values,
            errors=errors,
            events=_events(session, vm.id),
            filt=EventFilter(),
        )

    target_changed = (vm.ip, vm.check_type, vm.port) != (ip.strip(), check_type, port_num)
    vm.name = clean(name)
    vm.ip = ip.strip()
    vm.description = clean(description)
    vm.check_type = check_type
    vm.port = port_num
    if not enabled:
        # Pausada: al reactivarla parte de cero, sin avisos por estados viejos
        vm.reset_state(keep_status=False)
    elif target_changed:
        # Mantiene el estado: si estaba caída y el nuevo destino responde, se avisa la recuperación
        vm.reset_state(keep_status=True)
    vm.enabled = enabled
    session.add(vm)
    session.commit()
    flash(request, "VM actualizada")
    return redirect(f"/vms/{vm.id}")


@router.post("/vms/{vm_id}/delete")
def delete_vm(request: Request, vm_id: int, session: Session = Depends(get_session)):
    vm = get_or_404(session, VM, vm_id)
    product_id = vm.product_id
    name = vm.name
    session.delete(vm)
    session.commit()
    flash(request, f"VM «{name}» eliminada")
    return redirect(f"/products/{product_id}")
