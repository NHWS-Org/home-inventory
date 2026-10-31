import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from models import BarcodeProductCache

# Anagrafica esterna: famiglia Open * Facts (gratuita, senza API key, dati ODbL).
# Ogni fonte viene interrogata in ordine finche' non trova il prodotto.
LOOKUP_SOURCES = [
    ("openfoodfacts", "https://world.openfoodfacts.org"),
    ("openbeautyfacts", "https://world.openbeautyfacts.org"),
    ("openpetfoodfacts", "https://world.openpetfoodfacts.org"),
    ("openproductsfacts", "https://world.openproductsfacts.org"),
]
# Libri (ISBN-13 978/979): Open Library. Per i farmaci non esiste un'API pubblica per codice
# (AIFA pubblica solo open data scaricabili), quindi restano riconosciuti ma senza anagrafica dedicata.
BOOK_SOURCE = ("openlibrary", "https://openlibrary.org")
# Fallback per i libri non presenti su Open Library (es. editoria italiana). La chiave e' opzionale,
# ma senza chiave la quota giornaliera condivisa di Google e' spesso esaurita (errore, mai cache negativa).
GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
USER_AGENT = "home-inventory/1.0 (https://github.com/NHWS-Org/home-inventory)"
HTTP_TIMEOUT_SECONDS = 4
CACHE_TTL_FOUND = timedelta(days=30)
CACHE_TTL_NOT_FOUND = timedelta(days=1)
_ACTIVE_SOURCE_CHECK: ContextVar[dict[str, str] | None] = ContextVar("barcode_source_check", default=None)


def _record_source_error(detail: str) -> None:
    check = _ACTIVE_SOURCE_CHECK.get()
    if check is not None:
        check["detail"] = detail[:300]


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    detail = f"HTTP {exc.code} {exc.reason}"
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        error = payload.get("error") if isinstance(payload, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        reasons = [entry.get("reason") for entry in error.get("errors", []) if isinstance(entry, dict) and entry.get("reason")] if isinstance(error, dict) else []
        if message:
            detail += f": {message}"
        if reasons:
            detail += f" ({', '.join(reasons)})"
    except (ValueError, UnicodeDecodeError, OSError):
        pass
    return detail[:300]


def lookup_enabled() -> bool:
    return os.getenv("BARCODE_LOOKUP_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


# DataMatrix GS1 dei farmaci: "01" + GTIN-14 seguito da scadenza (17), lotto (10), seriale (21)...
_GS1_GTIN_RE = re.compile(r"^(?:\]d2)?01(\d{14})(?=.)", re.DOTALL)


def is_valid_isbn10(code: str) -> bool:
    if not re.fullmatch(r"\d{9}[\dXx]", code):
        return False
    total = sum((10 - i) * (10 if c in "Xx" else int(c)) for i, c in enumerate(code))
    return total % 11 == 0


def isbn10_to_isbn13(code: str) -> str:
    body = "978" + code[:9]
    check = (10 - sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body)) % 10) % 10
    return body + str(check)


def is_isbn13(code: str) -> bool:
    return len(code) == 13 and code.startswith(("978", "979")) and is_valid_gtin(code)


def normalize_code(raw: str) -> str:
    """Normalizza un codice scansionato.

    I codici numerici perdono spazi; gli UPC-A (12 cifre) diventano EAN-13 con zero
    iniziale, cosi' la stessa etichetta letta da scanner diversi coincide.
    Gli ISBN-10 (anche con trattini) diventano ISBN-13; dal DataMatrix GS1 dei farmaci
    si estrae il GTIN. I codici non numerici (QR, Code128 alfanumerici) vengono solo ripuliti.
    """
    code = (raw or "").strip()
    gs1 = _GS1_GTIN_RE.match(code)
    if gs1 and is_valid_gtin(gs1.group(1)):
        gtin = gs1.group(1)
        return gtin[1:] if gtin.startswith("0") else gtin
    isbn = re.sub(r"[\s-]", "", code)
    if is_valid_isbn10(isbn):
        return isbn10_to_isbn13(isbn)
    if re.fullmatch(r"97[89]\d{10}", isbn) and is_valid_gtin(isbn):
        return isbn
    compact = re.sub(r"\s+", "", code)
    if compact.isdigit():
        return "0" + compact if len(compact) == 12 else compact
    return code


def is_valid_gtin(code: str) -> bool:
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    check = digits.pop()
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
    return (10 - total % 10) % 10 == check


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fetch_product(base_url: str, code: str) -> tuple[str, Optional[dict]]:
    """Ritorna ("found", prodotto) | ("missing", None) | ("error", None)."""
    url = (
        f"{base_url}/api/v2/product/{urllib.parse.quote(code)}.json"
        "?fields=product_name,product_name_it,generic_name,brands,quantity,image_front_small_url"
    )
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        _record_source_error(_http_error_detail(exc))
        return ("missing", None) if exc.code == 404 else ("error", None)
    except urllib.error.URLError as exc:
        _record_source_error(f"Errore di rete: {exc.reason}")
        return "error", None
    except TimeoutError:
        _record_source_error(f"Timeout dopo {HTTP_TIMEOUT_SECONDS} secondi")
        return "error", None
    except ValueError:
        _record_source_error("La risposta non contiene JSON valido")
        return "error", None
    except OSError as exc:
        _record_source_error(f"Errore di connessione ({type(exc).__name__})")
        return "error", None
    product = payload.get("product") if payload.get("status") == 1 else None
    return ("found", product) if product else ("missing", None)


def _fetch_book(base_url: str, code: str) -> tuple[str, Optional[dict]]:
    """Come _fetch_product, ma da Open Library; il risultato usa le chiavi di Open * Facts."""
    key = f"ISBN:{code}"
    url = f"{base_url}/api/books?bibkeys={urllib.parse.quote(key)}&format=json&jscmd=data"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        _record_source_error(_http_error_detail(exc))
        return ("missing", None) if exc.code == 404 else ("error", None)
    except urllib.error.URLError as exc:
        _record_source_error(f"Errore di rete: {exc.reason}")
        return "error", None
    except TimeoutError:
        _record_source_error(f"Timeout dopo {HTTP_TIMEOUT_SECONDS} secondi")
        return "error", None
    except ValueError:
        _record_source_error("La risposta non contiene JSON valido")
        return "error", None
    except OSError as exc:
        _record_source_error(f"Errore di connessione ({type(exc).__name__})")
        return "error", None
    book = payload.get(key) if isinstance(payload, dict) else None
    if not book or not book.get("title"):
        return "missing", None
    title = book["title"]
    if book.get("subtitle"):
        title = f"{title}: {book['subtitle']}"
    authors = " & ".join(a["name"] for a in book.get("authors", []) if a.get("name"))
    publishers = book.get("publishers") or []
    cover = book.get("cover") or {}
    return "found", {
        "product_name": title,
        "brands": authors,
        "quantity": publishers[0].get("name") if publishers else None,
        "image_front_small_url": cover.get("small"),
    }


def _fetch_google_book(code: str) -> tuple[str, Optional[dict]]:
    """Come _fetch_book, ma da Google Books."""
    params = {"q": f"isbn:{code}", "maxResults": "1"}
    api_key = os.getenv("GOOGLE_BOOKS_API_KEY", "").strip()
    if api_key:
        params["key"] = api_key
    url = f"{GOOGLE_BOOKS_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        _record_source_error(_http_error_detail(exc))
        return ("missing", None) if exc.code == 404 else ("error", None)
    except urllib.error.URLError as exc:
        _record_source_error(f"Errore di rete: {exc.reason}")
        return "error", None
    except TimeoutError:
        _record_source_error(f"Timeout dopo {HTTP_TIMEOUT_SECONDS} secondi")
        return "error", None
    except ValueError:
        _record_source_error("La risposta non contiene JSON valido")
        return "error", None
    except OSError as exc:
        _record_source_error(f"Errore di connessione ({type(exc).__name__})")
        return "error", None
    items = payload.get("items") if isinstance(payload, dict) else None
    info = (items[0].get("volumeInfo") if items else None) or {}
    if not info.get("title"):
        return "missing", None
    title = info["title"]
    if info.get("subtitle"):
        title = f"{title}: {info['subtitle']}"
    thumb = (info.get("imageLinks") or {}).get("smallThumbnail")
    return "found", {
        "product_name": title,
        "brands": " & ".join(info.get("authors") or []),
        "quantity": info.get("publisher"),
        "image_front_small_url": thumb.replace("http://", "https://", 1) if thumb else None,
    }


def _sources_for(code: str) -> list[tuple[str, Callable[[str], tuple[str, Optional[dict]]]]]:
    if is_isbn13(code):
        name, base_url = BOOK_SOURCE
        return [(name, lambda c: _fetch_book(base_url, c)), ("googlebooks", _fetch_google_book)]
    return [(name, lambda c, u=base_url: _fetch_product(u, c)) for name, base_url in LOOKUP_SOURCES]


def lookup_product(
    db: Session,
    code: str,
    source_checks: list[dict[str, str]] | None = None,
) -> Optional[BarcodeProductCache]:
    """Restituisce la riga di cache (found=True) oppure None. Non solleva mai per errori di rete."""
    if not lookup_enabled() or not is_valid_gtin(code):
        return None

    now = _utc_now_naive()
    cached = db.get(BarcodeProductCache, code)
    if cached is not None:
        ttl = CACHE_TTL_FOUND if cached.found else CACHE_TTL_NOT_FOUND
        if now - cached.fetched_at < ttl:
            return cached if cached.found else None

    found_product = None
    found_source = None
    all_missing = True
    for source, fetch in _sources_for(code):
        check = {"source": source, "outcome": "pending"}
        token = _ACTIVE_SOURCE_CHECK.set(check)
        try:
            outcome, product = fetch(code)
        finally:
            _ACTIVE_SOURCE_CHECK.reset(token)
        check["outcome"] = outcome
        if source_checks is not None:
            source_checks.append(check)
        if outcome == "found":
            found_product, found_source = product, source
            break
        if outcome == "error":
            all_missing = False

    row = cached or BarcodeProductCache(code=code)
    if found_product is None:
        # Il negativo si memorizza solo se tutte le fonti hanno risposto "non trovato".
        if all_missing:
            row.found = False
            row.name = row.brand = row.quantity_label = row.image_url = row.source = None
            row.fetched_at = now
            db.add(row)
            db.commit()
        return None

    row.found = True
    row.name = (
        found_product.get("product_name_it")
        or found_product.get("product_name")
        or found_product.get("generic_name")
        or None
    )
    row.brand = (found_product.get("brands") or "").split(",")[0].strip() or None
    row.quantity_label = found_product.get("quantity") or None
    row.image_url = found_product.get("image_front_small_url") or None
    row.source = found_source
    row.fetched_at = now
    db.add(row)
    db.commit()
    return row
