import math
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select


@dataclass
class Page:
    items: list[Any] = field(default_factory=list)
    page: int = 1
    pages: int = 1
    total: int = 0
    per_page: int = 10
    q: str = ""

    @property
    def start(self) -> int:
        return (self.page - 1) * self.per_page + 1 if self.total else 0

    @property
    def end(self) -> int:
        return self.start + len(self.items) - 1 if self.total else 0


def paginate(session: Session, query, page: int, per_page: int, order_by, q: str = "") -> Page:
    """Ejecuta `query` paginada; una página fuera de rango se ajusta a la primera/última.

    `order_by` es una expresión o una lista de expresiones.
    """
    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    pages = max(1, math.ceil(total / per_page))
    page = min(max(1, page), pages)
    order = order_by if isinstance(order_by, (list, tuple)) else [order_by]
    items = session.exec(query.order_by(*order).offset((page - 1) * per_page).limit(per_page)).all()
    return Page(items=list(items), page=page, pages=pages, total=total, per_page=per_page, q=q)
