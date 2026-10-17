from fastapi import APIRouter, Depends, Request
from sqlalchemy import case, func
from sqlalchemy.orm import selectinload
from sqlmodel import Session, col, select

from app.auth import require_login
from app.db import get_session
from app.models import VM, Client, Product
from app.pagination import Page, paginate
from app.web import get_or_404, render

router = APIRouter(dependencies=[Depends(require_login)])

DASHBOARD_VMS_PER_PAGE = 5

# En el dashboard las caídas van primero para que nunca queden escondidas en otra página
STATUS_ORDER = case(
    (col(VM.enabled).is_(False), 3),
    (col(VM.status) == "down", 0),
    (col(VM.status) == "unknown", 1),
    else_=2,
)


def dashboard_vms(session: Session, product_id: int, page: int = 1) -> Page:
    query = select(VM).where(VM.product_id == product_id)
    return paginate(session, query, page, DASHBOARD_VMS_PER_PAGE, [STATUS_ORDER, func.lower(col(VM.name))])


def client_vms(session: Session, client_id: int) -> list[VM]:
    return list(session.exec(select(VM).join(Product).where(Product.client_id == client_id)).all())


def _stats(session: Session) -> dict:
    vms = session.exec(select(VM)).all()
    return {
        "up": sum(1 for v in vms if v.enabled and v.status == "up"),
        "down": sum(1 for v in vms if v.enabled and v.status == "down"),
        "unknown": sum(1 for v in vms if v.enabled and v.status == "unknown"),
        "paused": sum(1 for v in vms if not v.enabled),
    }


@router.get("/")
def dashboard(request: Request, session: Session = Depends(get_session)):
    clients = session.exec(
        select(Client)
        .options(selectinload(Client.products).selectinload(Product.vms), selectinload(Client.channels))
        .order_by(Client.name)
    ).all()
    vm_pages = {p.id: dashboard_vms(session, p.id) for c in clients for p in c.products}
    client_vms_map = {c.id: [vm for p in c.products for vm in p.vms] for c in clients}
    return render(
        request,
        "dashboard.html",
        clients=clients,
        stats=_stats(session),
        vm_pages=vm_pages,
        client_vms_map=client_vms_map,
    )


@router.get("/partials/stats")
def stats_partial(request: Request, session: Session = Depends(get_session)):
    return render(request, "_stats.html", flash=None, stats=_stats(session))


@router.get("/partials/products/{product_id}/vms")
def product_vms_partial(request: Request, product_id: int, page: int = 1, session: Session = Depends(get_session)):
    product = get_or_404(session, Product, product_id)
    return render(request, "_dash_vms.html", flash=None, product=product, vms=dashboard_vms(session, product.id, page))


@router.get("/partials/clients/{client_id}/status")
def client_status_partial(request: Request, client_id: int, session: Session = Depends(get_session)):
    client = get_or_404(session, Client, client_id)
    return render(request, "_client_status.html", flash=None, client=client, vms=client_vms(session, client.id))
