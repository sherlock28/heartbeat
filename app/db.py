from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_engine: Engine | None = None


def _enable_sqlite_fk(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    # Sin WAL: su memoria compartida (-shm) no es fiable en volúmenes montados (Docker Desktop, red)
    cur.execute("PRAGMA journal_mode=DELETE")
    cur.close()


def make_engine(url: str, **kwargs) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False}, **kwargs)
    event.listen(engine, "connect", _enable_sqlite_fk)
    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        data_dir = Path(get_settings().data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        _engine = make_engine(f"sqlite:///{data_dir / 'monitor.db'}")
    return _engine


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}


def _migrate_channels_to_config(engine: Engine) -> None:
    """v1 → v2: notificationchannel.webhook_url pasa a config JSON {"webhook_url": ...}."""
    with engine.begin() as conn:
        cols = _columns(conn, "notificationchannel")
        if not cols or "config" in cols:
            return
        conn.exec_driver_sql("DROP INDEX IF EXISTS ix_notificationchannel_client_id")
        conn.exec_driver_sql("ALTER TABLE notificationchannel RENAME TO _notificationchannel_v1")
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO notificationchannel (id, client_id, type, name, config, enabled) "
            "SELECT id, client_id, type, name, json_object('webhook_url', webhook_url), enabled "
            "FROM _notificationchannel_v1"
        )
        conn.exec_driver_sql("DROP TABLE _notificationchannel_v1")


def init_db(engine: Engine) -> None:
    import app.models  # noqa: F401  registra las tablas

    _migrate_channels_to_config(engine)
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(get_engine()) as session:
        yield session
