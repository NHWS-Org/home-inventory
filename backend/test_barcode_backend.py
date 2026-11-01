import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import barcode_service
from barcode_service import is_valid_gtin, normalize_code
from database import Base
from dependencies import get_db
from main import app
from models import BarcodeProductCache, Inventory, Item, Role, User
from routes.auth import get_current_user


@pytest.fixture
def ctx():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = Session()
    admin_role = Role(name="admin")
    viewer_role = Role(name="viewer")
    db.add_all([admin_role, viewer_role])
    db.commit()
    admin = User(username="admin", hashed_password="x", role_id=admin_role.id)
    viewer = User(username="viewer", hashed_password="x", role_id=viewer_role.id)
    db.add_all([admin, viewer])
    db.commit()
    inv_a = Inventory(name="A", type="INVENTORY", owner_id=admin.id)
    inv_b = Inventory(name="B", type="INVENTORY", owner_id=admin.id)
    db.add_all([inv_a, inv_b])
    db.commit()
    state = {"user_id": admin.id}

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    def override_user():
        session = Session()
        try:
            yield session.get(User, state["user_id"])
        finally:
            session.close()

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    yield {
        "client": TestClient(app),
        "db": db,
        "inv_a": inv_a.id,
        "inv_b": inv_b.id,
        "viewer_id": viewer.id,
        "state": state,
    }
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)
    db.close()


def _create_item(client, inventory_id, name="Latte", barcodes=None):
    payload = {"name": name, "quantity": 1, "inventory_id": inventory_id}
    if barcodes is not None:
        payload["barcodes"] = barcodes
    response = client.post("/item/", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_normalize_and_gtin():
    assert normalize_code(" 036000291452 ") == "0036000291452"
    assert normalize_code("4006381333931") == "4006381333931"
    assert normalize_code(" https://x.y/z ") == "https://x.y/z"
    assert is_valid_gtin("4006381333931")
    assert not is_valid_gtin("4006381333932")
    assert not is_valid_gtin("abc")


def test_multiple_barcodes_per_item_and_lookup(ctx):
    client = ctx["client"]
    item = _create_item(client, ctx["inv_a"], barcodes=[{"code": "4006381333931", "format": "ean_13"}])
    assert [b["code"] for b in item["barcodes"]] == ["4006381333931"]

    response = client.post(f"/item/{item['id']}/barcodes", json={"code": "QR-ABC-1", "format": "qr_code"})
    assert response.status_code == 201
    barcode_id = response.json()["id"]

    assert len(client.get(f"/item/{item['id']}").json()["barcodes"]) == 2
    listed = client.get(f"/item/{ctx['inv_a']}".replace("/item/", "/inventory/item/") + "/").json()
    assert len(listed[0]["barcodes"]) == 2

    for code in ("4006381333931", "QR-ABC-1"):
        found = client.get("/barcode/lookup", params={"code": code, "external": False}).json()
        assert [m["item_id"] for m in found["matches"]] == [item["id"]]

    assert client.delete(f"/item/{item['id']}/barcodes/{barcode_id}").status_code == 200
    found = client.get("/barcode/lookup", params={"code": "QR-ABC-1", "external": False}).json()
    assert found["matches"] == []


def test_upca_scan_matches_ean13(ctx):
    client = ctx["client"]
    item = _create_item(client, ctx["inv_a"], barcodes=[{"code": "0036000291452"}])
    found = client.get("/barcode/lookup", params={"code": "036000291452", "external": False}).json()
    assert [m["item_id"] for m in found["matches"]] == [item["id"]]


def test_conflict_within_inventory_but_not_across(ctx):
    client = ctx["client"]
    first = _create_item(client, ctx["inv_a"], barcodes=[{"code": "111"}])
    other = _create_item(client, ctx["inv_a"], name="Altro")

    conflict = client.post(f"/item/{other['id']}/barcodes", json={"code": "111"})
    assert conflict.status_code == 409
    assert "Latte" in conflict.json()["detail"]

    dup = client.post("/item/", json={"name": "X", "quantity": 1, "inventory_id": ctx["inv_a"], "barcodes": [{"code": "111"}]})
    assert dup.status_code == 409

    in_other_inventory = _create_item(client, ctx["inv_b"], name="Latte B", barcodes=[{"code": "111"}])
    both = client.get("/barcode/lookup", params={"code": "111", "external": False}).json()
    assert {m["item_id"] for m in both["matches"]} == {first["id"], in_other_inventory["id"]}
    scoped = client.get("/barcode/lookup", params={"code": "111", "inventory_id": ctx["inv_b"], "external": False}).json()
    assert [m["item_id"] for m in scoped["matches"]] == [in_other_inventory["id"]]

    move = client.patch(
        f"/item/{in_other_inventory['id']}",
        json={"name": "Latte B", "description": None, "quantity": 1, "inventory_id": ctx["inv_a"]},
    )
    assert move.status_code == 409


def test_same_item_duplicate_and_idempotent_create(ctx):
    client = ctx["client"]
    item = _create_item(client, ctx["inv_a"], barcodes=[{"code": "222"}, {"code": " 222 "}])
    assert len(item["barcodes"]) == 1
    assert client.post(f"/item/{item['id']}/barcodes", json={"code": "222"}).status_code == 409


def test_lookup_hides_inaccessible_items(ctx):
    client = ctx["client"]
    _create_item(client, ctx["inv_a"], barcodes=[{"code": "333"}])
    ctx["state"]["user_id"] = ctx["viewer_id"]
    found = client.get("/barcode/lookup", params={"code": "333", "external": False}).json()
    assert found["matches"] == []


def test_history_records_barcode_changes(ctx):
    client = ctx["client"]
    item = _create_item(client, ctx["inv_a"])
    client.post(f"/item/{item['id']}/barcodes", json={"code": "444"})
    history = client.get(f"/item/{item['id']}/history").json()
    assert any("barcodes" in (h.get("diff") or "") for h in history)


def test_external_lookup_uses_and_fills_cache(ctx, monkeypatch):
    client = ctx["client"]
    calls = []

    def fake_fetch(base_url, code):
        calls.append(base_url)
        return "found", {"product_name": "Nutella", "brands": "Ferrero, Altro", "quantity": "400 g"}

    monkeypatch.setattr(barcode_service, "_fetch_product", fake_fetch)
    code = "4006381333931"
    first = client.get("/barcode/lookup", params={"code": code}).json()
    assert first["product"]["name"] == "Nutella"
    assert first["product"]["brand"] == "Ferrero"
    second = client.get("/barcode/lookup", params={"code": code}).json()
    assert second["product"]["name"] == "Nutella"
    assert len(calls) == 1
    assert ctx["db"].get(BarcodeProductCache, code).found


def test_external_lookup_negative_cache_only_when_all_missing(ctx, monkeypatch):
    client = ctx["client"]
    monkeypatch.setattr(barcode_service, "_fetch_product", lambda b, c: ("error", None))
    code = "4006381333931"
    assert client.get("/barcode/lookup", params={"code": code}).json()["product"] is None
    assert ctx["db"].get(BarcodeProductCache, code) is None

    monkeypatch.setattr(barcode_service, "_fetch_product", lambda b, c: ("missing", None))
    assert client.get("/barcode/lookup", params={"code": code}).json()["product"] is None
    assert ctx["db"].get(BarcodeProductCache, code).found is False


def test_external_lookup_skipped_for_non_gtin_and_when_disabled(ctx, monkeypatch):
    client = ctx["client"]

    def boom(*args):
        raise AssertionError("rete non deve essere usata")

    monkeypatch.setattr(barcode_service, "_fetch_product", boom)
    assert client.get("/barcode/lookup", params={"code": "QR-XYZ"}).json()["product"] is None
    monkeypatch.setenv("BARCODE_LOOKUP_ENABLED", "false")
    assert client.get("/barcode/lookup", params={"code": "4006381333931"}).json()["product"] is None


def test_isbn_normalization():
    assert normalize_code("0-14-032872-6") == "9780140328721"
    assert normalize_code("0140328726") == "9780140328721"
    assert normalize_code("978-0-14-032872-1") == "9780140328721"
    assert normalize_code("080442957X") == "9780804429573"
    # 10 cifre con checksum ISBN errato: resta invariato
    assert normalize_code("0140328727") == "0140328727"


def test_pharma_codes():
    gtin13 = "8033784590018"
    assert is_valid_gtin(gtin13)
    datamatrix = f"0{gtin13}" "17270630" "10LOT42" "\x1d" "21SERIAL123"
    assert normalize_code("01" + datamatrix[:14] + datamatrix[14:]) == gtin13
    assert normalize_code("]d2" + "01" + datamatrix[:14] + datamatrix[14:]) == gtin13
    # il solo GTIN con AI 01, senza altri dati, non e' un DataMatrix e resta com'e'
    assert normalize_code("01" + f"0{gtin13}") == "01" + f"0{gtin13}"
    # AIC a 9 cifre invariato
    assert normalize_code("024402051") == "024402051"


def test_book_lookup_uses_open_library(ctx, monkeypatch):
    client = ctx["client"]
    calls = []

    def fake_book(base_url, code):
        calls.append(code)
        return "found", {"product_name": "Fantastic Mr. Fox", "brands": "Roald Dahl", "quantity": "Puffin"}

    def boom(*args):
        raise AssertionError("Open * Facts non va interrogato per gli ISBN")

    monkeypatch.setattr(barcode_service, "_fetch_book", fake_book)
    monkeypatch.setattr(barcode_service, "_fetch_product", boom)
    data = client.get("/barcode/lookup", params={"code": "0140328726"}).json()
    assert data["code"] == "9780140328721"
    assert data["product"]["name"] == "Fantastic Mr. Fox"
    assert data["product"]["brand"] == "Roald Dahl"
    assert data["product"]["source"] == "openlibrary"
    assert calls == ["9780140328721"]


def test_fetch_book_maps_open_library_payload(monkeypatch):
    import io
    import json

    payload = {"ISBN:9780140328721": {
        "title": "Fantastic Mr. Fox", "subtitle": "una storia",
        "authors": [{"name": "Roald Dahl"}, {"name": "Q. Blake"}],
        "publishers": [{"name": "Puffin"}], "cover": {"small": "http://x/s.jpg"},
    }}
    monkeypatch.setattr(
        barcode_service.urllib.request, "urlopen",
        lambda *a, **k: io.BytesIO(json.dumps(payload).encode()),
    )
    outcome, book = barcode_service._fetch_book("https://openlibrary.org", "9780140328721")
    assert outcome == "found"
    assert book == {
        "product_name": "Fantastic Mr. Fox: una storia", "brands": "Roald Dahl & Q. Blake",
        "quantity": "Puffin", "image_front_small_url": "http://x/s.jpg",
    }
    monkeypatch.setattr(barcode_service.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"{}"))
    assert barcode_service._fetch_book("https://openlibrary.org", "9780140328721") == ("missing", None)


def test_book_lookup_falls_back_to_google_books(ctx, monkeypatch):
    client = ctx["client"]
    monkeypatch.setattr(barcode_service, "_fetch_book", lambda b, c: ("missing", None))
    monkeypatch.setattr(
        barcode_service, "_fetch_google_book",
        lambda c: ("found", {"product_name": "Libro IT", "brands": "Autore", "quantity": "Editore"}),
    )
    data = client.get("/barcode/lookup", params={"code": "9788893094955"}).json()
    assert data["product"]["name"] == "Libro IT"
    assert data["product"]["source"] == "googlebooks"


def test_book_lookup_google_error_is_not_negative_cached(ctx, monkeypatch):
    client = ctx["client"]
    monkeypatch.setattr(barcode_service, "_fetch_book", lambda b, c: ("missing", None))
    monkeypatch.setattr(barcode_service, "_fetch_google_book", lambda c: ("error", None))
    code = "9788893094955"
    assert client.get("/barcode/lookup", params={"code": code}).json()["product"] is None
    assert ctx["db"].get(BarcodeProductCache, code) is None


def test_fetch_google_book_maps_payload(monkeypatch):
    import io
    import json

    payload = {"items": [{"volumeInfo": {
        "title": "Titolo", "subtitle": "sotto", "authors": ["A", "B"], "publisher": "Ed",
        "imageLinks": {"smallThumbnail": "http://x/t.jpg"},
    }}]}
    seen = {}

    def fake_urlopen(request, **kwargs):
        seen["url"] = request.full_url
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "k123")
    monkeypatch.setattr(barcode_service.urllib.request, "urlopen", fake_urlopen)
    outcome, book = barcode_service._fetch_google_book("9788893094955")
    assert outcome == "found"
    assert "isbn%3A9788893094955" in seen["url"] and "key=k123" in seen["url"]
    assert book == {
        "product_name": "Titolo: sotto", "brands": "A & B", "quantity": "Ed",
        "image_front_small_url": "https://x/t.jpg",
    }
    monkeypatch.setattr(barcode_service.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"{}"))
    assert barcode_service._fetch_google_book("9788893094955") == ("missing", None)
