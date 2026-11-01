from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from assignment_service import build_assignment_response, pending_assigned_by_source
from dependencies import get_db
from models import Item, ListAssignment
from routes.auth import get_current_user
from routes.item import can_access_item
from schemas import AssignmentCreate, AssignmentResponse, AssignmentUpdate

router = APIRouter()


def _ensure_qty_within_stock(
    qty: int,
    source: Item,
    db: Session,
    *,
    assignment: ListAssignment | None = None,
) -> None:
    stock = int(source.quantity or 0)
    assigned = pending_assigned_by_source(db, [source.id]).get(source.id, 0)
    if assignment is not None and (assignment.list_item.quantity or 0) < 1:
        assigned -= assignment.qty
    available = max(0, stock - assigned)
    if qty > available and (assignment is None or qty > assignment.qty):
        raise HTTPException(
            status_code=400,
            detail=f"Quantita' superiore allo stock disponibile dopo le altre assegnazioni ({available})",
        )


def _get_assignment(db: Session, assignment_id: int) -> ListAssignment:
    assignment = db.query(ListAssignment).get(assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assegnazione non trovata")
    return assignment


@router.post("/", response_model=AssignmentResponse, status_code=status.HTTP_201_CREATED)
def create_assignment(payload: AssignmentCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    list_item = db.query(Item).get(payload.list_item_id)
    source = db.query(Item).get(payload.source_item_id)
    if not list_item or not source:
        raise HTTPException(status_code=404, detail="Item non trovato")
    if list_item.inventory.type != "CHECKLIST":
        raise HTTPException(status_code=400, detail="La riga deve appartenere a una lista")
    if source.inventory.type != "INVENTORY":
        raise HTTPException(status_code=400, detail="L'origine deve essere un item di inventario")
    if not can_access_item(user, list_item, action="edit") or not can_access_item(user, source, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    if list_item.list_assignment is not None:
        raise HTTPException(status_code=409, detail="La riga e' gia' collegata a un inventario")
    _ensure_qty_within_stock(payload.qty, source, db)

    assignment = ListAssignment(
        list_item_id=list_item.id, source_item_id=source.id, qty=payload.qty,
        user_ins=user.id, user_mod=user.id,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return build_assignment_response(assignment)


@router.get("/by-source/{item_id}", response_model=List[AssignmentResponse])
def list_assignments_by_source(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Assegnazioni collegate a un item di inventario, incluse le righe già spuntate."""
    source = db.query(Item).get(item_id)
    if not source:
        raise HTTPException(status_code=404, detail="Item non trovato")
    if not can_access_item(user, source, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    result = []
    for assignment in source.source_assignments:
        list_item = assignment.list_item
        if not can_access_item(user, list_item, action="view"):
            continue
        result.append(build_assignment_response(assignment))
    return result


@router.patch("/{assignment_id}", response_model=AssignmentResponse)
def update_assignment(assignment_id: int, payload: AssignmentUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    assignment = _get_assignment(db, assignment_id)
    if not can_access_item(user, assignment.list_item, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    _ensure_qty_within_stock(payload.qty, assignment.source_item, db, assignment=assignment)
    assignment.qty = payload.qty
    assignment.user_mod = user.id
    db.commit()
    db.refresh(assignment)
    return build_assignment_response(assignment)


@router.delete("/{assignment_id}")
def delete_assignment(assignment_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    assignment = _get_assignment(db, assignment_id)
    if not can_access_item(user, assignment.list_item, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    db.delete(assignment)
    db.commit()
    return {"detail": "Assegnazione eliminata"}
