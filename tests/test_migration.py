import sqlite3

from sqlmodel import Session, select

from app.db import init_db, make_engine
from app.models import NotificationChannel


def test_v1_channels_migrate_to_config(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE client (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, description VARCHAR, created_at DATETIME NOT NULL);
        CREATE TABLE notificationchannel (
            id INTEGER NOT NULL, client_id INTEGER NOT NULL, type VARCHAR NOT NULL, name VARCHAR NOT NULL,
            webhook_url VARCHAR NOT NULL, enabled BOOLEAN NOT NULL, PRIMARY KEY (id),
            FOREIGN KEY(client_id) REFERENCES client (id) ON DELETE CASCADE);
        CREATE INDEX ix_notificationchannel_client_id ON notificationchannel (client_id);
        INSERT INTO client VALUES (1, 'ACME', NULL, '2026-10-16 00:00:00');
        INSERT INTO notificationchannel VALUES (5, 1, 'google_chat', 'Soporte', 'https://chat.googleapis.com/x', 1);
        """
    )
    conn.close()

    engine = make_engine(f"sqlite:///{db}")
    init_db(engine)
    init_db(engine)  # idempotente

    with Session(engine) as s:
        ch = s.exec(select(NotificationChannel)).one()
        assert (ch.id, ch.client_id, ch.type, ch.name, ch.enabled) == (5, 1, "google_chat", "Soporte", True)
        assert ch.config == {"webhook_url": "https://chat.googleapis.com/x"}
