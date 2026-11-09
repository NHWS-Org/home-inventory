import base64
from datetime import timedelta
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import requests
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.schema import CreateTable

from backup_archive import create_backup_archive, read_backup_archive
from dependencies import get_db
from models import (
    Base, DeviceSession, Inventory, Item, Notification, NotificationEvent, NotificationPreference,
    PushDelivery, PushSubscription, Role, SharedInventory, User,
)
from notification_contracts import InventoryUpdatedData
from notification_outbox import claim_event, enqueue_event, process_claim, utcnow
from push_config import PushConfigurationError, load_push_config
from routes.auth import create_access_token, router as auth_router
from routes.backup import RestoreRequest, _restore_backup_rows
from routes.notifications import router
import web_push as push


def encoded(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def write_key(path):
    key = ec.generate_private_key(ec.SECP256R1())
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    return key


@pytest.fixture
def setup(tmp_path, monkeypatch):
    path = tmp_path / "vapid.pem"
    write_key(path)
    monkeypatch.setenv("WEB_PUSH_ENABLED", "true")
    monkeypatch.setenv("WEB_PUSH_VAPID_PRIVATE_KEY_FILE", str(path))
    monkeypatch.setenv("WEB_PUSH_VAPID_SUBJECT", "mailto:admin@example.com")
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    before = utcnow() - timedelta(minutes=1)
    with factory.begin() as db:
        db.add_all([Role(id=1, name="moderator"), Role(id=2, name="viewer")])
        db.flush()
        db.add_all([User(id=i, username=f"user{i}", role_id=1) for i in (1, 2, 3)])
        db.flush()
        db.add(Inventory(id=1, name="Private list name", type="CHECKLIST", owner_id=1))
        db.flush()
        db.add_all([
            SharedInventory(inventory_id=1, user_id=2),
            NotificationPreference(
                user_id=2, event_type="inventory_updated", in_app_enabled=True, push_enabled=True,
                data_ins=before, data_mod=before,
            ),
            *[DeviceSession(
                id=i, session_token_id=f"session-{i}", user_id=i,
                created_at=before, expires_at=utcnow() + timedelta(days=1),
            ) for i in (1, 2, 3)],
        ])
    app = FastAPI()
    app.include_router(router, prefix="/notifications")
    app.include_router(auth_router, prefix="/auth")

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    public = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    )
    payload = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/private-endpoint",
        "keys": {"p256dh": encoded(public), "auth": encoded(b"0123456789abcdef")},
        "consent": True, "expirationTime": None,
    }
    headers = {
        i: {"Authorization": "Bearer " + create_access_token({
            "sub": f"user{i}", "jti": f"session-{i}",
        })} for i in (1, 2, 3)
    }
    yield SimpleNamespace(
        factory=factory, client=TestClient(app), headers=headers, payload=payload,
        path=path, engine=engine,
    )
    engine.dispose()


def subscribe(setup, **changes):
    response = setup.client.post(
        "/notifications/push/subscriptions", headers=setup.headers[2],
        json={**setup.payload, **changes},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def queued(setup):
    subscription_id = subscribe(setup)
    with setup.factory.begin() as db:
        record = enqueue_event(db, InventoryUpdatedData(inventory_id=1, changed_fields=["name"]), actor_id=1)
        db.flush()
        event_id = record.id
    claim = claim_event(setup.factory)
    assert process_claim(setup.factory, claim)
    with setup.factory() as db:
        row = db.scalar(select(PushDelivery))
        assert row is not None
        return subscription_id, row.id, event_id


def delivery(setup, delivery_id):
    with setup.factory() as db:
        return db.get(PushDelivery, delivery_id)


def test_vapid_is_persistent_derived_and_never_generated(setup, monkeypatch):
    first = load_push_config()
    assert load_push_config().public_key == first.public_key
    assert "private" not in repr(first)
    assert len(push.decode_key(first.public_key, 65)) == 65
    response = setup.client.get("/notifications/push/config", headers=setup.headers[2])
    assert response.json() == {
        "public_key": first.public_key, "payload_mode": "detailed", "ttl_seconds": 300,
    }
    write_key(setup.path)
    assert load_push_config().fingerprint != first.fingerprint
    monkeypatch.setenv("WEB_PUSH_ENABLED", "false")
    assert load_push_config() is None
    assert setup.client.get("/notifications/push/config", headers=setup.headers[2]).status_code == 503
    monkeypatch.setenv("WEB_PUSH_ENABLED", "true")
    setup.path.unlink()
    with pytest.raises(PushConfigurationError, match="Cannot read"):
        load_push_config()
    assert not setup.path.exists()


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/fcm/send/a", "https://127.0.0.1/push",
    "https://localhost/push", "https://169.254.169.254/latest",
    "https://fcm.googleapis.com.attacker.example/push",
    "https://attacker.example/fcm/send/a",
    "https://user@fcm.googleapis.com/fcm/send/a",
    "https://fcm.googleapis.com:444/fcm/send/a",
    "https://fcm.googleapis.com./fcm/send/a",
    "https://fcm.googleapis.com\\@attacker.example/push",
    "//fcm.googleapis.com/fcm/send/a", "https://fcm.googleapis.com/push#x",
    "https://fcm.googleapis.com/\npush", "https://fcm.googleapis.com",
])
def test_arbitrary_endpoints_rejected_without_network(setup, endpoint):
    response = setup.client.post(
        "/notifications/push/subscriptions", headers=setup.headers[2],
        json={**setup.payload, "endpoint": endpoint},
    )
    assert response.status_code == 422


def test_subscription_requires_authenticated_session_consent_and_valid_keys(setup):
    assert setup.client.get("/notifications/push/config").status_code == 401
    for values in (
        {"consent": False}, {"consent": "true"},
        {"keys": {"p256dh": "invalid", "auth": setup.payload["keys"]["auth"]}},
        {"keys": {**setup.payload["keys"], "auth": encoded(b"short")}},
        {"expirationTime": 1}, {"expirationTime": 10**100},
        {"keys": {**setup.payload["keys"], "p256dh": encoded(b"\x04" + b"\0" * 64)}},
    ):
        assert setup.client.post(
            "/notifications/push/subscriptions", headers=setup.headers[2],
            json={**setup.payload, **values},
        ).status_code == 422
    legacy = create_access_token({"sub": "user2"})
    assert setup.client.post(
        "/notifications/push/subscriptions", headers={"Authorization": f"Bearer {legacy}"},
        json=setup.payload,
    ).status_code == 401


def test_endpoint_deduplication_cross_account_and_session_ownership(setup):
    subscription_id = subscribe(setup)
    assert subscribe(setup) == subscription_id
    assert setup.client.post(
        "/notifications/push/subscriptions", headers=setup.headers[3], json=setup.payload,
    ).status_code == 409
    assert setup.client.delete(
        f"/notifications/push/subscriptions/{subscription_id}", headers=setup.headers[3],
    ).status_code == 404
    data = setup.client.get("/notifications/push/subscriptions", headers=setup.headers[2]).json()
    assert len(data) == 1
    assert not any(key in json.dumps(data) for key in ("endpoint", "p256dh", "auth", "session_token"))
    with setup.factory.begin() as db:
        db.add(DeviceSession(
            session_token_id="other-session", user_id=2, expires_at=utcnow() + timedelta(days=1),
        ))
    other = {"Authorization": "Bearer " + create_access_token({
        "sub": "user2", "jti": "other-session",
    })}
    assert setup.client.get("/notifications/push/subscriptions", headers=other).json() == []
    assert setup.client.delete(
        f"/notifications/push/subscriptions/{subscription_id}", headers=other,
    ).status_code == 404


def test_push_and_inbox_are_independent_and_reprocessing_deduplicated(setup):
    with setup.factory.begin() as db:
        db.scalar(select(NotificationPreference)).in_app_enabled = False
    _, delivery_id, event_id = queued(setup)
    with setup.factory.begin() as db:
        assert db.scalars(select(Notification)).all() == []
        from notification_service import evaluate_event

        evaluate_event(db, db.get(NotificationEvent, event_id))
    with setup.factory() as db:
        assert len(db.scalars(select(PushDelivery)).all()) == 1
    claim = push.claim_push(setup.factory)
    assert push.claim_push(setup.factory) is None
    calls = []
    assert push.process_push(
        setup.factory, claim,
        lambda *args: calls.append(args) or push.SendResult(201),
    )
    assert len(calls) == 1
    assert "notification_event=" not in calls[0][2]["url"]
    assert delivery(setup, delivery_id).status == "accepted"
    assert delivery(setup, delivery_id).accepted_at is not None
    assert not push.process_push(setup.factory, claim, lambda *args: pytest.fail("Duplicate send"))
    status = setup.client.get("/notifications/push/deliveries", headers=setup.headers[2]).json()
    assert status[0]["status"] == "accepted"
    assert "read_at" not in status[0]
    assert setup.client.get("/notifications/push/deliveries", headers=setup.headers[3]).json() == []


@pytest.mark.parametrize("revoke_access", [False, True])
def test_deleted_item_push_respects_container_access(setup, revoke_access):
    from notification_service import emit_item_deleted
    subscribe(setup)
    with setup.factory.begin() as db:
        db.add(NotificationPreference(
            user_id=2, event_type="item_updated", in_app_enabled=True, push_enabled=True,
            data_ins=utcnow() - timedelta(minutes=1), data_mod=utcnow() - timedelta(minutes=1),
        ))
        item = Item(name="Deleted name", inventory_id=1, quantity=0)
        db.add(item)
        db.flush()
        emit_item_deleted(db, item, actor_id=1)
        db.delete(item)
    assert process_claim(setup.factory, claim_event(setup.factory))
    claim = push.claim_push(setup.factory)
    assert claim is not None
    if revoke_access:
        with setup.factory.begin() as db:
            db.query(SharedInventory).delete()
    calls = []
    assert push.process_push(setup.factory, claim, lambda *args: calls.append(args) or push.SendResult(201))
    if revoke_access:
        assert calls == []
    else:
        assert len(calls) == 1
        assert calls[0][2]["body"] == "🔴✕ Deleted name"
        assert calls[0][2]["url"].startswith("/checklists/1?notification_event=")


@pytest.mark.parametrize("change", [
    "logout", "revocation", "expiry", "block", "access", "preference", "own_action",
    "generation", "vapid", "event_expiry", "subscription_expiry", "account", "viewer",
])
def test_rechecks_every_lifecycle_gate_before_send(setup, change):
    subscription_id, delivery_id, event_id = queued(setup)
    claim = push.claim_push(setup.factory)
    if change == "logout":
        assert setup.client.post("/auth/logout", headers=setup.headers[2]).status_code == 200
    else:
        with setup.factory.begin() as db:
            if change == "revocation":
                db.get(DeviceSession, 2).revoked_at = utcnow()
            elif change == "expiry":
                db.get(DeviceSession, 2).expires_at = utcnow() - timedelta(seconds=1)
            elif change == "block":
                db.get(User, 2).is_blocked = True
            elif change == "access":
                db.query(SharedInventory).delete()
            elif change == "preference":
                db.scalar(select(NotificationPreference)).push_enabled = False
            elif change == "own_action":
                db.get(NotificationEvent, event_id).actor_id = 2
            elif change == "generation":
                db.get(PushSubscription, subscription_id).generation = "new-generation"
            elif change == "vapid":
                write_key(setup.path)
            elif change == "event_expiry":
                db.get(NotificationEvent, event_id).expires_at = utcnow() - timedelta(seconds=1)
            elif change == "subscription_expiry":
                db.get(PushSubscription, subscription_id).expires_at = utcnow() - timedelta(seconds=1)
            elif change == "account":
                db.get(DeviceSession, 2).user_id = 3
            elif change == "viewer":
                db.get(User, 2).role_id = 2
    assert push.process_push(setup.factory, claim, lambda *args: pytest.fail("Unauthorized send"))
    assert delivery(setup, delivery_id).status == "cancelled"


def test_new_session_rebind_cancels_old_queue(setup):
    _, delivery_id, _ = queued(setup)
    with setup.factory.begin() as db:
        db.add(DeviceSession(
            session_token_id="new-session", user_id=2, expires_at=utcnow() + timedelta(days=1),
        ))
    setup.headers[2] = {"Authorization": "Bearer " + create_access_token({
        "sub": "user2", "jti": "new-session",
    })}
    subscribe(setup)
    assert push.process_push(
        setup.factory, push.claim_push(setup.factory), lambda *args: pytest.fail("Obsolete send"),
    )
    assert delivery(setup, delivery_id).status == "cancelled"


def test_no_retroactive_push_after_new_consent_or_subscription(setup):
    with setup.factory.begin() as db:
        record = enqueue_event(db, InventoryUpdatedData(inventory_id=1, changed_fields=["name"]), actor_id=1)
    subscribe(setup)
    assert process_claim(setup.factory, claim_event(setup.factory))
    with setup.factory() as db:
        assert db.scalars(select(PushDelivery)).all() == []
        assert len(db.scalars(select(Notification)).all()) == 1
    with setup.factory.begin() as db:
        enqueue_event(db, InventoryUpdatedData(inventory_id=1, changed_fields=["name"]), actor_id=1)
        db.scalar(select(NotificationPreference)).data_mod = utcnow() + timedelta(seconds=1)
    assert process_claim(setup.factory, claim_event(setup.factory))
    with setup.factory() as db:
        assert db.scalars(select(PushDelivery)).all() == []
        assert len(db.scalars(select(Notification)).all()) == 2


def test_queue_age_and_disabled_installation_never_send(setup, monkeypatch):
    _, delivery_id, _ = queued(setup)
    row = delivery(setup, delivery_id)
    assert row.expires_at <= row.created_at + timedelta(days=1)
    assert push.claim_push(setup.factory, now=row.expires_at) is None
    assert delivery(setup, delivery_id).status == "cancelled"
    with setup.factory.begin() as db:
        record = db.get(PushDelivery, delivery_id)
        record.status = "pending"
        record.expires_at = utcnow() + timedelta(days=1)
    claim = push.claim_push(setup.factory)
    monkeypatch.setenv("WEB_PUSH_ENABLED", "false")
    assert push.process_push(setup.factory, claim, lambda *a: pytest.fail("Disabled push"))
    assert delivery(setup, delivery_id).status == "cancelled"


@pytest.mark.parametrize("code", [404, 410])
def test_dead_endpoints_removed_with_queued_sends(setup, code):
    subscription_id, delivery_id, _ = queued(setup)
    assert push.process_push(
        setup.factory, push.claim_push(setup.factory), lambda *args: push.SendResult(code),
    )
    with setup.factory() as db:
        assert db.get(PushSubscription, subscription_id) is None
        assert db.get(PushDelivery, delivery_id) is None


@pytest.mark.parametrize("code", [429, 500, 503])
def test_explicit_temporary_rejections_have_bounded_backoff(setup, code):
    _, delivery_id, _ = queued(setup)
    now = utcnow()
    for attempt in range(1, 6):
        claim = push.claim_push(setup.factory, now=now)
        assert claim is not None
        assert push.process_push(
            setup.factory, claim, lambda *args: push.SendResult(code, 120), now=now,
        )
        row = delivery(setup, delivery_id)
        assert row.attempts == attempt
        assert row.status == ("pending" if attempt < 5 else "failed")
        assert row.available_at >= now + timedelta(seconds=120)
        assert push.claim_push(setup.factory, now=now) is None
        now = row.available_at
    assert push.claim_push(setup.factory, now=now + timedelta(hours=1)) is None


@pytest.mark.parametrize("code", [200, 301, 302, 400, 401, 403])
def test_other_service_responses_fail_without_retry(setup, code):
    _, delivery_id, _ = queued(setup)
    assert push.process_push(
        setup.factory, push.claim_push(setup.factory), lambda *args: push.SendResult(code),
    )
    assert delivery(setup, delivery_id).status == "failed"


def test_timeout_and_crashed_lease_never_replay_or_log_credentials(setup, caplog):
    _, delivery_id, _ = queued(setup)

    def timeout(*args):
        raise requests.Timeout(setup.payload["endpoint"] + setup.payload["keys"]["auth"])

    assert not push.process_push(setup.factory, push.claim_push(setup.factory), timeout)
    assert delivery(setup, delivery_id).status == "uncertain"
    assert setup.payload["endpoint"] not in caplog.text
    assert setup.payload["keys"]["auth"] not in caplog.text
    with setup.factory.begin() as db:
        row = db.get(PushDelivery, delivery_id)
        row.status = "pending"
    now = utcnow()
    claim = push.claim_push(setup.factory, now=now)
    assert push.claim_push(setup.factory, now=now + timedelta(seconds=61)) is None
    assert delivery(setup, delivery_id).status == "uncertain"
    assert not push.process_push(setup.factory, claim, lambda *args: pytest.fail("Late send"))


def test_lease_expiring_while_waiting_for_authorization_never_sends(setup, monkeypatch):
    _, delivery_id, _ = queued(setup)
    now = utcnow()
    claim = push.claim_push(setup.factory, now=now)
    times = iter([now, now + timedelta(seconds=61)])
    monkeypatch.setattr(push, "utcnow", lambda: next(times))
    assert push.process_push(
        setup.factory, claim, lambda *args: pytest.fail("Expired lease sent"),
    )
    assert delivery(setup, delivery_id).status == "cancelled"


def test_push_click_link_identifies_only_recipients_inbox_event(setup):
    _, _, event_id = queued(setup)
    with setup.factory() as db:
        key = db.get(NotificationEvent, event_id).event_key
    calls = []
    assert push.process_push(
        setup.factory, push.claim_push(setup.factory),
        lambda *args: calls.append(args) or push.SendResult(201),
    )
    assert calls[0][2]["url"] == f"/checklists/1?notification_event={key}"


def test_standard_encryption_vapid_detailed_payload_and_transport_safety(setup, monkeypatch):
    subscription_id, _, event_id = queued(setup)
    captured = {}
    monkeypatch.setattr(push.socket, "getaddrinfo", lambda *a, **k: [
        (2, 1, 6, "", ("8.8.8.8", 443)),
    ])

    def request(self, method, url, **kwargs):
        captured.update(kwargs)
        assert not self.trust_env
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] == 10
        response = requests.Response()
        response.status_code = 201
        return response

    monkeypatch.setattr(requests.Session, "request", request)
    with setup.factory() as db:
        payload = push.notification_push_payload(db, db.get(NotificationEvent, event_id))
        result = push.send_push(db.get(PushSubscription, subscription_id), load_push_config(), payload)
    assert result.status_code == 201
    assert captured["headers"]["Authorization"].startswith("vapid ")
    assert captured["headers"]["content-encoding"] == "aes128gcm"
    assert str(captured["headers"]["ttl"]) == "300"
    assert b"Hai una nuova notifica" not in captured["data"]
    assert b"Private list name" not in captured["data"]
    # Resource details are included only inside the encrypted payload.
    def webpush_mock(**kwargs):
        assert json.loads(kwargs["data"]) == payload
        assert payload["title"] == "☑ Private list name"
        assert payload["url"] == "/checklists/1"
        response = requests.Response()
        response.status_code = 202
        return response
    monkeypatch.setattr(push, "webpush", webpush_mock)
    with setup.factory() as db:
        assert push.send_push(
            db.get(PushSubscription, subscription_id), load_push_config(), payload,
        ).status_code == 202


def test_detailed_push_identifies_resource_item_action_and_bounds_unicode(setup):
    from models import Item
    from notification_contracts import ItemQuantityChangedData
    with setup.factory.begin() as db:
        inventory = db.get(Inventory, 1)
        inventory.name = "Dispensa"
        inventory.type = "INVENTORY"
        item = Item(name="Riso", inventory_id=1, quantity=3)
        db.add(item)
        db.flush()
        record = enqueue_event(db, ItemQuantityChangedData(
            inventory_id=1, item_id=item.id, previous_quantity=2, quantity=3,
        ), actor_id=1)
        payload = push.notification_push_payload(db, record)
        assert payload["title"] == "📦 Dispensa"
        assert payload["body"] == "🟢↑ Riso · +1 (2 → 3)"
        assert payload["url"] == "/inventories/1"
        inventory.type = "CHECKLIST"
        assert push.notification_push_payload(db, record)["body"] == "🟢✓ Riso · Completato"
        record.payload = {
            "event_type": "item_updated", "inventory_id": 1, "item_id": item.id,
            "changed_fields": ["description", "name"],
            "details": {"description": "Una confezione", "name": "Riso integrale"},
        }
        assert "Descrizione: Una confezione · Titolo: Riso integrale" in push.notification_push_payload(db, record)["body"]
        inventory.name = "😀" * 300
        item.name = "😀" * 700
        payload = push.notification_push_payload(db, record)
        assert len(payload["title"]) <= 40
        assert len(payload["body"]) <= 500
        assert len(json.dumps(payload, ensure_ascii=False).encode()) < 3500


@pytest.mark.parametrize("kind,event,body", [
    ("INVENTORY", {"event_type": "item_updated", "operation": "created", "quantity": 0}, "🟢＋ Riso · ×0"),
    ("INVENTORY", {"event_type": "item_updated", "operation": "deleted"}, "🔴✕ Riso"),
    ("INVENTORY", {"event_type": "item_updated"}, "🟡✎ Riso · Titolo: Riso"),
    ("INVENTORY", {"event_type": "item_quantity_changed", "previous_quantity": 1, "quantity": 2}, "🟢↑ Riso · +1 (1 → 2)"),
    ("INVENTORY", {"event_type": "item_quantity_changed", "previous_quantity": 2, "quantity": 1}, "🔴↓ Riso · -1 (2 → 1)"),
    ("CHECKLIST", {"event_type": "item_quantity_changed", "previous_quantity": 0, "quantity": 1}, "🟢✓ Riso · Completato"),
    ("CHECKLIST", {"event_type": "item_quantity_changed", "previous_quantity": 1, "quantity": 0}, "🔴↶ Riso · Da fare"),
])
def test_push_compact_operation_symbols_match_inbox(setup, kind, event, body):
    from notification_contracts import notification_event_adapter
    with setup.factory.begin() as db:
        db.get(Inventory, 1).type = kind
        item = Item(name="Riso", inventory_id=1, quantity=1)
        db.add(item)
        db.flush()
        data = {"inventory_id": 1, **event}
        if event.get("operation") != "deleted":
            data["item_id"] = item.id
        if event["event_type"] == "item_updated":
            data.update(changed_fields=["name"], details={"name": "Riso"})
        record = enqueue_event(db, notification_event_adapter.validate_python(data), actor_id=1)
        payload = push.notification_push_payload(db, record)
        assert payload["body"] == body
        assert "Nuovo elemento" not in body
        assert "Quantità:" not in body


def test_transport_rejects_private_dns_and_redirect_following(monkeypatch):
    monkeypatch.setattr(push.socket, "getaddrinfo", lambda *a, **k: [
        (2, 1, 6, "", ("127.0.0.1", 443)),
    ])
    with push.SafePushSession() as transport:
        assert isinstance(transport.get_adapter("https://fcm.googleapis.com"), push.SafePushAdapter)
        with pytest.raises(ValueError, match="public"):
            push.SafeHTTPSConnection("fcm.googleapis.com", port=443)._new_conn()
        with pytest.raises(ValueError, match="consentito"):
            transport.post("https://attacker.example/push")


def test_dns_pinning_preserves_tls_host_and_uses_only_validated_public_ip(monkeypatch):
    monkeypatch.setattr(push.socket, "getaddrinfo", lambda *a, **k: [
        (2, 1, 6, "", ("8.8.8.8", 443)),
    ])
    captured = []
    sentinel = object()
    monkeypatch.setattr(push, "create_connection", lambda address, *a, **k: captured.append(address) or sentinel)
    connection = push.SafeHTTPSConnection("fcm.googleapis.com", port=443, timeout=10)
    assert connection._new_conn() is sentinel
    assert connection.host == "fcm.googleapis.com"
    assert captured == [("8.8.8.8", 443)]


def test_logical_backup_excludes_credentials_and_restore_clears_existing_push(setup, tmp_path):
    queued(setup)
    path = tmp_path / "push.hibackup"
    with setup.factory() as db:
        create_backup_archive(db, path, {
            "format": "home-inventory-backup-v3", "format_version": 1,
            "db_alembic_version": "f8a9b0c1d2e3",
        })
    _, rows = read_backup_archive(path)
    assert "push_subscriptions" not in rows
    assert "push_deliveries" not in rows
    from backup_comparison import _field_value, REDACTED

    for field in ("endpoint", "p256dh", "auth"):
        assert _field_value("push_subscriptions", field, "private-value") == REDACTED
    with setup.factory.begin() as db:
        _restore_backup_rows(
            db, {"push_subscriptions": [{"endpoint": setup.payload["endpoint"]}]},
            RestoreRequest(confirm=True), {},
        )
    with setup.factory() as db:
        assert db.scalars(select(PushSubscription)).all() == []
        assert db.scalars(select(PushDelivery)).all() == []


def test_unsubscribe_and_session_cleanup_cascade_queue(setup):
    subscription_id, delivery_id, _ = queued(setup)
    assert setup.client.delete(
        f"/notifications/push/subscriptions/{subscription_id}", headers=setup.headers[2],
    ).status_code == 200
    assert delivery(setup, delivery_id) is None
    subscription_id = subscribe(setup)
    with setup.factory.begin() as db:
        db.delete(db.get(DeviceSession, 2))
    with setup.factory() as db:
        assert db.get(PushSubscription, subscription_id) is None


def test_migration_matches_models_from_existing_database_and_bootstrap():
    engine = create_engine("sqlite://")
    tables = [
        table for table in Base.metadata.sorted_tables
        if table.name not in {"push_subscriptions", "push_deliveries"}
    ]
    Base.metadata.create_all(engine, tables=tables)
    revision = importlib.import_module("migrations.versions.f8a9b0c1d2e3_web_push")
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            revision.upgrade()
            revision.upgrade()
        assert compare_metadata(context, Base.metadata) == []
        with Operations.context(context):
            revision.downgrade()
            revision.upgrade()
        assert compare_metadata(context, Base.metadata) == []
    engine.dispose()


@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect(), mysql.dialect()])
def test_push_tables_compile_on_supported_databases(dialect):
    for model in (PushSubscription, PushDelivery):
        assert str(CreateTable(model.__table__).compile(dialect=dialect))


def test_offline_reset_cli_and_restore_rollback(setup, tmp_path):
    _, delivery_id, _ = queued(setup)
    with setup.factory() as db:
        _restore_backup_rows(db, {}, RestoreRequest(confirm=True), {})
        db.rollback()
    assert delivery(setup, delivery_id) is not None
    url = f"sqlite:///{tmp_path / 'offline.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with setup.factory() as db:
        with engine.begin() as connection:
            for model in (Role, User, Inventory, DeviceSession, NotificationEvent, PushSubscription, PushDelivery):
                rows = [dict(row) for row in db.execute(select(model.__table__)).mappings()]
                if rows:
                    connection.execute(model.__table__.insert(), rows)
    result = subprocess.run(
        [sys.executable, "-m", "notification_worker", "--reset-push"],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "DATABASE_TYPE": "SQLITE", "DATABASE_URL": url},
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "1 deliveries, 1 subscriptions removed" in result.stderr
    with engine.connect() as connection:
        assert connection.execute(select(PushSubscription)).all() == []
        assert connection.execute(select(PushDelivery)).all() == []
        assert len(connection.execute(select(NotificationEvent)).all()) == 1
        assert len(connection.execute(select(Inventory)).all()) == 1
    engine.dispose()
