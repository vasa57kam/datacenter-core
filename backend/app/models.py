from app.core.tz import now as tz_now
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey,
    Index, Integer, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, INET
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
        CheckConstraint("role in ('client','admin','cashier','manager','master')", name="users_role_ck"),
        CheckConstraint("status in ('active','blocked')", name="users_status_ck"),
    )
    referral_code: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    referred_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    register_ip: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    auto_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)


class Wallet(Base):
    __tablename__ = "wallets"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), unique=True, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="RUB")
    balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    auto_approved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auto_approve_limit_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_approve_max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    promise_limit_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user = relationship("User")
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
    wallet = relationship("Wallet")
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
        CheckConstraint("unit in ('second','minute','hour','day','month','one_time','gb','mb')", name="products_unit_ck"),
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
    user = relationship("User")
    product = relationship("Product")
    accounts = relationship("VpnAccount", back_populates="service", cascade="all, delete-orphan")
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
        BigInteger, ForeignKey("service_instances.id", ondelete="CASCADE"), unique=True, nullable=False
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
    service = relationship("ServiceInstance", back_populates="accounts")
    __table_args__ = (
        CheckConstraint("status in ('pending','active','suspended','deleted')", name="account_status_ck"),
        UniqueConstraint("node_id", "ip_address", name="uq_account_node_ip"),
    )


class UsageSession(Base):
    __tablename__ = "usage_sessions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    service_instance_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("service_instances.id"), nullable=False)
    vpn_account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vpn_accounts.id", ondelete="CASCADE"), nullable=False)
    node_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vpn_nodes.id"), nullable=False)
    external_session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rx_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tx_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    charged_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    traffic_pending_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    account = relationship("VpnAccount")
    __table_args__ = (
        CheckConstraint("status in ('active','closed')", name="session_status_ck"),
        Index("ix_sessions_active", "status", "last_heartbeat_at"),
        # не более одной активной сессии на аккаунт — защита от двойного списания
        Index("uq_sessions_one_active_per_account", "vpn_account_id", unique=True,
              postgresql_where=text("status = 'active'")),
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


class PaymentRequest(Base):
    __tablename__ = "payment_requests"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user = relationship("User")
    __table_args__ = (
        CheckConstraint("status in ('pending','approved','rejected')", name="payreq_status_ck"),
        CheckConstraint("amount_minor > 0", name="payreq_amount_ck"),
        Index("ix_payreq_user", "user_id"),
    )

class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: tz_now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: tz_now(), onupdate=lambda: tz_now())

    messages: Mapped[list["TicketMessage"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan",
        order_by="TicketMessage.id",
    )


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("support_tickets.id", ondelete="CASCADE"), index=True)
    author_role: Mapped[str] = mapped_column(Text, nullable=False)  # client | manager
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: tz_now())

    ticket: Mapped["SupportTicket"] = relationship(back_populates="messages")


class Coupon(Base):
    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True, index=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="promo")  # promo | gift | coupon
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    max_activations: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    activations_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: tz_now())


class CouponActivation(Base):
    __tablename__ = "coupon_activations"

    id: Mapped[int] = mapped_column(primary_key=True)
    coupon_id: Mapped[int] = mapped_column(ForeignKey("coupons.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: tz_now())

    __table_args__ = (UniqueConstraint("coupon_id", "user_id", name="uq_coupon_user"),)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: tz_now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_email: Mapped[str] = mapped_column(Text, nullable=False, default="")
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: tz_now())


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    client_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")


class PatchHistory(Base):
    __tablename__ = "patch_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    actor_email: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: tz_now())
