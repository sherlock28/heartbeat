import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from app import auth
from app.config import get_settings
from app.db import get_engine, init_db
from app.monitor.engine import Monitor
from app.routes import channels, clients, dashboard, products, vms

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx registra cada URL en INFO, y la URL de Telegram incluye el token del bot
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = get_engine()
    init_db(engine)
    monitor = Monitor(engine, settings)
    monitor.start()
    app.state.monitor = monitor
    yield
    await monitor.stop()


settings = get_settings()
app = FastAPI(title="Heartbeat", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax", max_age=7 * 24 * 3600)


@app.exception_handler(auth.NotAuthenticated)
async def not_authenticated(request: Request, _exc: auth.NotAuthenticated):
    if request.headers.get("HX-Request"):
        return Response(status_code=401, headers={"HX-Redirect": "/login"})
    return RedirectResponse("/login", status_code=303)


@app.get("/health")
def health(request: Request):
    monitor: Monitor | None = getattr(request.app.state, "monitor", None)
    running = bool(monitor and monitor.running)
    body = {"status": "ok" if running else "degraded", "monitor_running": running}
    if monitor and monitor.last_run_at:
        body["last_run_at"] = monitor.last_run_at.isoformat() + "Z"
    return body


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(clients.router)
app.include_router(products.router)
app.include_router(vms.router)
app.include_router(channels.router)
