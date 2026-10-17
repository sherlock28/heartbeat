# 💓 Heartbeat

[English](README.md) · **Español**

Monitoreo liviano de disponibilidad de VMs organizado en **Cliente → Producto → VM**, con alertas por **Telegram** y **Google Chat** que se envían **solo cuando una máquina se cae y cuando se recupera**, sin avisos periódicos que molesten.

Hecho con FastAPI, SQLite y HTMX, y empaquetado en **un único contenedor Docker**.

---

## Contenido

- [Características](#características)
- [Cómo funciona](#cómo-funciona)
- [Puesta en marcha](#puesta-en-marcha)
- [Configuración](#configuración)
- [Uso del panel](#uso-del-panel)
- [Canales de notificación](#canales-de-notificación)
- [¿Cuándo avisa?](#cuándo-avisa)
- [Red](#red)
- [Uso en producción](#uso-en-producción)
- [Backup, restauración y actualización](#backup-restauración-y-actualización)
- [Health check](#health-check)
- [Solución de problemas](#solución-de-problemas)
- [Desarrollo](#desarrollo)
- [Agregar una integración](#agregar-una-integración)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Próximos pasos](#próximos-pasos)
- [Licencia](#licencia)

---

## Características

- **Jerarquía Cliente → Producto → VM.** Cada cliente tiene sus propios canales de aviso.
- **Dos tipos de chequeo por VM:**
  - **Ping (ICMP)**, para máquinas que responden a ping.
  - **Puerto TCP**, para máquinas cuyo firewall bloquea ICMP (habitual en Windows y en la nube). Además confirma que el servicio está escuchando (22 SSH, 3389 RDP, 443 HTTPS, 5432 PostgreSQL…).
- **Alertas solo en los cambios de estado:** un mensaje cuando la VM se cae y otro cuando se recupera, con la duración de la caída.
- **Umbrales configurables.** Por defecto una VM se considera caída tras 3 fallos seguidos, con chequeos cada 30 s (≈ 90 s).
- **Integraciones:**
  - **Telegram**, con detección automática del chat: no hace falta buscar el Chat ID a mano.
  - **Google Chat**, mediante webhooks. La caída y la recuperación de una VM se agrupan en el mismo hilo.
- **Panel web** con login:
  - **Dashboard en vivo:**
    - contadores de VMs activas, caídas, pendientes y pausadas;
    - clientes y productos colapsables que recuerdan su estado;
    - VMs ordenadas con las caídas primero.
  - **Tablas en vivo:** se actualizan cada 10 s sin recargar la página.
  - **Buscador:** búsqueda en vivo de VMs por nombre o IP, que resalta las coincidencias.
  - **Paginación:** en todas las tablas (VMs, productos, canales y eventos).
  - **Historial de eventos por VM:**
    - filtro por rango de fechas (*desde*, *hasta* o ambos);
    - indica si cada evento fue notificado.
  - **Mensajes de prueba:** botón "Enviar prueba" en cada canal.
- **Estado persistente:** reiniciar el contenedor no reenvía alertas.
- **Reintentos:** cada notificación se reintenta hasta 3 veces.
- **Integraciones enchufables:** sumar Slack, Teams, etc. es escribir una sola clase.

## Cómo funciona

```
                 ┌──────────────────────── Contenedor Docker ───────────────────────┐
                 │                                                                   │
  Navegador ────▶│  FastAPI + Jinja + HTMX (panel, login)                            │
                 │        │                                                          │
                 │        ▼                                                          │
                 │  SQLite (/data/monitor.db) ◀──── Monitor (bucle async, c/30 s)    │
                 │                                     │  ping / conexión TCP        │
                 └─────────────────────────────────────┼─────────────────────────────┘
                                                       ▼
                                         VMs ──▶ ¿cambió el estado? ──▶ Telegram / Google Chat
```

El monitor corre **dentro del proceso web**. Por eso la app usa **un solo worker de uvicorn**: con más workers se duplicarían los chequeos y las alertas.

## Puesta en marcha

Requisitos: **Docker** con **Docker Compose**.

```bash
git clone <url-de-tu-repo> heartbeat
cd heartbeat
cp .env.example .env
```

Editá `.env` y definí al menos estos dos valores:

```ini
ADMIN_PASSWORD=una-contraseña-segura
SECRET_KEY=<salida de: python -c "import secrets; print(secrets.token_urlsafe(32))">
```

Levantalo:

```bash
docker compose up -d --build
```

Entrá a **http://localhost:8000** con `ADMIN_USER` / `ADMIN_PASSWORD`. Los datos quedan en `./data/monitor.db`.

Comandos útiles:

```bash
docker compose logs -f        # ver logs
docker compose restart        # reiniciar
docker compose down           # detener (los datos en ./data se conservan)
```

## Configuración

Toda la configuración se toma de variables de entorno, cargadas desde `.env`.

| Variable | Defecto | Descripción |
|---|---|---|
| `ADMIN_USER` | `admin` | Usuario del panel |
| `ADMIN_PASSWORD` | `admin` | Contraseña del panel. **Cambiala**: mientras sea la de defecto se registra un aviso en el log |
| `SECRET_KEY` | aleatoria | Firma la cookie de sesión. Si no se define, se genera una temporal y las sesiones se pierden en cada reinicio |
| `CHECK_INTERVAL` | `30` | Segundos entre rondas de chequeo |
| `CHECK_TIMEOUT` | `2` | Segundos de espera de cada chequeo |
| `FAIL_THRESHOLD` | `3` | Fallos seguidos para declarar una VM **caída** |
| `RECOVER_THRESHOLD` | `1` | Éxitos seguidos para declararla **recuperada** |
| `NOTIFY_INITIAL_DOWN` | `true` | Avisar si una VM ya está caída al registrarla |
| `MAX_CONCURRENT_CHECKS` | `100` | Máximo de chequeos en paralelo |
| `ICMP_PRIVILEGED` | `true` | Usar sockets ICMP crudos. En Docker (root) dejalo en `true`; si corrés como usuario sin root en Linux, usá `false` |
| `DATA_DIR` | `/data` (Docker) · `./data` (local) | Carpeta de la base SQLite |
| `TZ` | `America/Argentina/Buenos_Aires` | Zona horaria del panel y de los mensajes |

Después de cambiar `.env`, corré `docker compose up -d` para aplicarlo.

## Uso del panel

1. **+ Cliente**: creá el cliente, por ejemplo "ACME Corp".
2. Dentro del cliente, **+ Canal**: elegí Telegram o Google Chat (ver [Canales de notificación](#canales-de-notificación)), guardá y tocá **Enviar prueba**.
3. **+ Producto**, por ejemplo "Portal de clientes".
4. Dentro del producto, **+ VM**: cargá el nombre, la IP o el hostname, una descripción opcional y el tipo de chequeo:
   - **Ping (ICMP)**: lo más simple.
   - **Puerto TCP**: elegí un puerto que la VM siempre tenga abierto.

El **dashboard** muestra cada cliente con sus productos y VMs:

- podés colapsar cada cliente o producto, y el panel lo recuerda;
- una sección colapsada sigue mostrando el conteo de estados en vivo;
- las VMs caídas siempre aparecen primero.

La **página de cada VM** muestra:

- su estado actual, la latencia, el último chequeo y el último cambio;
- el historial de eventos, con filtro por rango de fechas para investigar incidencias.

> La **latencia** es el valor del último chequeo exitoso: un paquete de ping o el tiempo en abrir la conexión TCP. Se actualiza cada `CHECK_INTERVAL` segundos y muestra "—" si el último chequeo falló.

## Canales de notificación

### Telegram

1. En Telegram hablá con **@BotFather**, enviá `/newbot` y copiá el **token**.
2. Abrí el chat con tu bot y enviale `/start`. Si es un grupo, agregá el bot y escribí cualquier mensaje.
3. En Heartbeat pegá el token y tocá **🔍 Detectar**: elegís el chat y el Chat ID se completa solo.

### Google Chat

1. Abrí el espacio donde querés recibir los avisos.
2. Andá a **Apps e integraciones → Webhooks → Agregar webhook** y copiá la URL.
3. Pegala en Heartbeat.

La caída y la recuperación de una misma VM se agrupan en el mismo hilo.

## ¿Cuándo avisa?

| Situación | ¿Avisa? |
|---|---|
| VM nueva, o reinicio del servicio, y la VM responde | No (estado inicial) |
| VM nueva que ya está caída | Sí, si `NOTIFY_INITIAL_DOWN=true` |
| `FAIL_THRESHOLD` fallos seguidos | 🔴 Sí, una vez |
| Sigue caída | No |
| Vuelve a responder | 🟢 Sí, una vez, con la duración de la caída |
| Fallos sueltos por debajo del umbral | No |
| VM pausada | No se chequea |

El estado se guarda en la base, así que reiniciar el contenedor no reenvía alertas. Si una notificación falla se reintenta 3 veces, y el resultado queda en el historial de la VM (columna *Notificado*).

## Red

El contenedor tiene que poder alcanzar las IPs de las VMs.

- **Redes ruteables** (LAN, IPs públicas): funciona la configuración por defecto, con `ports: "8000:8000"`.
- **VMs alcanzables solo desde el host** (VPN, rutas propias): en `docker-compose.yml` quitá `ports` y descomentá `network_mode: host`. En Linux el contenedor pasa a usar directamente la red del host.

## Uso en producción

- **Credenciales:** definí una `ADMIN_PASSWORD` fuerte y una `SECRET_KEY` fija.
- **HTTPS:** poné el panel detrás de un reverse proxy (Nginx, Caddy, Traefik) en lugar de exponer el puerto 8000 directamente. La app ya confía en los headers `X-Forwarded-*` (`--proxy-headers`).
- **Acceso restringido:** si podés, limitá el panel a tu red o VPN.
- **Datos sensibles:** la base contiene tokens de bots y URLs de webhooks. Protegé `./data` y nunca la subas a git, ni tampoco `.env` (los dos ya están en `.gitignore`).

## Backup, restauración y actualización

**Backup:** todo vive en `data/monitor.db`.

```bash
docker compose stop
cp data/monitor.db backups/monitor-$(date +%F).db
docker compose start
```

**Restaurar:** detené el contenedor, reemplazá `data/monitor.db` por el backup y volvé a levantarlo.

**Actualizar:**

```bash
git pull
docker compose up -d --build
```

Las migraciones de esquema corren solas al iniciar. Aun así, hacé un backup de la base antes de actualizar.

## Health check

`GET /health` (no requiere login) devuelve:

```json
{ "status": "ok", "monitor_running": true, "last_run_at": "2026-10-17T05:00:00Z" }
```

Docker lo usa como `HEALTHCHECK` del contenedor, y también podés apuntarle un monitor externo.

## Solución de problemas

| Problema | Causa probable / solución |
|---|---|
| Una VM figura **caída** pero está andando | El firewall bloquea ICMP: cambiala a chequeo por **puerto TCP** |
| Todas las VMs figuran caídas | El contenedor no llega a esa red: ver [Red](#red) |
| Un celular o una notebook alterna entre activo y caído | Es normal: los dispositivos "duermen" el WiFi cuando están inactivos |
| **Detectar** de Telegram no encuentra chats | Primero enviale `/start` al bot (o escribí en el grupo) y volvé a probar |
| Se cierra la sesión en cada reinicio | Falta definir `SECRET_KEY` en `.env` |
| No llegó una notificación | Revisá la columna *Notificado* del historial de la VM y después `docker compose logs` |

## Desarrollo

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt pytest     # Linux/macOS: .venv/bin/pip
.venv/Scripts/python -m pytest -q                        # correr los tests
.venv/Scripts/uvicorn app.main:app --reload              # servidor de desarrollo en :8000
```

Fuera de Docker, el ping ICMP puede requerir privilegios. En Linux sin root, usá `ICMP_PRIVILEGED=false`.

**Stack:** FastAPI · SQLModel/SQLite · Jinja2 · HTMX · Pico CSS · icmplib · httpx.

## Agregar una integración

Creá una clase en `app/notifiers/` que herede de `Notifier`:

```python
from app.notifiers.base import ConfigField, Notifier, register, event_rows

class SlackNotifier(Notifier):
    type = "slack"
    label = "Slack"
    fields = [ConfigField("webhook_url", "URL del webhook", placeholder="https://hooks.slack.com/…", secret=True)]
    help_html = "<ol><li>Creá un Incoming Webhook en Slack…</li></ol>"

    async def send(self, config: dict, event) -> None:
        ...  # armá el mensaje con event_rows(event) y envialo

register(SlackNotifier())
```

Después importá el módulo nuevo en `app/notifiers/__init__.py`. El formulario de canales toma solo los campos y la ayuda:

- los campos con `secret=True` se muestran como contraseña;
- `validate(config)` permite agregar validaciones extra;
- la configuración de cada canal se guarda como JSON en `notificationchannel.config`.

## Estructura del proyecto

```
app/
├── main.py            # app FastAPI, lifespan (arranca el monitor), /health
├── config.py          # configuración desde el entorno / .env
├── db.py              # motor SQLite y migraciones
├── models.py          # Client, Product, VM, NotificationChannel, Event
├── monitor/
│   ├── checks.py      # chequeos ICMP y TCP
│   └── engine.py      # máquina de estados (transiciones up/down) y bucle
├── notifiers/         # clase base Notifier, Telegram, Google Chat
├── routes/            # dashboard, clientes, productos, VMs, canales
├── pagination.py      # helper de paginación compartido
└── templates/         # vistas y parciales Jinja + HTMX
tests/                 # tests con pytest
```

## Próximos pasos

- [ ] **Servicios** dentro de cada VM: chequeos HTTP o TCP por servicio, con el mismo motor y las mismas integraciones.
- [ ] Más integraciones (Slack, Microsoft Teams, e-mail).
- [ ] Historial y gráficos de latencia por VM.

## Licencia

Publicado bajo la [licencia MIT](LICENSE).
