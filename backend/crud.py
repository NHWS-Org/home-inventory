from sqlalchemy.orm import Session
from models import User, Role, Group, Setting
from schemas import UserCreate
from datetime import datetime, timezone
import logging
from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from models import DeviceSession


def cleanup_ended_sessions(db: Session, user_id: int | None = None) -> int:
    query = db.query(DeviceSession).filter(or_(
        DeviceSession.revoked_at.is_not(None),
        DeviceSession.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None),
    ))
    if user_id is not None:
        query = query.filter(DeviceSession.user_id == user_id)
    try:
        deleted = query.delete(synchronize_session=False)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logging.getLogger(__name__).exception("Errore nella pulizia manuale delle sessioni")
        raise HTTPException(500, "Pulizia sessioni non riuscita; nessuna eliminazione confermata.") from None
    logging.getLogger(__name__).info("Pulizia manuale sessioni: %s eliminate; user_id=%s", deleted, user_id)
    return deleted


def get_user(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()

def create_user(db: Session, user: UserCreate, hashed_password: str, role_id: int = None):
    db_user = User(username=user.username, email=user.email, hashed_password=hashed_password, role_id=user.role_id)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def assign_role_to_user(db: Session, user_id: int, role_id: int):
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.role_id = role_id
        db.commit()
        return user
    return None

def create_group(db: Session, name: str, role_id: int):
    group = Group(name=name, role_id=role_id)
    db.add(group)
    db.commit()
    db.refresh(group)
    return group

def add_user_to_group(db: Session, user_id: int, group_id: int):
    user = db.query(User).filter(User.id == user_id).first()
    group = db.query(Group).filter(Group.id == group_id).first()
    if user and group:
        group.users.append(user)
        db.commit()
        return group
    return None

def get_all_settings(db: Session):
    return db.query(Setting).all()

def get_setting(db: Session, key: str) -> Setting | None:
    setting = db.query(Setting).filter_by(key=key).first()
    return setting

def set_setting(db: Session, key: str, value: str, protected: bool = False):
    setting = db.query(Setting).filter_by(key=key).first()
    if setting:
        setting.value = value
    else:
        setting = Setting(key=key, value=value, protected=protected)
        db.add(setting)
    db.commit()

def delete_setting(db: Session, key: str):
    setting = db.query(Setting).filter_by(key=key).first()
    if setting and not setting.protected:
        db.delete(setting)
        db.commit()
        return True
    return False