import secrets

from fastapi import APIRouter, Form, Request

from app.config import get_settings
from app.web import redirect, render


class NotAuthenticated(Exception):
    pass


def require_login(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise NotAuthenticated()
    return user


router = APIRouter()


@router.get("/login")
def login_page(request: Request):
    if request.session.get("user"):
        return redirect("/")
    return render(request, "login.html", error=None)


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    settings = get_settings()
    valid_user = secrets.compare_digest(username.encode(), settings.admin_user.encode())
    valid_pass = secrets.compare_digest(password.encode(), settings.admin_password.encode())
    if not (valid_user and valid_pass):
        return render(request, "login.html", status_code=401, error="Usuario o contraseña incorrectos")
    request.session.clear()
    request.session["user"] = username
    return redirect("/")


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/login")
