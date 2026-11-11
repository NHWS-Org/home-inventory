from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import not_
from routes.auth import hash_password, get_current_user
from routes.inventory import can_access_inventory
from dependencies import get_db, role_required
from models import User, RoleEnum, Role, Group, Inventory, UserGroupAssociation
import crud, schemas
from typing import List

router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(role_required(RoleEnum.admin))])

def ensure_not_last_active_admin(db: Session, user: User) -> None:
    """Verifica che l'utente non sia l'ultimo amministratore attivo e abilitato nel sistema."""
    if user.role and user.role.name == "admin" and not user.is_blocked:
        active_admins = db.query(User).join(User.role).filter(
            User.is_blocked == False,
            Role.name == "admin",
            User.id != user.id
        ).count()
        if active_admins == 0:
            raise HTTPException(
                status_code=403,
                detail="Impossibile disabilitare o rimuovere il ruolo all'ultimo utente ADMIN attivo"
            )

#############################################################################
# Creazione utente
@admin_router.post("/users/", response_model=schemas.UserResponse)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    hashed_password = hash_password(user.password)
    return crud.create_user(db, user, hashed_password)

# Elenco utenti
@admin_router.get("/users/", response_model=list[schemas.UserResponse])
def list_users(db: Session = Depends(get_db)):
    # ⚡ Bolt optimization: Preload User.role via joinedload to prevent N+1 queries during UserResponse serialization.
    # Impact: Reduces query count from O(N_roles) to O(1) constant query.
    return db.query(User).options(joinedload(User.role)).all()

# Modifica utente
@admin_router.put("/users/{user_id}", response_model=schemas.UserResponse)
def update_user(user_id: int, update: schemas.UserUpdate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    #if update.username is not None:
    #    user.username = update.username
    if update.password is not None:
        user.hashed_password = hash_password(update.password)
    if update.email is not None:
        user.email = update.email
    if update.is_blocked is not None:
        if update.is_blocked:
            ensure_not_last_active_admin(db, user)
        user.is_blocked = update.is_blocked
    if update.role_id is not None:
        role = db.query(Role).filter(Role.id == update.role_id).first()
        if not role:
            raise HTTPException(status_code=404, detail="Ruolo non trovato")
        if role.name != "admin":
            ensure_not_last_active_admin(db, user)
        user.role_id = update.role_id

    db.commit()
    db.refresh(user)
    return user

# Eliminazione utente
@admin_router.delete("/users/{user_id}", response_model=dict)
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    if user.username == "ADMIN":
        raise HTTPException(status_code=403, detail="Non puoi eliminare l'utente ADMIN")
    if user.role and user.role.name == "admin":
        active_admins = db.query(User).join(User.role).filter(User.is_blocked == False, Role.name == "admin", User.id != user.id).count()
        if active_admins == 0:
            raise HTTPException(status_code=403, detail="Impossibile eliminare l'ultimo utente ADMIN abilitato")

    db.delete(user)
    db.commit()
    return {"detail": "Utente eliminato"}

#############################################################################
# Creazione ruolo
@admin_router.post("/roles/", response_model=schemas.RoleResponse)
def create_role(role: schemas.RoleCreate, db: Session = Depends(get_db)):
    return crud.create_role(db, role.name)

# Elenco ruoli
@admin_router.get("/roles/", response_model=list[schemas.RoleResponse])
def list_roles(db: Session = Depends(get_db)):
    return db.query(Role).all()

# Modifica ruolo
@admin_router.put("/roles/{role_id}", response_model=schemas.RoleResponse)
def update_role(role_id: int, update: schemas.RoleCreate, db: Session = Depends(get_db)):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Ruolo non trovato")
    role.name = update.name
    db.commit()
    db.refresh(role)
    return role

# Eliminazione ruolo
@admin_router.delete("/roles/{role_id}", response_model=dict)
def delete_role(role_id: int, db: Session = Depends(get_db)):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Ruolo non trovato")
    db.delete(role)
    db.commit()
    return {"detail": "Ruolo eliminato"}

#############################################################################
# Creazione gruppo
@admin_router.post("/groups/", response_model=schemas.GroupResponse)
def create_group(group: schemas.GroupCreate, db: Session = Depends(get_db)):
    return crud.create_group(db, group.name, group.role_id)

# Elenco gruppi
@admin_router.get("/groups/", response_model=list[schemas.GroupResponse])
def list_groups(db: Session = Depends(get_db)):
    # ⚡ Bolt optimization: Eager load Group.role and Group.users with User.role.
    # Impact: Reduces query count from O(G + U) to O(1) constant query during GroupResponse serialization.
    return (
        db.query(Group)
        .options(
            joinedload(Group.role),
            joinedload(Group.users).joinedload(User.role),
        )
        .all()
    )

# Modifica gruppo
@admin_router.put("/groups/{group_id}", response_model=schemas.GroupResponse)
def update_group(group_id: int, update: schemas.GroupCreate, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Gruppo non trovato")
    group.name = update.name
    group.role_id = update.role_id
    db.commit()
    db.refresh(group)
    return group

# Eliminazione gruppo
@admin_router.delete("/groups/{group_id}", response_model=dict)
def delete_group(group_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Gruppo non trovato")
    db.delete(group)
    db.commit()
    return {"detail": "Gruppo eliminato"}

#############################################################################
# Assegnazione utente a gruppo
@admin_router.post("/groups/{group_id}/add_user/{user_id}", response_model=schemas.GroupResponse)
def add_user_to_group(group_id: int, user_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    user = db.query(User).filter(User.id == user_id).first()

    if not group or not user:
        raise HTTPException(status_code=404, detail="Gruppo o utente non trovato")

    if user not in group.users:
        group.users.append(user)
        db.commit()
        db.refresh(group)

    return group

# Rimozione utente da gruppo
@admin_router.delete("/groups/{group_id}/remove_user/{user_id}", response_model=schemas.GroupResponse)
def remove_user_from_group(group_id: int, user_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    user = db.query(User).filter(User.id == user_id).first()

    if not group or not user:
        raise HTTPException(status_code=404, detail="Gruppo o utente non trovato")

    if user in group.users:
        group.users.remove(user)
        db.commit()
        db.refresh(group)

    return group

#############################################################################
# Assegnazione ruolo a utente
@admin_router.post("/users/{user_id}/role/{role_id}")
def assign_role(user_id: int, role_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Ruolo non trovato")
    if role.name != "admin":
        ensure_not_last_active_admin(db, user)
    user.role_id = role.id
    db.commit()
    db.refresh(user)
    return schemas.UserResponse.model_validate(user)  # ✅ Converti SQLAlchemy → Pydantic

# Blocco/sblocco utente
@admin_router.patch("/users/{user_id}/block", response_model=dict)
def block_user(user_id: int,
               db: Session = Depends(get_db),
               current_user: User = Depends(role_required(RoleEnum.admin))
):
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    # ✅ Previene auto-blocco
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Non puoi bloccare te stesso!")

    if not user.is_blocked:
        ensure_not_last_active_admin(db, user)

    user.is_blocked = not user.is_blocked  # ✅ Inverte lo stato
    db.commit()
    db.refresh(user)
    
    status_text = "bloccato" if user.is_blocked else "sbloccato"
    return {"message": f"Utente {user.username} {status_text}", "user": schemas.UserResponse.model_validate(user)}

router.include_router(admin_router)

@router.get("/users/shareable/{inventory_id}", response_model=List[schemas.UserResponse])
def get_shareable_users(inventory_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inventory = db.query(Inventory).options(
        joinedload(Inventory.shared_with_users),
        joinedload(Inventory.shared_with_groups)
    ).get(inventory_id)
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventario non trovato")

    if not can_access_inventory(current_user, inventory, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    # ⚡ Bolt optimization: Batch group user lookups and eager-load roles to avoid N+1 queries.
    # Impact: Reduces query count from O(G + U) to O(1) where G is shared groups and U is non-admin users.
    # Utenti con accesso diretto
    shared_user_ids = {s.user_id for s in inventory.shared_with_users}

    # Utenti che hanno già accesso tramite gruppo (query singola su UserGroupAssociation)
    shared_group_ids = [s.group_id for s in inventory.shared_with_groups]
    if shared_group_ids:
        group_user_ids = (
            db.query(UserGroupAssociation.user_id)
            .filter(UserGroupAssociation.group_id.in_(shared_group_ids))
            .all()
        )
        shared_user_ids.update(uid for (uid,) in group_user_ids)

    # Security: Defense-in-depth to exclude blocked/deactivated users from being discovered or shared with.
    # Tutti gli utenti non admin attivi, con ruolo pre-caricato per evitare N+1 in fase di serializzazione UserResponse
    all_users = (
        db.query(User)
        .options(joinedload(User.role))
        .filter(User.role.has(Role.name != "admin"), User.is_blocked.is_(False))
        .all()
    )

    # Ritorna solo quelli non ancora condivisi in nessun modo
    return [u for u in all_users if u.id not in shared_user_ids]