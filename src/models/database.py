"""
SQLAlchemy ORM models for the Banking AI Transfer Agent demo.

All monetary values are stored as integers (KRW, no decimals).
"""

from datetime import datetime, date
from typing import Optional

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

db = SQLAlchemy()


# ─────────────────────────────────────────────────────────────────────────────
# Users & Accounts
# ─────────────────────────────────────────────────────────────────────────────


class User(db.Model):
    """Demo banking customer."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100), nullable=False)
    phone = Column(String(20))
    email = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    accounts = relationship("Account", back_populates="user", lazy="select")
    favorites = relationship("Favorite", back_populates="user", lazy="select")
    recurring_transfers = relationship("RecurringTransfer", back_populates="user", lazy="select")
    transfer_history = relationship("TransferHistory", back_populates="user", lazy="select")
    transfer_limits = relationship("TransferLimit", back_populates="user", lazy="select")
    chat_sessions = relationship("ChatSession", back_populates="user", lazy="select")

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.display_name})>"


class Account(db.Model):
    """Bank account belonging to a user."""

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_number = Column(String(50), unique=True, nullable=False)
    account_name = Column(String(100), nullable=False)
    bank_name = Column(String(50), nullable=False)
    account_type = Column(String(50), default="입출금")  # 입출금 / 저축 / 적금
    balance = Column(BigInteger, default=0)  # KRW integer
    is_active = Column(Boolean, default=True)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="accounts")

    def __repr__(self) -> str:
        return f"<Account {self.account_number} ({self.account_name})>"


# ─────────────────────────────────────────────────────────────────────────────
# Recipients & Favorites
# ─────────────────────────────────────────────────────────────────────────────


class Recipient(db.Model):
    """External transfer destination (bank + account number)."""

    __tablename__ = "recipients"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    bank_name = Column(String(50), nullable=False)
    account_number = Column(String(50), nullable=False)
    is_verified = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Recipient {self.name} @ {self.bank_name}>"


class Favorite(db.Model):
    """
    Saved recipient entry for a user.

    An alias (e.g. '엄마', '아빠') is stored here.  The same Recipient can be
    a favorite for multiple users under different aliases.
    """

    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recipient_id = Column(Integer, ForeignKey("recipients.id"), nullable=False)
    alias = Column(String(100))  # User-defined nickname: "엄마", "민수", …
    send_count = Column(Integer, default=0)
    last_sent_at = Column(DateTime)
    is_favorite = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="favorites")
    recipient = relationship("Recipient")

    def __repr__(self) -> str:
        return f"<Favorite alias='{self.alias}' recipient={self.recipient_id}>"


# ─────────────────────────────────────────────────────────────────────────────
# Recurring Transfers
# ─────────────────────────────────────────────────────────────────────────────


class RecurringTransfer(db.Model):
    """Template for a scheduled recurring transfer (monthly rent, allowance, …)."""

    __tablename__ = "recurring_transfers"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    favorite_id = Column(Integer, ForeignKey("favorites.id"), nullable=True)
    alias = Column(String(100), nullable=False)  # e.g. "월세", "관리비"
    default_amount = Column(BigInteger, nullable=False)
    recurrence_type = Column(String(20), default="monthly")  # monthly / weekly
    day_of_month = Column(Integer)  # 1–31
    next_due_date = Column(Date)
    is_active = Column(Boolean, default=True)
    memo = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="recurring_transfers")
    favorite = relationship("Favorite")

    def __repr__(self) -> str:
        return f"<RecurringTransfer '{self.alias}' {self.default_amount}원>"


# ─────────────────────────────────────────────────────────────────────────────
# Transfer History & Ledger
# ─────────────────────────────────────────────────────────────────────────────


class TransferHistory(db.Model):
    """Record of each completed (or failed) transfer."""

    __tablename__ = "transfer_history"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    source_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    recipient_id = Column(Integer, ForeignKey("recipients.id"), nullable=False)
    favorite_id = Column(Integer, ForeignKey("favorites.id"), nullable=True)
    amount = Column(BigInteger, nullable=False)
    fee = Column(BigInteger, default=0)
    memo = Column(String(200))
    status = Column(String(20), default="completed")  # completed / failed / cancelled
    transferred_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="transfer_history")
    source_account = relationship("Account")
    recipient = relationship("Recipient")
    favorite = relationship("Favorite")

    def __repr__(self) -> str:
        return f"<TransferHistory id={self.id} amount={self.amount} status={self.status}>"


# ─────────────────────────────────────────────────────────────────────────────
# Limits
# ─────────────────────────────────────────────────────────────────────────────


class TransferLimit(db.Model):
    """Per-user transfer limit tracking.  Daily used resets each calendar day."""

    __tablename__ = "transfer_limits"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    single_transfer_limit = Column(BigInteger, default=10_000_000)  # 1천만원
    daily_limit = Column(BigInteger, default=30_000_000)  # 3천만원
    daily_used = Column(BigInteger, default=0)
    last_reset_date = Column(Date, default=date.today)

    user = relationship("User", back_populates="transfer_limits")

    def get_daily_remaining(self) -> int:
        self._maybe_reset_daily()
        return max(0, self.daily_limit - self.daily_used)

    def _maybe_reset_daily(self) -> None:
        today = date.today()
        if self.last_reset_date != today:
            self.daily_used = 0
            self.last_reset_date = today

    def __repr__(self) -> str:
        return f"<TransferLimit user={self.user_id} daily_used={self.daily_used}>"


# ─────────────────────────────────────────────────────────────────────────────
# Chat Sessions & Messages
# ─────────────────────────────────────────────────────────────────────────────


class ChatSession(db.Model):
    """Persistent multi-turn conversation session for the transfer agent."""

    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id = Column(String(100), unique=True, nullable=False)
    state_json = Column(Text)  # JSON-serialised agent state (between turns)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", lazy="select")

    def __repr__(self) -> str:
        return f"<ChatSession {self.session_id}>"


class ChatMessage(db.Model):
    """Single message within a chat session."""

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)  # user / assistant
    content = Column(Text, nullable=False)
    intent = Column(String(50))  # classified intent for debug display
    slots_json = Column(Text)  # JSON of extracted slots
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("ChatSession", back_populates="messages")

    def __repr__(self) -> str:
        return f"<ChatMessage role={self.role} len={len(self.content)}>"


# ─────────────────────────────────────────────────────────────────────────────
# Audit Log
# ─────────────────────────────────────────────────────────────────────────────


class AuditLog(db.Model):
    """Immutable audit trail for transfer-related actions."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)  # e.g. "transfer_executed"
    entity_type = Column(String(50))  # e.g. "transfer_history"
    entity_id = Column(Integer)
    details_json = Column(Text)  # JSON blob with full context
    ip_address = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<AuditLog action={self.action} entity={self.entity_type}/{self.entity_id}>"


# ─────────────────────────────────────────────────────────────────────────────
# Agent Run Log
# ─────────────────────────────────────────────────────────────────────────────


class AgentRunLog(db.Model):
    """One record per LangGraph invocation — stores per-node execution details."""

    __tablename__ = "agent_run_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    session_id = Column(String(100), nullable=True)
    user_message = Column(Text, nullable=False)
    intent = Column(String(50))
    response_type = Column(String(50))
    response_text = Column(Text)
    pending_state = Column(String(50))
    graph_trace = Column(Text)          # comma-separated node names
    node_logs_json = Column(Text)       # JSON array — one entry per node execution
    total_duration_ms = Column(Integer)
    langsmith_url = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<AgentRunLog id={self.id} intent={self.intent}>"


# ─────────────────────────────────────────────────────────────────────────────
# Initialisation helper
# ─────────────────────────────────────────────────────────────────────────────


def init_db(app) -> None:
    """Attach SQLAlchemy to the Flask *app* and create all tables."""
    db.init_app(app)
    with app.app_context():
        db.create_all()
