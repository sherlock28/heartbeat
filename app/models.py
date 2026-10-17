from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    """UTC naive: SQLite no guarda zona horaria."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


CASCADE = {"cascade": "all, delete-orphan"}


class Client(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)

    products: list["Product"] = Relationship(back_populates="client", sa_relationship_kwargs=CASCADE)
    channels: list["NotificationChannel"] = Relationship(back_populates="client", sa_relationship_kwargs=CASCADE)


class Product(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id", ondelete="CASCADE", index=True)
    name: str
    description: Optional[str] = None

    client: Client = Relationship(back_populates="products")
    vms: list["VM"] = Relationship(back_populates="product", sa_relationship_kwargs=CASCADE)


class VM(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", ondelete="CASCADE", index=True)
    name: str
    ip: str  # IP o hostname
    description: Optional[str] = None
    check_type: str = "icmp"  # "icmp" | "tcp"
    port: Optional[int] = None
    enabled: bool = True

    # Estado de runtime (lo mantiene el monitor)
    status: str = "unknown"  # "unknown" | "up" | "down"
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_check_at: Optional[datetime] = None
    last_change_at: Optional[datetime] = None
    last_latency_ms: Optional[float] = None
    last_error: Optional[str] = None

    product: Product = Relationship(back_populates="vms")
    events: list["Event"] = Relationship(back_populates="vm", sa_relationship_kwargs=CASCADE)

    @property
    def check_label(self) -> str:
        return f"TCP:{self.port}" if self.check_type == "tcp" else "Ping (ICMP)"

    def reset_state(self, keep_status: bool = True) -> None:
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.last_error = None
        if not keep_status:
            self.status = "unknown"
            self.last_latency_ms = None


class NotificationChannel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id", ondelete="CASCADE", index=True)
    type: str = "telegram"
    name: str
    # Configuración propia de cada integración (webhook_url, bot_token, chat_id…)
    config: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    enabled: bool = True

    client: Client = Relationship(back_populates="channels")


class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    vm_id: int = Field(foreign_key="vm.id", ondelete="CASCADE", index=True)
    kind: str  # "down" | "up"
    at: datetime = Field(default_factory=utcnow, index=True)
    detail: Optional[str] = None
    notified: bool = False

    vm: VM = Relationship(back_populates="events")
