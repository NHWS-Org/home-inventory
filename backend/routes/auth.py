from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from models import User, RoleEnum, Role
from schemas import UserCreateSelf, Token, UserResponse, UserSelfUpdate
from passlib.context import CryptContext
import jwt
import datetime
import os
import re
import uuid
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.security.utils import get_authorization_scheme_param
from dependencies import get_db, get_current_user, authenticated_user, decode_access_token
from crud import get_setting, set_setting, cleanup_ended_sessions
from models import DeviceSession
from auth_config import get_secret_key, current_secret_key, key_lock, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

router = APIRouter()

get_secret_key()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def _encode_access_token(data: dict, expires_delta: int):
    now = datetime.datetime.now(datetime.timezone.utc)
    expire = now + datetime.timedelta(minutes=expires_delta)
    to_encode = data.copy()
    to_encode.update({"exp": expire, "iat": now.timestamp()})
    return jwt.encode(to_encode, current_secret_key(), algorithm=ALGORITHM), expire


def create_access_token(data: dict, expires_delta: int = ACCESS_TOKEN_EXPIRE_MINUTES):
    with key_lock():
        token, _ = _encode_access_token(data, expires_delta)
        return token


def _device_details(user_agent: str) -> tuple[str, str, str]:
    ua = user_agent or ""

    def version(pattern: str) -> str | None:
        match = re.search(pattern, ua, re.IGNORECASE)
        return match.group(1).replace("_", ".") if match else None

    browser = "Unknown browser"
    for name, pattern in (
        ("Edge", r"Edg(?:e|A|iOS)?/([\d.]+)"),
        ("Opera", r"(?:OPR|Opera)/([\d.]+)"),
        ("Samsung Internet", r"SamsungBrowser/([\d.]+)"),
        ("Chrome", r"(?:Chrome|CriOS)/([\d.]+)"),
        ("Firefox", r"(?:Firefox|FxiOS)/([\d.]+)"),
        ("Safari", r"Version/([\d.]+).*Safari"),
    ):
        browser_version = version(pattern)
        if browser_version:
            browser = f"{name} {browser_version}"
            break

    operating_system = "Unknown OS"
    for name, pattern in (
        ("Windows", r"Windows NT ([\d.]+)"),
        ("Android", r"Android ([\d.]+)"),
        ("iOS", r"(?:iPhone OS|CPU OS) ([\d_]+)"),
        ("macOS", r"Mac OS X ([\d_]+)"),
    ):
        os_version = version(pattern)
        if os_version:
            operating_system = f"{name} {os_version}"
            break
    else:
        if "Linux" in ua:
            operating_system = "Linux"

    ua_lower = ua.lower()
    if "ipad" in ua_lower or "tablet" in ua_lower or ("android" in ua_lower and "mobile" not in ua_lower):
        device_type = "Tablet"
    elif any(marker in ua_lower for marker in ("mobile", "iphone", "ipod", "android")):
        device_type = "Mobile"
    else:
        device_type = "Desktop"

    return device_type, browser, operating_system


def _session_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

#############################################################################
# Registrazione utente
@router.post("/register", response_model=dict)
def register(
    user: UserCreateSelf,
    db: Session = Depends(get_db)
):
    setting = get_setting(db, "ENABLE_REGISTRATION")
    if (setting.value if setting else "true").lower() != "true":
        raise HTTPException(status_code=403, detail="Registrazione disabilitata")
    
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username già in uso")
    hashed_password = hash_password(user.password)

    viewer_role = db.query(Role).filter(Role.name == RoleEnum.viewer).first()
    if not viewer_role:
        raise HTTPException(status_code=500, detail="Ruolo viewer non trovato nel database")

    new_user = User(
        username=user.username,
        email=user.email,
        hashed_password=hashed_password,
        role_id=viewer_role.id
    )
    db.add(new_user)
    db.commit()
    return {"message": "Utente registrato con successo"}

#############################################################################
# Login utente
@router.post("/login", response_model=Token)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    #print(f"🔍 DEBUG: db ricevuto in login -> {db}")  # ✅ Debug

    if db is None:  # ✅ Debug: Controlla se db è None
        raise HTTPException(status_code=500, detail="Errore interno: database non disponibile")

    user = db.query(User).filter(User.username == form_data.username).first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenziali non valide")

    if user.is_blocked:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utente bloccato. Accesso negato.")
    
    session_token_id = str(uuid.uuid4())
    user_agent = request.headers.get("user-agent", "")
    device_type, browser, operating_system = _device_details(user_agent)
    region = request.headers.get("cf-ipcountry", "").upper()
    if not re.fullmatch(r"[A-Z]{2}", region):
        region = None
    with key_lock():
        token, expire = _encode_access_token(
            {"sub": user.username, "jti": session_token_id}, ACCESS_TOKEN_EXPIRE_MINUTES,
        )
        device_session = DeviceSession(
            session_token_id=session_token_id,
            user_id=user.id,
            device_type=device_type,
            browser=browser,
            operating_system=operating_system,
            user_agent=user_agent[:2048] or None,
            language=request.headers.get("accept-language", "")[:64] or None,
            timezone=request.headers.get("x-client-timezone", "")[:64] or None,
            region=region,
            expires_at=expire.replace(tzinfo=None),
        )
        db.add(device_session)
        db.commit()
    return {"access_token": token, "token_type": "bearer"}

#############################################################################
# Logout utente
@router.post("/logout")
def logout(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    payload = decode_access_token(token)
    session_token_id = payload.get("jti")
    if session_token_id:
        device_session = db.query(DeviceSession).filter(
            DeviceSession.session_token_id == session_token_id,
            DeviceSession.user_id == current_user.id,
        ).first()
        if device_session and not device_session.revoked_at:
            device_session.revoked_at = _session_now()
            db.commit()
    return {"message": f"Utente {current_user.username} disconnesso"}


@router.get("/sessions")
def get_device_sessions(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    session_token_id = decode_access_token(token).get("jti")
    sessions = db.query(DeviceSession).filter(
        DeviceSession.user_id == current_user.id,
    ).order_by(DeviceSession.created_at.desc()).all()
    return [
        {
            "id": session.id,
            "device_type": session.device_type,
            "browser": session.browser,
            "operating_system": session.operating_system,
            "language": session.language,
            "timezone": session.timezone,
            "region": session.region,
            "created_at": session.created_at,
            "expires_at": session.expires_at,
            "is_expired": session.expires_at <= _session_now(),
            "revoked_at": session.revoked_at,
            "is_current": session.session_token_id == session_token_id,
        }
        for session in sessions
    ]


@router.delete("/sessions")
def cleanup_own_sessions(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return {"deleted": cleanup_ended_sessions(db, user_id=current_user.id)}


@router.delete("/sessions/{session_id}")
def revoke_device_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    device_session = db.query(DeviceSession).filter(
        DeviceSession.id == session_id,
        DeviceSession.user_id == current_user.id,
    ).first()
    if not device_session:
        raise HTTPException(status_code=404, detail="Sessione non trovata")
    if not device_session.revoked_at:
        device_session.revoked_at = _session_now()
        db.commit()
    return {"message": "Sessione revocata"}

#############################################################################
# Info sull'utente loggato
@router.get("/me", response_model=dict)
def get_current_user_info(request: Request, db: Session = Depends(get_db)):
    auth: str = request.headers.get("Authorization")
    scheme, token = get_authorization_scheme_param(auth)

    if not token or scheme.lower() != "bearer":
        token = None

    if token:
        try:
            payload = jwt.decode(token, current_secret_key(), algorithms=[ALGORITHM])
            username: str = payload.get("sub")
            if not username:
                raise jwt.InvalidTokenError()
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Token non valido") from None
    else:
        username = None

    if not username:
        return {
            "id": None,
            "username": None,
            "email_masked": "",
            "email": "",
            "role": {
                "id": None,
                "name": None
            },
            "is_blocked": None,
            "data_ins": None,
            "data_mod": None
        }

    user = authenticated_user(db, payload)

    if not user or user.is_blocked:
        return {
            "id": None,
            "username": None,
            "email_masked": "",
            "email": "",
            "role": {
                "id": None,
                "name": None
            },
            "is_blocked": None,
            "data_ins": None,
            "data_mod": None
        }

    def mask_email(email: str) -> str:
        if not email or "@" not in email:
            return ""
        name, domain = email.split("@", 1)
        if len(name) <= 2:
            masked = name[0] + "*" + "@" + domain
        else:
            masked = name[0] + "*" * (len(name) - 2) + name[-1] + "@" + domain
        return masked

    return {
        "id": user.id,
        "username": user.username,
        "email_masked": mask_email(user.email),
        "email": user.email,
        "role": {
            "id": user.role.id if user.role else None,
            "name": user.role.name if user.role else None
        },
        "is_blocked": user.is_blocked,
        "data_ins": user.data_ins,
        "data_mod": user.data_mod
    }

#############################################################################
# Aggiornamento dati utente autenticato (anche se non ADMIN)
@router.put("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
def update_own_user(update: UserSelfUpdate, 
                    db: Session = Depends(get_db), 
                    current_user: User = Depends(get_current_user)):

    user = db.query(User).filter(User.id == current_user.id).first()

    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    if user.is_blocked:  # ✅ Access control: disallow updates from blocked users
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utente bloccato. Accesso negato.")

    if update.email:
        user.email = update.email
    if update.password:
        user.hashed_password = hash_password(update.password)

    db.commit()
    db.refresh(user)
    return user
