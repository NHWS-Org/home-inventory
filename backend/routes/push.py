import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from dependencies import decode_access_token, get_current_user, get_db, oauth2_scheme
from models import DeviceSession, PushDelivery, PushSubscription, User
from notification_outbox import utcnow
from push_config import PushConfigurationError, load_push_config
from web_push import SubscriptionInput, endpoint_hash

router = APIRouter()
logger = logging.getLogger(__name__)


def push_config():
    try:
        config = load_push_config()
    except PushConfigurationError:
        logger.error("Invalid Web Push installation configuration")
        raise HTTPException(503, "Configurazione Web Push non valida") from None
    if config is None:
        raise HTTPException(503, "Web Push disabilitato nell'installazione")
    return config


def current_session(db: Session, user: User, token: str) -> DeviceSession:
    session = db.scalar(select(DeviceSession).where(
        DeviceSession.user_id == user.id,
        DeviceSession.session_token_id == decode_access_token(token).get("jti"),
        DeviceSession.revoked_at.is_(None), DeviceSession.expires_at > utcnow(),
    ))
    if session is None:
        raise HTTPException(401, "Accedi nuovamente per registrare questo dispositivo")
    return session


@router.get("/config")
def config(user=Depends(get_current_user)):
    config = push_config()
    return {"public_key": config.public_key, "payload_mode": "detailed", "ttl_seconds": 300}


@router.post("/subscriptions", status_code=201)
def subscribe(
    payload: SubscriptionInput, token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db), user=Depends(get_current_user),
):
    config = push_config()
    session = current_session(db, user, token)
    if not payload.consent:
        raise HTTPException(422, "Consenso esplicito richiesto")
    now = utcnow()
    expires_at = session.expires_at
    if payload.expiration_time is not None:
        try:
            expires_at = min(
                expires_at,
                datetime.fromtimestamp(payload.expiration_time / 1000, timezone.utc).replace(tzinfo=None),
            )
        except (ValueError, OverflowError, OSError):
            raise HTTPException(422, "Scadenza sottoscrizione non valida") from None
        if expires_at <= now:
            raise HTTPException(422, "Sottoscrizione gia scaduta")
    digest = endpoint_hash(payload.endpoint)
    try:
        row = db.scalar(select(PushSubscription).where(
            PushSubscription.endpoint_hash == digest,
        ).with_for_update())
        if row is not None and row.user_id != user.id:
            raise HTTPException(409, "Sottoscrizione gia associata: ricreala nel browser")
        if row is None:
            count = db.scalar(select(func.count()).select_from(PushSubscription).where(
                PushSubscription.user_id == user.id,
            ))
            if count >= 100:
                raise HTTPException(409, "Limite sottoscrizioni raggiunto")
            row = PushSubscription(
                endpoint_hash=digest, endpoint=payload.endpoint, user_id=user.id,
            )
            db.add(row)
        if (
            row.session_id != session.id or row.p256dh != payload.keys.p256dh
            or row.auth != payload.keys.auth or row.vapid_fingerprint != config.fingerprint
            or row.expires_at is None or row.expires_at <= now
        ):
            row.generation = str(uuid4())
            row.created_at = now
        row.session_id = session.id
        row.p256dh = payload.keys.p256dh
        row.auth = payload.keys.auth
        row.vapid_fingerprint = config.fingerprint
        row.updated_at = now
        row.expires_at = expires_at
        db.commit()
        return {"id": row.id, "expires_at": row.expires_at, "payload_mode": "detailed"}
    except IntegrityError:
        db.rollback()
        logger.warning("Concurrent Web Push subscription registration")
        raise HTTPException(409, "Sottoscrizione modificata, riprova") from None
    except SQLAlchemyError:
        db.rollback()
        logger.error("Web Push subscription persistence failed")
        raise HTTPException(500, "Impossibile salvare la sottoscrizione") from None


@router.get("/subscriptions")
def subscriptions(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    session = current_session(db, user, token)
    return [{
        "id": row.id, "created_at": row.created_at, "expires_at": row.expires_at,
    } for row in db.scalars(select(PushSubscription).where(
        PushSubscription.user_id == user.id, PushSubscription.session_id == session.id,
    ).order_by(PushSubscription.id))]


@router.delete("/subscriptions/{subscription_id}")
def unsubscribe(
    subscription_id: int, token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db), user=Depends(get_current_user),
):
    session = current_session(db, user, token)
    row = db.scalar(select(PushSubscription).where(
        PushSubscription.id == subscription_id, PushSubscription.user_id == user.id,
        PushSubscription.session_id == session.id,
    ))
    if row is None:
        raise HTTPException(404, "Sottoscrizione non trovata")
    try:
        db.query(PushDelivery).filter(
            PushDelivery.subscription_id == row.id,
        ).delete(synchronize_session=False)
        db.delete(row)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.error("Web Push subscription deletion failed")
        raise HTTPException(500, "Impossibile eliminare la sottoscrizione") from None
    return {"deleted": 1}


@router.get("/deliveries")
def deliveries(
    limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return [{
        "id": row.id, "status": row.status, "attempts": row.attempts,
        "accepted_at": row.accepted_at, "last_error": row.last_error,
    } for row in db.scalars(select(PushDelivery).join(
        PushSubscription, PushSubscription.id == PushDelivery.subscription_id,
    ).where(PushSubscription.user_id == user.id).order_by(PushDelivery.id.desc()).limit(limit))]
