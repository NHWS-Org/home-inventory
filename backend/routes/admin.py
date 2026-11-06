from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from models import User, Role, RoleEnum
from dependencies import get_db, role_required
from routes.user import ensure_not_last_active_admin
from datetime import datetime, timedelta, timezone
import logging
from typing import Literal
from fastapi import Query
from fastapi.security import SecurityScopes
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from models import DeviceSession, SecurityAudit
from dependencies import get_current_user, oauth2_scheme, decode_access_token
from routes.auth import verify_password
from auth_config import automatic_key_mode, key_lock, rotate_automatic_key

logger = logging.getLogger(__name__)
EXTERNAL_ROTATION_MESSAGE = "Rotazione gestita tramite configurazione dell'installazione"


class SecurityConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=1, max_length=1024)
    confirm: Literal[True]


def audit_action(db: Session, user: User, action: str, outcome: str, sessions: int = 0) -> SecurityAudit:
    now = datetime.now(timezone.utc)
    record = SecurityAudit(
        actor_id=user.id, actor_username=user.username, action=action, outcome=outcome,
        created_at=now.replace(tzinfo=None), sessions_revoked=sessions,
        revoked_before=int(now.timestamp() * 1_000_000) if outcome in ("pending", "succeeded") else None,
    )
    db.add(record)
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("Security audit commit failed (%s); action rolled back", type(exc).__name__)
        raise HTTPException(500, "Impossibile salvare audit di sicurezza; operazione annullata.") from None
    return record

#router = APIRouter()
router = APIRouter(dependencies=[Depends(role_required(RoleEnum.admin))])


@router.get("/security")
def security_status():
    automatic = automatic_key_mode()
    return {
        "key_mode": "auto" if automatic else "external",
        "can_rotate": automatic,
        "rotation_message": None if automatic else EXTERNAL_ROTATION_MESSAGE,
    }


@router.get("/security/audit")
def security_audit(limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    rows = db.scalars(select(SecurityAudit).order_by(SecurityAudit.id.desc()).limit(limit))
    return [{
        "id": row.id, "actor_username": row.actor_username, "action": row.action,
        "outcome": row.outcome, "created_at": row.created_at,
        "sessions_revoked": row.sessions_revoked,
    } for row in rows]


@router.get("/security/sessions")
def security_sessions(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    current_id = decode_access_token(token).get("jti")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = db.execute(select(DeviceSession, User.username).join(
        User, DeviceSession.user_id == User.id,
    ).where(
        DeviceSession.revoked_at.is_(None),
    ).order_by(DeviceSession.created_at.desc(), DeviceSession.id.desc()))
    return [{
        "id": session.id, "username": username,
        "device_type": session.device_type, "browser": session.browser,
        "operating_system": session.operating_system,
        "created_at": session.created_at, "expires_at": session.expires_at,
        "is_expired": session.expires_at <= now,
        "is_current": session.session_token_id == current_id,
    } for session, username in rows]


def perform_security_action(
    action: Literal["revoke_sessions", "rotate_key"],
    payload: SecurityConfirmation,
    token: str,
    db: Session,
):
    with key_lock(exclusive=True):
        # Recheck authentication after waiting for any concurrent rotation.
        db.rollback()
        user = get_current_user(SecurityScopes(), token=token, db=db)
        db.refresh(user)
        if user.is_blocked:
            raise HTTPException(403, "Utente bloccato. Accesso negato.")
        if user.role is None or user.role.name != "admin":
            raise HTTPException(403, "Accesso negato: permessi insufficienti")
        recent_failures = db.scalar(select(func.count()).select_from(SecurityAudit).where(
            SecurityAudit.actor_id == user.id,
            SecurityAudit.outcome == "password_rejected",
            SecurityAudit.created_at >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5),
        ))
        if recent_failures >= 5:
            audit_action(db, user, action, "rate_limited")
            raise HTTPException(429, "Troppi tentativi. Riprovare tra 5 minuti.", headers={"Retry-After": "300"})
        if not verify_password(payload.password.get_secret_value(), user.hashed_password):
            audit_action(db, user, action, "password_rejected")
            raise HTTPException(403, "Password di conferma non valida")
        if action == "rotate_key" and not automatic_key_mode():
            audit_action(db, user, action, "blocked_external")
            raise HTTPException(409, EXTERNAL_ROTATION_MESSAGE)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = db.execute(update(DeviceSession).where(
            DeviceSession.revoked_at.is_(None),
        ).values(revoked_at=now))
        # Commit revocation + durable audit before changing a filesystem secret.
        record = audit_action(
            db, user, action, "pending" if action == "rotate_key" else "succeeded",
            result.rowcount,
        )
        if action == "rotate_key":
            rotation_failed = False
            try:
                rotate_automatic_key()
            except (OSError, RuntimeError) as exc:
                rotation_failed = True
                record.outcome = "rotation_failed"
                logger.error("Automatic JWT rotation failed (%s); sessions revoked", type(exc).__name__)
            else:
                record.outcome = "succeeded"
            try:
                db.commit()
            except SQLAlchemyError as exc:
                db.rollback()
                logger.error("JWT rotation audit finalization failed (%s); durable audit remains pending", type(exc).__name__)
                raise HTTPException(
                    500, "Sessioni revocate; esito rotazione non confermato nell'audit. Verificare i log e rifare login.",
                ) from None
            if rotation_failed:
                raise HTTPException(
                    500, "Rotazione non riuscita; sessioni revocate. Verificare storage e rifare login.",
                ) from None
        logger.warning("Admin security action %s completed; audit id %s", action, record.id)
        return {"message": "Operazione completata. Effettuare nuovamente il login."}


@router.post("/security/revoke-sessions")
def revoke_all_sessions(
    payload: SecurityConfirmation, token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    return perform_security_action("revoke_sessions", payload, token, db)


@router.post("/security/rotate-key")
def rotate_key(
    payload: SecurityConfirmation, token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    return perform_security_action("rotate_key", payload, token, db)

# Aggiorna il ruolo di un utente
@router.put("/users/{user_id}/role/")
def update_user_role(
    user_id: int,
    new_role: str,  # Cambiato da RoleEnum a str
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utente non trovato")

    # Converte il ruolo stringa in enum
    new_role_obj = db.query(Role).filter(Role.name == new_role).first()
    if not new_role_obj:
        raise HTTPException(status_code=404, detail="Ruolo non trovato")

    if new_role_obj.name != "admin":
        ensure_not_last_active_admin(db, user)

    try:
        user.role = new_role_obj
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ruolo non valido")

    db.commit()

    return {
        "message": "Ruolo aggiornato con successo",
        "username": user.username,
        "new_role": user.role.name
    }