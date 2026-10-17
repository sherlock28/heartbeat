from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.auth import require_login
from app.db import get_session
from app.models import Client, NotificationChannel, Product
from app.pagination import Page, paginate
from app.web import clean, flash, get_or_404, redirect, render

router = APIRouter(dependencies=[Depends(require_login)])

PRODUCTS_PER_PAGE = 5
CHANNELS_PER_PAGE = 5


def products_page(session: Session, client_id: int, page: int = 1) -> Page:
    query = select(Product).where(Product.client_id == client_id)
    return paginate(session, query, page, PRODUCTS_PER_PAGE, func.lower(col(Product.name)))


def channels_page(session: Session, client_id: int, page: int = 1) -> Page:
    query = select(NotificationChannel).where(NotificationChannel.client_id == client_id)
    return paginate(session, query, page, CHANNELS_PER_PAGE, func.lower(col(NotificationChannel.name)))


def render_client(request: Request, session: Session, client: Client, values: dict, errors: list, status: int = 200):
    return render(
        request,
        "client.html",
        status,
        client=client,
        values=values,
        errors=errors,
        products=products_page(session, client.id),
        channels=channels_page(session, client.id),
    )


@router.get("/clients/new")
def new_client(request: Request):
    return render(request, "client.html", client=None, values={}, errors=[])


@router.post("/clients")
def create_client(
    request: Request,
    name: str = Form(""),
    description: str = Form(""),
    session: Session = Depends(get_session),
):
    values = {"name": name, "description": description}
    if not clean(name):
        return render(request, "client.html", 422, client=None, values=values, errors=["El nombre es obligatorio"])
    client = Client(name=clean(name), description=clean(description))
    session.add(client)
    session.commit()
    flash(request, f"Cliente «{client.name}» creado. Agrega productos y un canal de notificación.")
    return redirect(f"/clients/{client.id}")


@router.get("/clients/{client_id}")
def client_detail(request: Request, client_id: int, session: Session = Depends(get_session)):
    client = get_or_404(session, Client, client_id)
    values = {"name": client.name, "description": client.description or ""}
    return render_client(request, session, client, values, [])


@router.get("/clients/{client_id}/products/list")
def client_products(request: Request, client_id: int, page: int = 1, session: Session = Depends(get_session)):
    client = get_or_404(session, Client, client_id)
    return render(request, "_client_products.html", client=client, products=products_page(session, client.id, page), flash=None)


@router.get("/clients/{client_id}/channels/list")
def client_channels(request: Request, client_id: int, page: int = 1, session: Session = Depends(get_session)):
    client = get_or_404(session, Client, client_id)
    return render(request, "_client_channels.html", client=client, channels=channels_page(session, client.id, page), flash=None)


@router.post("/clients/{client_id}")
def update_client(
    request: Request,
    client_id: int,
    name: str = Form(""),
    description: str = Form(""),
    session: Session = Depends(get_session),
):
    client = get_or_404(session, Client, client_id)
    values = {"name": name, "description": description}
    if not clean(name):
        return render_client(request, session, client, values, ["El nombre es obligatorio"], 422)
    client.name = clean(name)
    client.description = clean(description)
    session.add(client)
    session.commit()
    flash(request, "Cliente actualizado")
    return redirect(f"/clients/{client.id}")


@router.post("/clients/{client_id}/delete")
def delete_client(request: Request, client_id: int, session: Session = Depends(get_session)):
    client = get_or_404(session, Client, client_id)
    name = client.name
    session.delete(client)
    session.commit()
    flash(request, f"Cliente «{name}» eliminado junto con sus productos, VMs y canales")
    return redirect("/")
