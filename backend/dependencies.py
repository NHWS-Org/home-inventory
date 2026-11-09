from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm, SecurityScopes
from database import SessionLocal, Session
from models import User, RoleEnum, Role, DeviceSession, SecurityAudit
from crud import get_setting, set_setting
import jwt
import os
import datetime
from auth_config import get_secret_key, current_secret_key, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from sqlalchemy import select, func

get_secret_key()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# Funzione per ottenere la sessione del database
def get_db():
    db = SessionLocal()
    
    if db is None:
        print("❌ ERRORE: La sessione DB è None!")  # ✅ Debug in caso di errore 

    try:
        yield db
    finally:
        db.close()

# Funzione per inizializzare i ruoli e l'admin
def init_roles_and_admin(db: Session):
    from routes.auth import hash_password
    role_objects = {}
    admin_username = "admin"

    # 1️⃣ Creiamo i ruoli senza user_ins
    for role_enum in RoleEnum:
        role_name = role_enum.value  # 👈 Otteniamo il valore della Enum
        existing_role = db.query(Role).filter(Role.name == role_name).first()
        if not existing_role:
            new_role = Role(name=role_name)  # 👈 Non assegniamo subito user_ins
            db.add(new_role)
            db.flush()  # 👈 Necessario per ottenere l'ID subito senza commit
            role_objects[role_name] = new_role

    db.commit()

    # 2️⃣ Creiamo l'utente ADMIN
    admin_password = os.getenv("ADMIN_PASSWORD")  # La password viene letta da un ENV

    admin_user = db.query(User).filter(User.username == admin_username).first()
    if not admin_user:
        if not admin_password:
            raise RuntimeError("ADMIN_PASSWORD must be configured when creating the initial admin account.")
        admin_user = User(
            username=admin_username,
            hashed_password=hash_password(admin_password),
            role_id=role_objects[RoleEnum.admin.value].id  # 👈 Assegniamo subito il ruolo admin
        )
        db.add(admin_user)
        db.commit()

    # 3️⃣ Aggiorniamo i ruoli con `user_ins`
    for role in role_objects.values():
        role.user_ins = admin_user.id  # 👈 Ora assegniamo l'utente
    db.commit()

def authenticated_user(db: Session, payload: dict) -> User | None:
    # Integer microseconds retain precision even on databases with second-only DATETIME.
    cutoff_query = select(func.max(SecurityAudit.revoked_before)).scalar_subquery()
    result = db.query(User, cutoff_query).filter(User.username == payload.get("sub")).first()
    if result is None:
        return None
    user, cutoff = result
    user_cutoff = user.auth_revoked_before
    if cutoff is not None or user_cutoff is not None:
        issued_at = payload.get("iat")
        if (
            type(issued_at) not in (int, float)
            or cutoff is not None and issued_at <= cutoff / 1_000_000
            or user_cutoff is not None and issued_at <= user_cutoff / 1_000_000
        ):
            raise HTTPException(status_code=401, detail="Sessione revocata")
    session_token_id = payload.get("jti")
    if session_token_id:
        session = db.query(DeviceSession).filter(
            DeviceSession.session_token_id == session_token_id,
            DeviceSession.user_id == user.id,
        ).first()
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        if not session or session.revoked_at or session.expires_at <= now:
            raise HTTPException(status_code=401, detail="Sessione non valida o revocata")
    return user


# Funzione per ottenere l'utente corrente
def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, current_secret_key(), algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token non valido") from None


def get_current_user(security_scopes: SecurityScopes,
                     token: str = Depends(oauth2_scheme),
                     db: Session = Depends(get_db)
):
    try:
        payload = decode_access_token(token)
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token non valido")
        user = authenticated_user(db, payload)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utente non trovato")
        if user.role is None:
            raise HTTPException(status_code=403, detail="Accesso negato: ruolo non assegnato")
        if user.is_blocked:  # ✅ Blocca l'accesso agli utenti disabilitati
            raise HTTPException(status_code=403, detail="Utente bloccato. Accesso negato.")
        return user
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token non valido")

# Funzione per verificare il ruolo dell'utente
def role_required(required_role: RoleEnum):  # ✅ Accetta RoleEnum invece di str
    def dependency(user: User = Depends(get_current_user)):
        if user.role is None:
            raise HTTPException(status_code=403, detail="Accesso negato: ruolo non assegnato")
        if user.role.name != required_role.value:  # ✅ Confronto con RoleEnum
            raise HTTPException(status_code=403, detail="Accesso negato: permessi insufficienti")
        return user
    return dependency

def initialize_settings(db: Session):
    defaults = {
        "ENABLE_REGISTRATION": "true",
        "BACKUP_FREQUENCY": "none",
        "BACKUP_INTERVAL_DAYS": None,
        "BACKUP_INTERVAL_HOURS": None,
        "BACKUP_INTERVAL_MINUTES": None,
        "BACKUP_RETENTION": None,  # numero di backup da mantenere
        "BACKUP_LAST_RUN": None,
        "UI_RECENT_ITEMS_LIMIT": "10",
        "AUDIT_RETENTION_DAYS": "90",  # giorni prima di pulire le versioni storiche
        "DEVICE_SESSION_RETENTION_DAYS": "30",
    }
    for key, value in defaults.items():
        setting = get_setting(db, key)
        if setting is None:
            set_setting(db, key, value, True)  # ✅ Proteggiamo le impostazioni di default
        elif key == "DEVICE_SESSION_RETENTION_DAYS" and not setting.protected:
            setting.protected = True
            db.commit()