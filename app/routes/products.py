from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, or_
from sqlmodel import Session, col, select

from app.auth import require_login
from app.db import get_session
from app.models import VM, Client, Product
from app.pagination import Page, paginate
from app.web import clean, flash, get_or_404, redirect, render

router = APIRouter(dependencies=[Depends(require_login)])

VMS_PER_PAGE = 10


def search_vms(session: Session, product_id: int, q: str = "", page: int = 1) -> Page:
    """VMs del producto cuyo nombre o IP contienen `q` (sin distinguir mayúsculas), paginadas."""
    q = (q or "").strip()
    query = select(VM).where(VM.product_id == product_id)
    if q:
        needle = q.lower()
        query = query.where(
            or_(
                func.lower(col(VM.name)).contains(needle, autoescape=True),
                func.lower(col(VM.ip)).contains(needle, autoescape=True),
            )
        )
    return paginate(session, query, page, VMS_PER_PAGE, func.lower(col(VM.name)), q=q)


def render_product(request: Request, session: Session, product: Product, values: dict, errors: list, status: int = 200):
    return render(
        request,
        "product.html",
        status,
        client=product.client,
        product=product,
        values=values,
        errors=errors,
        page=search_vms(session, product.id),
    )


@router.get("/clients/{client_id}/products/new")
def new_product(request: Request, client_id: int, session: Session = Depends(get_session)):
    client = get_or_404(session, Client, client_id)
    return render(request, "product.html", client=client, product=None, values={}, errors=[])


@router.post("/clients/{client_id}/products")
def create_product(
    request: Request,
    client_id: int,
    name: str = Form(""),
    description: str = Form(""),
    session: Session = Depends(get_session),
):
    client = get_or_404(session, Client, client_id)
    values = {"name": name, "description": description}
    if not clean(name):
        return render(
            request, "product.html", 422, client=client, product=None, values=values, errors=["El nombre es obligatorio"]
        )
    product = Product(client_id=client.id, name=clean(name), description=clean(description))
    session.add(product)
    session.commit()
    flash(request, f"Producto «{product.name}» creado. Ahora registra sus VMs.")
    return redirect(f"/products/{product.id}")


@router.get("/products/{product_id}")
def product_detail(request: Request, product_id: int, session: Session = Depends(get_session)):
    product = get_or_404(session, Product, product_id)
    values = {"name": product.name, "description": product.description or ""}
    return render_product(request, session, product, values, [])


@router.get("/products/{product_id}/vms")
def product_vms(request: Request, product_id: int, q: str = "", page: int = 1, session: Session = Depends(get_session)):
    product = get_or_404(session, Product, product_id)
    page_ = search_vms(session, product.id, q, page)
    return render(request, "_product_vms.html", product=product, page=page_, flash=None)


@router.post("/products/{product_id}")
def update_product(
    request: Request,
    product_id: int,
    name: str = Form(""),
    description: str = Form(""),
    session: Session = Depends(get_session),
):
    product = get_or_404(session, Product, product_id)
    values = {"name": name, "description": description}
    if not clean(name):
        return render_product(request, session, product, values, ["El nombre es obligatorio"], 422)
    product.name = clean(name)
    product.description = clean(description)
    session.add(product)
    session.commit()
    flash(request, "Producto actualizado")
    return redirect(f"/products/{product.id}")


@router.post("/products/{product_id}/delete")
def delete_product(request: Request, product_id: int, session: Session = Depends(get_session)):
    product = get_or_404(session, Product, product_id)
    client_id = product.client_id
    name = product.name
    session.delete(product)
    session.commit()
    flash(request, f"Producto «{name}» eliminado junto con sus VMs")
    return redirect(f"/clients/{client_id}")
