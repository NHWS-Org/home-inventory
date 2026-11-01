"""Telemetria anonima opt-in.

Disattivata di default: si attiva solo con TELEMETRY_ENABLED=true.
Dati inviati: ID casuale dell'installazione, versione, numero di inventari e data
dell'ultima modifica. Nessun contenuto dell'inventario, nessun nome utente.
La nazione viene ricavata dal server di ricezione, che non salva l'indirizzo IP.

La tab "About" legge inoltre le statistiche aggregate pubbliche (sola GET, nessun dato
inviato); si disattiva con ABOUT_STATS_ENABLED=false.
"""
import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from crud import get_setting, set_setting
from models import Inventory, Item

logger = logging.getLogger(__name__)

# Endpoint pubblico di raccolta (Cloudflare Worker).
# TELEMETRY_URL, se presente, ha la precedenza (endpoint personalizzato).
DEFAULT_TELEMETRY_URL = "https://home-inventory-telemetry.nhws.workers.dev/ping"
INSTANCE_ID_KEY = "TELEMETRY_INSTANCE_ID"
HTTP_TIMEOUT_SECONDS = 5
USER_AGENT = "home-inventory-telemetry/1.0 (https://github.com/NHWS-Org/home-inventory)"


def telemetry_enabled() -> bool:
    return os.getenv("TELEMETRY_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def telemetry_url() -> str:
    return os.getenv("TELEMETRY_URL", "").strip() or DEFAULT_TELEMETRY_URL


ABOUT_CACHE_SECONDS = 3600
ABOUT_FAILURE_CACHE_SECONDS = 300
_about_cache: dict = {"fetched_at": 0.0, "ttl": 0, "data": None}


def about_stats_enabled() -> bool:
    return os.getenv("ABOUT_STATS_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def public_stats_url() -> str:
    url = telemetry_url()
    if not url:
        return ""
    return url[: -len("/ping")] + "/public-stats" if url.endswith("/ping") else url.rstrip("/") + "/public-stats"


def get_public_stats() -> dict | None:
    """Legge le statistiche aggregate pubbliche dal server di raccolta (cache in memoria).

    È una semplice GET: non invia alcun dato dell'installazione. Restituisce None se
    non disponibile; non solleva mai eccezioni.
    """
    if not about_stats_enabled():
        return None
    url = public_stats_url()
    if not url:
        return None
    now = time.monotonic()
    if _about_cache["fetched_at"] and now - _about_cache["fetched_at"] < _about_cache["ttl"]:
        return _about_cache["data"]

    data = None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            raw = json.loads(response.read(65536))
        data = {
            "active_installations": int(raw["active_installations"]),
            "active_window_days": int(raw["active_window_days"]),
            "countries": [{"country": str(c["country"]), "n": int(c["n"])} for c in raw["countries"]],
            "versions": [{"version": str(v["version"]), "n": int(v["n"])} for v in raw["versions"]],
            # assente nelle versioni precedenti del Worker
            "channels": [{"channel": str(c["channel"]), "n": int(c["n"])} for c in raw.get("channels", [])],
        }
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, KeyError, TypeError):
        logger.info("Statistiche pubbliche non disponibili.")

    _about_cache.update(
        fetched_at=now,
        ttl=ABOUT_CACHE_SECONDS if data else ABOUT_FAILURE_CACHE_SECONDS,
        data=data,
    )
    return data


def get_instance_id(db: Session) -> str:
    env_id = os.getenv("TELEMETRY_INSTANCE_ID", "").strip()
    if env_id:
        return env_id
    setting = get_setting(db, INSTANCE_ID_KEY)
    if setting and setting.value:
        return setting.value
    instance_id = str(uuid.uuid4())
    set_setting(db, INSTANCE_ID_KEY, instance_id, True)
    return instance_id


def _last_activity(db: Session) -> str | None:
    latest = [
        value
        for value in (db.query(func.max(Item.data_mod)).scalar(), db.query(func.max(Inventory.data_mod)).scalar())
        if value is not None
    ]
    if not latest:
        return None
    # I DateTime del DB sono naive e salvati in UTC dal server
    return max(latest).replace(tzinfo=timezone.utc).isoformat()


def _channel() -> str:
    channel = os.getenv("IMAGE_CHANNEL", "").strip().lower()
    return channel if channel in ("release", "dev") else "unknown"


def build_payload(db: Session) -> dict:
    return {
        "id": get_instance_id(db),
        "version": os.getenv("API_VERSION", "unknown"),
        "channel": _channel(),
        "inventories": db.query(Inventory).filter(Inventory.type == "INVENTORY").count(),
        "last_activity": _last_activity(db),
    }


def send_telemetry(db: Session) -> bool:
    """Invia un ping anonimo. Non solleva mai eccezioni: la telemetria non deve disturbare l'app."""
    if not telemetry_enabled():
        return False
    url = telemetry_url()
    if not url:
        logger.warning("TELEMETRY_ENABLED è attivo ma nessun endpoint è configurato: telemetria non inviata.")
        return False
    try:
        body = json.dumps(build_payload(db)).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS):
            pass
        return True
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        logger.info(f"Invio telemetria non riuscito: {exc}")
        return False
    except Exception:
        logger.exception("Errore inatteso nell'invio della telemetria.")
        return False
