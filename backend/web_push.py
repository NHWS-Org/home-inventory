"""Session-bound subscriptions and a separately committed external delivery outbox."""

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import ipaddress
import json
import logging
import re
import socket
from urllib.parse import urlsplit
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import BaseModel, ConfigDict, Field, field_validator
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError
from urllib3.util.connection import create_connection

from models import (
    DeviceSession, Item, Notification, NotificationEvent, NotificationPreference,
    PushDelivery, PushSubscription, User,
)
from notification_contracts import notification_event_adapter
from notification_outbox import LEASE_SECONDS, MAX_ATTEMPTS, RETRY_SECONDS, utcnow
from notification_service import can_receive, event_inventory, event_recipients
from push_config import PushConfig, load_push_config

logger = logging.getLogger(__name__)
# Exact service hosts only: never user-configurable suffixes or arbitrary destinations.
PUSH_HOSTS = frozenset({
    "fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com",
})
PUSH_TTL_SECONDS = 300


def validate_endpoint(endpoint: str) -> str:
    try:
        parsed = urlsplit(endpoint)
        valid = (
            parsed.scheme == "https" and parsed.hostname in PUSH_HOSTS
            and parsed.netloc == parsed.hostname
            and parsed.path.startswith("/") and len(parsed.path) > 1
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if (
        not valid or len(endpoint) > 2048
        or any(ord(char) <= 32 or ord(char) >= 127 for char in endpoint)
        or "\\" in endpoint
    ):
        raise ValueError("Endpoint Web Push non consentito")
    return endpoint


def decode_key(value: str, length: int) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Chiave Web Push non valida")
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except ValueError:
        raise ValueError("Chiave Web Push non valida") from None
    if len(decoded) != length:
        raise ValueError("Lunghezza chiave Web Push non valida")
    return decoded


class SubscriptionKeys(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    p256dh: str = Field(max_length=128)
    auth: str = Field(max_length=32)

    @field_validator("p256dh")
    @classmethod
    def public_key(cls, value: str) -> str:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), decode_key(value, 65))
        return value

    @field_validator("auth")
    @classmethod
    def auth_secret(cls, value: str) -> str:
        decode_key(value, 16)
        return value


class SubscriptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    endpoint: str = Field(max_length=2048)
    keys: SubscriptionKeys
    consent: bool
    expiration_time: int | None = Field(default=None, alias="expirationTime", ge=0)

    @field_validator("endpoint")
    @classmethod
    def endpoint_service(cls, value: str) -> str:
        return validate_endpoint(value)


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("ascii")).hexdigest()


def queue_push(db: Session, event: NotificationEvent, user_id: int) -> None:
    now = utcnow()
    for subscription in db.scalars(select(PushSubscription).where(
        PushSubscription.user_id == user_id,
        PushSubscription.created_at <= event.created_at,
    )):
        existing = db.scalar(select(PushDelivery.id).where(
            PushDelivery.event_id == event.id, PushDelivery.subscription_id == subscription.id,
        ))
        if existing is None:
            db.add(PushDelivery(
                event_id=event.id, subscription_id=subscription.id,
                generation=subscription.generation, created_at=now, available_at=now,
                expires_at=min(event.expires_at or now + timedelta(days=1), now + timedelta(days=1)),
            ))


@dataclass(frozen=True)
class PushClaim:
    delivery_id: int
    token: str


def claim_push(factory: sessionmaker, *, now: datetime | None = None) -> PushClaim | None:
    current = now or utcnow()
    with factory.begin() as db:
        # A crashed send may already be accepted. Do not retry an ambiguous attempt.
        db.execute(update(PushDelivery).where(
            PushDelivery.status == "sending", PushDelivery.leased_until <= current,
        ).values(
            status="uncertain", last_error="send_outcome_unknown", lease_token=None,
            leased_until=None,
        ))
        db.execute(update(PushDelivery).where(
            PushDelivery.status == "pending", PushDelivery.expires_at <= current,
        ).values(status="cancelled", last_error="expired"))
        eligible = (
            PushDelivery.status == "pending", PushDelivery.available_at <= current,
            PushDelivery.expires_at > current, PushDelivery.attempts < MAX_ATTEMPTS,
        )
        delivery_id = db.scalar(select(PushDelivery.id).where(
            *eligible,
        ).order_by(PushDelivery.id).limit(1))
        if delivery_id is None:
            return None
        token = str(uuid4())
        result = db.execute(update(PushDelivery).where(
            PushDelivery.id == delivery_id, *eligible,
        ).values(
            status="sending", lease_token=token,
            leased_until=current + timedelta(seconds=LEASE_SECONDS),
            attempts=PushDelivery.attempts + 1,
        ))
        return PushClaim(delivery_id, token) if result.rowcount == 1 else None


def authorized_subscription(
    db: Session, delivery: PushDelivery, config: PushConfig, now: datetime,
) -> PushSubscription | None:
    subscription = db.get(PushSubscription, delivery.subscription_id)
    if (
        subscription is None or subscription.generation != delivery.generation
        or subscription.vapid_fingerprint != config.fingerprint
        or subscription.expires_at <= now
    ):
        return None
    session = db.get(DeviceSession, subscription.session_id)
    user = db.get(User, subscription.user_id)
    if (
        session is None or session.user_id != subscription.user_id
        or session.revoked_at is not None or session.expires_at <= now or user is None
    ):
        return None
    event = db.get(NotificationEvent, delivery.event_id)
    if (
        event is None or event.schema_version != 1 or event.status != "completed"
        or event.expires_at is not None and event.expires_at <= now
    ):
        return None
    data = notification_event_adapter.validate_python(event.payload)
    inventory = event_inventory(db, event)
    if inventory is None or not can_receive(user, inventory):
        return None
    if user.id not in event_recipients(db, event):
        return None
    preference = db.scalar(select(NotificationPreference).where(
        NotificationPreference.user_id == user.id,
        NotificationPreference.event_type == data.event_type,
    ))
    if (
        preference is None or not preference.push_enabled
        or preference.data_mod > event.created_at
        or event.actor_id == user.id and not preference.include_own_actions
    ):
        return None
    return subscription


class SafeHTTPSConnection(HTTPSConnection):
    def _new_conn(self):
        if self.host not in PUSH_HOSTS or self.port != 443:
            raise ValueError("Push service not allowed")
        addresses = socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise ValueError("Push service did not resolve to public addresses")
        # Connect to validated numeric addresses, keeping the original host for TLS/SNI.
        # A second DNS lookup must not redirect the socket to a private network.
        for address in list(dict.fromkeys(row[4][0] for row in addresses))[:2]:
            try:
                return create_connection(
                    (address, 443), self.timeout, source_address=self.source_address,
                    socket_options=self.socket_options,
                )
            except OSError:
                continue
        raise NewConnectionError(self, "Push service connection failed") from None


class SafeHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = SafeHTTPSConnection


class SafePushAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        super().init_poolmanager(connections, maxsize, block=block, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {
            **self.poolmanager.pool_classes_by_scheme, "https": SafeHTTPSPool,
        }


class SafePushSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.trust_env = False
        self.mount("https://", SafePushAdapter())

    def request(self, method, url, **kwargs):
        validate_endpoint(url)
        kwargs["allow_redirects"] = False
        return super().request(method, url, **kwargs)


@dataclass(frozen=True)
class SendResult:
    status_code: int
    retry_after: int | None = None


def notification_push_payload(db: Session, event: NotificationEvent) -> dict[str, str]:
    inventory = event_inventory(db, event)
    if inventory is None:
        raise ValueError("Notification resource no longer exists")
    data = event.payload
    item = db.get(Item, data["item_id"]) if "item_id" in data else None
    if data["event_type"] == "item_quantity_changed":
        if inventory.type == "CHECKLIST":
            action = "Spunta: completato" if data["quantity"] >= 1 else "Spunta: da completare"
        else:
            delta = data["quantity"] - data["previous_quantity"]
            action = f"Quantità: {delta:+d} ({data['previous_quantity']} → {data['quantity']})"
    else:
        labels = {
            "name": "Titolo", "description": "Descrizione", "priority": "Priorità",
            "inventory_id": "Inventario/lista", "barcodes": "Barcode", "metadata": "Metadati",
            "assignment": "Assegnazione", "assignments": "Assegnazioni",
        }
        details = data.get("details", {})
        action = " · ".join(
            f"{labels.get(field, field)}: {details[field] if details[field] is not None else '(vuoto)'}"
            if field in details else f"{labels.get(field, field)}: modificato"
            for field in data["changed_fields"]
        )
    def compact(value: str, limit: int) -> str:
        text = " ".join(value.split())
        return text if len(text) <= limit else text[:limit - 1] + "…"
    kind = "Lista" if inventory.type == "CHECKLIST" else "Inventario"
    path = "checklists" if inventory.type == "CHECKLIST" else "inventories"
    return {
        "title": compact(f"{kind}: {inventory.name}", 80),
        "body": compact(f"{item.name} · {action}" if item is not None else action, 500),
        "url": f"/{path}/{inventory.id}", "tag": event.event_key,
    }


def send_push(subscription: PushSubscription, config: PushConfig, payload: dict[str, str]) -> SendResult:
    encoded_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with SafePushSession() as transport:
        try:
            response = webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=encoded_payload, vapid_private_key=Vapid(private_key=config.private_key),
                vapid_claims={"sub": config.subject}, ttl=PUSH_TTL_SECONDS,
                timeout=10, requests_session=transport,
            )
        except WebPushException as exc:
            if exc.response is None:
                raise
            response = exc.response
        if not isinstance(response, requests.Response):
            raise TypeError("Unexpected Web Push response")
        retry_after = response.headers.get("Retry-After", "")
        return SendResult(
            response.status_code,
            min(int(retry_after), 3600) if retry_after.isdigit() and len(retry_after) < 10 else None,
        )


def process_push(
    factory: sessionmaker, claim: PushClaim, sender=send_push, *,
    now: datetime | None = None,
) -> bool:
    current = now or utcnow()
    fence = (
        PushDelivery.id == claim.delivery_id, PushDelivery.status == "sending",
        PushDelivery.lease_token == claim.token, PushDelivery.leased_until > current,
    )
    try:
        config = load_push_config()
        with factory.begin() as db:
            if db.get_bind().dialect.name in ("mysql", "mariadb"):
                # Do not authorize against MySQL's old repeatable-read snapshot after waiting for locks.
                db.connection(execution_options={"isolation_level": "READ COMMITTED"})
            if db.execute(update(PushDelivery).where(*fence).values(
                lease_token=claim.token,
            )).rowcount != 1:
                return False
            delivery = db.get(PushDelivery, claim.delivery_id)
            subscription = db.get(PushSubscription, delivery.subscription_id)
            if config is None or subscription is None or delivery.expires_at <= current:
                delivery.status = "cancelled"
                delivery.last_error = "no_longer_authorized"
            else:
                # Lock the session/user rows through the authorization check and bounded send.
                # SQLite is fenced by the write above; other DBs serialize revocation/blocking.
                db.execute(select(PushSubscription).where(
                    PushSubscription.id == subscription.id,
                ).with_for_update().execution_options(populate_existing=True)).all()
                db.execute(select(DeviceSession).where(
                    DeviceSession.id == subscription.session_id,
                ).with_for_update().execution_options(populate_existing=True)).all()
                db.execute(select(User).where(
                    User.id == subscription.user_id,
                ).with_for_update().execution_options(populate_existing=True)).all()
                db.expire_all()
                send_now = utcnow() if now is None else current
                subscription = authorized_subscription(db, delivery, config, send_now)
                if (
                    subscription is None or delivery.expires_at <= send_now
                    or delivery.leased_until <= send_now
                ):
                    delivery.status = "cancelled"
                    delivery.last_error = "no_longer_authorized"
                else:
                    event = db.get(NotificationEvent, delivery.event_id)
                    payload = notification_push_payload(db, event)
                    if db.scalar(select(Notification.id).where(
                        Notification.event_id == event.id,
                        Notification.user_id == subscription.user_id,
                    )) is not None:
                        payload["url"] += f"?notification_event={event.event_key}"
                    result = sender(subscription, config, payload)
                    if result.status_code in (201, 202):
                        delivery.status = "accepted"
                        delivery.accepted_at = utcnow()
                        delivery.last_error = None
                    elif result.status_code in (404, 410):
                        # Remove credentials and all associated queued work for dead endpoints.
                        db.query(PushDelivery).filter(
                            PushDelivery.subscription_id == subscription.id,
                        ).delete(synchronize_session=False)
                        db.delete(subscription)
                        logger.info("Push delivery %s: expired endpoint removed", claim.delivery_id)
                        return True
                    elif result.status_code == 429 or 500 <= result.status_code <= 599:
                        delivery.status = "pending" if delivery.attempts < MAX_ATTEMPTS else "failed"
                        delivery.last_error = "push_service_temporary_error"
                        delay = max(
                            RETRY_SECONDS * 2 ** (delivery.attempts - 1), result.retry_after or 0,
                        )
                        delivery.available_at = current + timedelta(seconds=delay)
                    else:
                        delivery.status = "failed"
                        delivery.last_error = "push_service_rejected"
            delivery.lease_token = None
            delivery.leased_until = None
            logger.info("Push delivery %s: %s", delivery.id, delivery.status)
        return True
    except Exception as exc:
        # Transport timeouts/DB failures can occur after acceptance; never replay blindly.
        logger.error("Push delivery %s failed (%s)", claim.delivery_id, type(exc).__name__)
        with factory.begin() as db:
            db.execute(update(PushDelivery).where(
                PushDelivery.id == claim.delivery_id, PushDelivery.status == "sending",
                PushDelivery.lease_token == claim.token,
            ).values(
                status="uncertain", last_error="send_outcome_unknown",
                lease_token=None, leased_until=None,
            ))
        return False
