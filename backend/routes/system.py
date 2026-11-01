import os
from fastapi import APIRouter
from pydantic import BaseModel
from dotenv import load_dotenv
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
    return {"version": os.getenv("API_VERSION", "unknown")}

#################################################
# Endpoint usato dall'HEALTHCHECK di Docker
@router.get("/health-check", response_model=HealthCheckResponse)
def get_health():
    return {"status": "Everything is OK", "version": os.getenv("API_VERSION", "unknown")}

#################################################
# Statistiche aggregate della community per la tab "About"
@router.get("/about-stats", response_model=AboutStatsResponse)
def about_stats():
    stats = get_public_stats()
    if stats is None:
        return AboutStatsResponse(available=False)
    return AboutStatsResponse(available=True, **stats)
