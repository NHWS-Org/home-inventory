"""Opt-in HTTP smoke test; creates and deletes isolated fixtures on a running app."""

import argparse
from contextlib import ExitStack
import json
import os
import secrets
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import uuid


class API:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def request(self, method, path, *, token=None, body=None, form=None, expected=200):
        headers = {"User-Agent": "HomeInventory-NotificationLiveTest"}
        data = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        if form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = urlencode(form).encode()
        request = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=15) as response:
                status, content = response.status, response.read()
        except HTTPError as error:
            status, content = error.code, error.read()
        if status != expected:
            raise AssertionError(f"{method} {path}: expected {expected}, received {status}")
        return json.loads(content) if content else None

    def login(self, username, password):
        return self.request(
            "POST", "/auth/login", form={"username": username, "password": password},
        )["access_token"]


def run(api: API, username: str, password: str, timeout: float, quiet_window: float):
    passed = 0

    def check(condition, label):
        nonlocal passed
        if not condition:
            raise AssertionError(label)
        passed += 1
        print(f"PASS {passed:02}: {label}", flush=True)

    with ExitStack() as cleanup:
        admin = api.login(username, password)
        cleanup.callback(api.request, "POST", "/auth/logout", token=admin)
        spec = api.request("GET", "/openapi.json")
        check("/notifications" in spec["paths"], "live OpenAPI exposes Notifications")
        roles = api.request("GET", "/user/roles/", token=admin)
        role_ids = {row["name"]: row["id"] for row in roles}
        prefix = f"notification-live-{uuid.uuid4().hex[:12]}"

        def verify_cleanup():
            users = api.request("GET", "/user/users/", token=admin)
            inventories = api.request("GET", "/inventory/", token=admin)
            checklists = api.request("GET", "/checklist/", token=admin)
            check(
                not any(row["username"].startswith(prefix) for row in users)
                and not any(row["name"].startswith(prefix) for row in inventories + checklists),
                "temporary users, inventories and checklists removed",
            )

        cleanup.callback(verify_cleanup)

        def create_user(suffix, role):
            name, secret = f"{prefix}-{suffix}", secrets.token_urlsafe(24)
            row = api.request("POST", "/user/users/", token=admin, body={
                "username": name, "password": secret, "role_id": role_ids[role],
            })
            cleanup.callback(api.request, "DELETE", f"/user/users/{row['id']}", token=admin)
            return name, api.login(name, secret)

        _, owner = create_user("owner", "moderator")
        recipient_name, recipient = create_user("recipient", "viewer")
        _, stranger = create_user("stranger", "viewer")
        inventory = api.request(
            "POST", "/inventory/", token=owner, body={"name": prefix + "-stock"},
        )["id"]
        cleanup.callback(api.request, "DELETE", f"/inventory/{inventory}", token=admin)
        checklist = api.request(
            "POST", "/checklist/", token=owner, body={"name": prefix + "-list"},
        )["id"]
        cleanup.callback(api.request, "DELETE", f"/checklist/{checklist}", token=admin)

        def inbox(token, resource):
            rows = api.request("GET", "/notifications?limit=100", token=token)
            return [row for row in rows if row["event"]["inventory_id"] == resource]

        def expect_count(token, resource, count, label):
            deadline = time.monotonic() + timeout
            while True:
                rows = inbox(token, resource)
                if len(rows) == count:
                    check(True, label)
                    return rows
                if len(rows) > count or time.monotonic() >= deadline:
                    check(False, f"{label}: expected {count}, received {len(rows)}")
                time.sleep(0.5)

        def unchanged(token, resource, count, label):
            deadline = time.monotonic() + quiet_window
            while True:
                rows = inbox(token, resource)
                if len(rows) != count:
                    check(False, f"{label}: expected {count}, received {len(rows)}")
                if time.monotonic() >= deadline:
                    check(True, label)
                    return
                time.sleep(0.5)

        def preference(kind, enabled=True, own=True):
            return api.request("PUT", f"/notifications/preferences/{kind}", token=owner, body={
                "in_app_enabled": enabled, "include_own_actions": own,
            })

        def rule(resource, kind, recipients, threshold=None):
            payload = {
                "event_type": kind, "threshold": threshold,
                "recipients": recipients, "enabled": True,
            }
            row = api.request(
                "POST", f"/notifications/rules/{resource}", token=owner,
                body=payload, expected=201,
            )
            return row, payload

        def item(resource, name, quantity):
            return api.request("POST", "/item/", token=owner, expected=201, body={
                "name": name, "description": "Isolated live test", "quantity": quantity,
                "inventory_id": resource,
            })

        def update(row, quantity):
            api.request("PATCH", f"/item/{row['id']}", token=owner, body={
                "name": row["name"], "description": row["description"],
                "inventory_id": row["inventory_id"], "quantity": quantity,
            })

        quantity_kind = "item_quantity_changed"
        threshold_rule, payload = rule(inventory, quantity_kind, [{"kind": "owner"}], 3)
        rule_path = f"/notifications/rules/{inventory}/{threshold_rule['id']}"
        check(
            len(api.request("GET", f"/notifications/rules/{inventory}", token=owner)) == 1,
            "owner can create and list rules",
        )
        api.request("GET", f"/notifications/rules/{inventory}", token=stranger, expected=403)
        api.request("PUT", rule_path, token=stranger, body=payload, expected=403)
        check(True, "unrelated user cannot read or modify rules")
        api.request(
            "POST", f"/notifications/rules/{inventory}", token=owner,
            body={**payload, "threshold": -1}, expected=422,
        )
        check(True, "invalid negative threshold rejected")
        stock = item(inventory, "Stock", 5)
        update(stock, 2)
        unchanged(owner, inventory, 0, "own actions excluded by default")
        preference(quantity_kind)
        update(stock, 5)
        update(stock, 2)
        rows = expect_count(owner, inventory, 1, "worker delivers threshold crossing")
        check(
            rows[0]["event"]["previous_quantity"] == 5
            and rows[0]["event"]["quantity"] == 2,
            "notification contains exact 5 -> 2 payload",
        )
        update(stock, 1)
        update(stock, 1)
        unchanged(owner, inventory, 1, "below-threshold decrease and no-op do not duplicate")
        update(stock, 5)
        update(stock, 2)
        rows = expect_count(owner, inventory, 2, "recovery rearms threshold")
        notification_id = rows[0]["id"]
        read_path = f"/notifications/{notification_id}/read"
        marked = api.request("PUT", read_path, token=owner)
        repeated = api.request("PUT", read_path, token=owner)
        check(
            bool(marked["read_at"]) and marked == repeated,
            "mark-as-read persists and is idempotent",
        )
        api.request("PUT", read_path, token=stranger, expected=404)
        check(True, "other account cannot mark someone else's notification read")
        preference(quantity_kind, enabled=False)
        update(stock, 5)
        update(stock, 2)
        unchanged(owner, inventory, 2, "disabled inbox preference suppresses delivery")
        preference(quantity_kind)
        api.request("PUT", rule_path, token=owner, body={**payload, "enabled": False})
        update(stock, 5)
        update(stock, 2)
        unchanged(owner, inventory, 2, "disabled rule suppresses delivery")
        api.request("PUT", rule_path, token=owner, body=payload)

        rule(inventory, "inventory_shared", [{"kind": "event_recipient"}])
        share_path = f"/inventory/share/{inventory}/{recipient_name}"
        api.request("POST", share_path, token=owner)
        shared = expect_count(recipient, inventory, 1, "sharing notifies actual recipient")
        api.request("POST", share_path, token=owner)
        unchanged(recipient, inventory, 1, "repeated sharing does not duplicate")
        check(inbox(stranger, inventory) == [], "unrelated account has no notification")
        api.request("DELETE", share_path, token=owner)
        check(inbox(recipient, inventory) == [], "revocation hides previous inbox entry")
        api.request(
            "PUT", f"/notifications/{shared[0]['id']}/read", token=recipient, expected=404,
        )
        check(True, "revocation prevents read-by-ID")

        rule(checklist, "checklist_completed", [{"kind": "owner"}])
        preference("checklist_completed")
        first = item(checklist, "First", 0)
        second = item(checklist, "Second", 0)
        update(first, 1)
        unchanged(owner, checklist, 0, "partial checklist does not notify")
        update(second, 1)
        expect_count(owner, checklist, 1, "last check emits completion")
        update(second, 1)
        unchanged(owner, checklist, 1, "unchanged completed checklist does not duplicate")
        update(second, 0)
        update(second, 1)
        expect_count(owner, checklist, 2, "uncheck and recheck emits a new completion")
        api.request("DELETE", rule_path, token=owner)
        remaining = api.request("GET", f"/notifications/rules/{inventory}", token=owner)
        check(
            all(row["id"] != threshold_rule["id"] for row in remaining),
            "rule deletion persisted",
        )
        page = api.request("GET", "/notifications?limit=1&offset=1", token=owner)
        check(len(page) == 1, "inbox pagination accepts limit and offset")
        print(f"All {passed} checks passed; removing isolated fixtures.", flush=True)
    print("Cleanup completed; existing users, preferences and inventories unchanged.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:3000/api")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--quiet-window", type=float, default=6)
    args = parser.parse_args()
    username = os.environ.get("NOTIFICATION_TEST_USERNAME")
    password = os.environ.get("NOTIFICATION_TEST_PASSWORD")
    if not username or not password:
        parser.error("Set NOTIFICATION_TEST_USERNAME and NOTIFICATION_TEST_PASSWORD")
    if args.timeout <= 0 or args.quiet_window < 6:
        parser.error("timeout must be positive; quiet-window must be at least 6 seconds")
    run(API(args.api_url), username, password, args.timeout, args.quiet_window)


if __name__ == "__main__":
    main()
