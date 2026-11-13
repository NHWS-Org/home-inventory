import os
from app_version import API_VERSION
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from dependencies import get_current_user, get_db
from models import Setting, User
from telemetry_service import get_public_stats

load_dotenv()

router = APIRouter()

##################################################
# Modelli per le statistiche pubbliche della community
class CountryStat(BaseModel):
    country: str
    n: int

class VersionStat(BaseModel):
    version: str
    n: int

class ChannelStat(BaseModel):
    channel: str
    n: int

class AboutStatsResponse(BaseModel):
    available: bool
    active_installations: int | None = None
    active_window_days: int | None = None
    countries: list[CountryStat] = []
    versions: list[VersionStat] = []
    channels: list[ChannelStat] = []

##################################################
# Modello per la risposta della versione dell'API
class VersionResponse(BaseModel):
    version: str

##################################################
# Modello per la risposta all'HEALTHCHECK dell'API
class HealthCheckResponse(BaseModel):
    status: str
    version: str

#################################################
# Endpoint per ottenere la versione dell'API
@router.get("/version", response_model=VersionResponse)
def get_api_version():
    return {"version": API_VERSION}

#################################################
# Endpoint usato dall'HEALTHCHECK di Docker
@router.get("/health-check", response_model=HealthCheckResponse)
def get_health():
    return {"status": "Everything is OK", "version": API_VERSION}

@router.get("/recent-items-limit")
def recent_items_limit(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    setting = db.get(Setting, "UI_RECENT_ITEMS_LIMIT")
    try:
        limit = int(setting.value) if setting is not None else None
    except (TypeError, ValueError):
        limit = None
    if limit is None or limit < 1:
        raise HTTPException(status_code=500, detail="Impostazione UI_RECENT_ITEMS_LIMIT mancante o non valida")
    return {"limit": limit}

#################################################
# Statistiche aggregate della community per la tab "About"
@router.get("/about-stats", response_model=AboutStatsResponse)
def about_stats():
    stats = get_public_stats()
    if stats is None:
        return AboutStatsResponse(available=False)
    return AboutStatsResponse(available=True, **stats)
