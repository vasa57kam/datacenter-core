from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey,
    Index, Integer, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, INET
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="client")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("role in ('client','admin','manager','master')", name="users_role_ck"),
        CheckConstraint("status in ('active','blocked')", name="users_status_ck"),
    )


class Wallet(Base):
    __tablename__ = "wallets"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), unique=True, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="RUB")
    balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (CheckConstraint("balance_minor >= 0", name="wallets_balance_non_negative"),)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    wallet_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("wallets.id"), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_type: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("entry_type in ('credit','debit')", name="ledger_entry_type_ck"),
        Index("ix_ledger_wallet_created", "wallet_id", "created_at"),
    )


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    service_type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="RUB")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    __table_args__ = (
        CheckConstraint("service_type in ('vpn','vps','cctv','hosting','storage','mail')", name="products_type_ck"),
        CheckConstraint("unit in ('minute','month','one_time')", name="products_unit_ck"),
        CheckConstraint("price_minor >= 0", name="products_price_ck"),
    )


class ServiceInstance(Base):
    __tablename__ = "service_instances"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        CheckConstraint(
            "status in ('pending','provisioning','active','suspended','terminated')",
            name="service_status_ck",
        ),
        Index("ix_services_user_status", "user_id", "status"),
    )


class VpnNode(Base):
    __tablename__ = "vpn_nodes"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    protocol: Mapped[str] = mapped_column(Text, nullable=False)
    api_kind: Mapped[str] = mapped_column(Text, nullable=False)
    api_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_user: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_host: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_port: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    ssh_user: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    subnet_cidr: Mapped[str | None] = mapped_column(Text, nullable=True)
    endpoint_host: Mapped[str | None] = mapped_column(Text, nullable=True)
    endpoint_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    __table_args__ = (
        CheckConstraint("protocol in ('vless','wireguard','openvpn')", name="node_protocol_ck"),
        CheckConstraint(
            "api_kind in ('3xui','marzban','ssh_wireguard','openvpn_api','manual')",
            name="node_api_kind_ck",
        ),
    )


class VpnAccount(Base):
    __tablename__ = "vpn_accounts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    service_instance_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_instances.id"), unique=True, nullable=False
    )
    node_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vpn_nodes.id"), nullable=False)
    protocol: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    uuid: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("status in ('pending','active','suspended','deleted')", name="account_status_ck"),
        UniqueConstraint("node_id", "ip_address", name="uq_account_node_ip"),
    )


class UsageSession(Base):
    __tablename__ = "usage_sessions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    service_instance_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("service_instances.id"), nullable=False)
    vpn_account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vpn_accounts.id"), nullable=False)
    node_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vpn_nodes.id"), nullable=False)
    external_session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rx_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tx_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    charged_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    __table_args__ = (
        CheckConstraint("status in ('active','closed')", name="session_status_ck"),
        Index("ix_sessions_active", "status", "last_heartbeat_at"),
    )


class ProvisioningTask(Base):
    __tablename__ = "provisioning_tasks"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        CheckConstraint("action in ('create','suspend','resume','delete')", name="task_action_ck"),
        CheckConstraint("status in ('pending','running','done','error')", name="task_status_ck"),
    )

class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_identity_provider_ext"),
        Index("ix_identity_user", "user_id"),
    )
