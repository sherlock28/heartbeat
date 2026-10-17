import re
from pathlib import Path
from typing import TypeVar

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlmodel import Session

from app.config import get_settings
from app.models import utcnow
from app.notifiers import REGISTRY
from app.utils import fmt_dt, human_duration


def highlight(text: str | None, q: str | None) -> Markup:
    """Escapa el texto y marca con <mark> las coincidencias (sin distinguir mayúsculas)."""
    safe = str(escape(text or ""))
    if q:
        pattern = re.compile(re.escape(str(escape(q))), re.IGNORECASE)
        safe = pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", safe)
    return Markup(safe)


templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.filters["dt"] = lambda d: fmt_dt(d, get_settings().zone)
templates.env.filters["since"] = lambda d: human_duration((utcnow() - d).total_seconds()) if d else "—"
templates.env.filters["highlight"] = highlight
templates.env.globals["notifier_types"] = {key: n.label for key, n in REGISTRY.items()}
templates.env.globals["notifiers"] = REGISTRY

T = TypeVar("T")


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session["flash"] = {"message": message, "kind": kind}


def render(request: Request, name: str, status_code: int = 200, **context):
    context.setdefault("flash", request.session.pop("flash", None))
    context.setdefault("user", request.session.get("user"))
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def get_or_404(session: Session, model: type[T], obj_id: int) -> T:
    obj = session.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="No encontrado")
    return obj


def clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None
