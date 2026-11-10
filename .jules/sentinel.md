# Sentinel Security Journal

## 2025-02-23 - Path Traversal in Backup File Management Routes
**Vulnerability:** Backup management routes (`download`, `delete`, `restore`, `upload`, `delete-bulk`) in `backend/routes/backup.py` accepted raw filename path parameters directly concatenated with `BACKUP_DIR`. Path traversal payloads such as `../../.env` allowed downloading, deleting, or overwriting files outside the intended backup directory.
**Learning:** File management endpoints that take user-controlled filenames as route parameters or payload properties can expose sensitive files if path resolution is not strictly restricted to the target directory.
**Prevention:** Always validate filenames against path traversal characters (`/`, `\`, `..`), enforce expected file extensions, and resolve paths using `Path.resolve()` verifying that the resolved path is relative to the designated base directory before performing filesystem operations.

## 2025-05-18 - Unenforced Account Blocking in Login/Me Endpoints & Self-Block Runtime Exception
**Vulnerability:** Blocked users (`is_blocked = True`) were issued valid JWT access tokens upon logging in via `/auth/login` and could query `/auth/me`. Additionally, `/user/users/{user_id}/block` called `role_required(RoleEnum.admin).id`, causing an `AttributeError` at runtime and preventing self-blocking validation.
**Learning:** Checking `is_blocked` only inside a generic `get_current_user` dependency leaves unauthenticated or custom auth endpoints (`/login`, `/me`) vulnerable if they do not explicitly check user block status or use `get_current_user`.
**Prevention:** Always check `user.is_blocked` during primary login authentication and profile queries, and use `Depends(role_required(RoleEnum.admin))` directly to obtain current user info in admin endpoints.

## 2025-05-19 - Administrative Lockout via Unchecked Last-Admin Role Demotion or Blocking
**Vulnerability:** User role update (`PUT /user/users/{user_id}`, `PUT /admin/users/{user_id}/role/`, `POST /user/users/{user_id}/role/{role_id}`) and user blocking endpoints allowed demoting or blocking the last active enabled administrator. This created a denial-of-administration scenario where 0 active admins remained.
**Learning:** Endpoints that mutate user roles or status must check total system active admin count before permitting changes that revoke admin access.
**Prevention:** Always validate that at least one active, unblocked admin user remains before executing role demotion, account blocking, or deletion operations.

## 2025-05-20 - Broken Object Level Authorization (IDOR) in Filter Template Management
**Vulnerability:** Unbound filter templates (`inventory_id = None`) could be retrieved by any authenticated user via `GET /filter-templates/{id}` or `GET /filter-templates` regardless of `is_shared` or owner status, exposing private filter criteria.
**Learning:** Checking inventory-level access controls when `inventory_id` is present is insufficient if resources can also exist independently without an associated inventory container.
**Prevention:** Always enforce both container-level permissions (if linked) and resource-level access control (`is_shared`, `user_ins == current_user`, or admin role) sequentially on read and list endpoints.

## 2025-05-21 - Router-Level Over-Restriction and Missing IDOR Checks in Shareable Users Endpoint
**Vulnerability:** `GET /user/users/shareable/{inventory_id}` was blocked for non-admin moderators due to `role_required(RoleEnum.admin)` attached at the `user.py` `APIRouter` constructor. In addition, the route handler lacked an object-level authorization check (`can_access_inventory`), exposing shareable user lists for arbitrary inventory IDs to any user who could access the route.
**Learning:** Applying router-level role requirements (`dependencies=[Depends(role_required(...))]`) on mixed routers blocks sub-routes intended for multi-role functionality. Furthermore, context-dependent endpoints must explicitly enforce object-level authorization on target resources.
**Prevention:** Isolate admin-only endpoints into dedicated subrouters, and ensure all endpoints operating on specific resources validate user permissions against those resources (`can_access_inventory`).

## 2025-05-22 - Information Disclosure in Filter Template Scope Preview
**Vulnerability:** Filter template scope preview endpoints (`GET /filter-templates/scope-preview` and `GET /filter-templates`) evaluated metadata definition assignments against `db.query(Inventory).all()` without filtering by user access, leaking names and IDs of private inventories belonging to other users.
**Learning:** Helper functions that compute scope or compatibility metrics across system-wide resources can bypass object-level authorization if they query all containers without contextual user filtering.
**Prevention:** Always filter system-wide container lists using `can_access_inventory(user, container, action="view")` before including resource summaries or scope metadata in responses returned to non-admin users.

## 2025-05-23 - Broken Object-Level Authorization and Missing Multi-Tenant Filtering in Inventory Audit Logs
**Vulnerability:** In `GET /audit/logs/inventories`, non-admin query results were filtered solely by `InventoryVersion.owner_id == current_user.id`. This bypassed object-level authorization rules: users with valid shared access (direct or via group associations) could not view audit logs for shared inventories, and any change in inventory ownership or access model caused discrepancies with item audit logs.
**Learning:** Filtering audit history solely by static `owner_id` fields instead of dynamic object-level authorization checks (`can_access_inventory`) breaks the shared inventory authorization model.
**Prevention:** Consistently use the centralized authorization function `can_access_inventory(user, inventory, action="view")` across all audit log and historical query endpoints for container-level resources.

## 2026-11-02 - Missing Destination Authorization Check in Item Relocation (IDOR / Unauthorized Inventory Transfer)
**Vulnerability:** In `PATCH /item/{item_id}`, users updating an item's `inventory_id` were only verified against the item's current inventory. The endpoint did not verify that the target destination inventory existed or that the user had `edit` permissions on the destination inventory, allowing users to inject or relocate items into other users' private inventories.
**Learning:** When moving a resource between containers (e.g. moving an item between inventories), verifying permissions on the source container only is insufficient; the user must also be authorized to create/edit within the destination container.
**Prevention:** Whenever an entity transfer or parent reassociation is performed, explicitly validate that the target container exists and that the user possesses `edit` permissions on the target (`can_access_inventory(user, target_inventory, action="edit")`) before committing the reassignment.

## 2026-11-03 - Credential Leakage via Permissive CORS Wildcard Reflection
**Vulnerability:** In `backend/main.py`, `CORSMiddleware` was configured with `allow_origins=["*"]` and `allow_credentials=True`. Starlette's CORS middleware responded to arbitrary origins by reflecting back the requested origin (`Access-Control-Allow-Origin: <origin>`) with `Access-Control-Allow-Credentials: true`, permitting unauthorized cross-origin websites to make authenticated requests and read responses.
**Learning:** Configuring wildcard origins (`allow_origins=["*"]`) alongside `allow_credentials=True` bypasses standard CORS restrictions because middleware reflects arbitrary origins dynamically rather than sending literal `*`.
**Prevention:** Always restrict `allow_origins` to an explicit whitelist of trusted origins (or configurable via environment variables such as `CORS_ORIGINS`) and never combine wildcard origins with `allow_credentials=True`.

## 2026-11-04 - Broken Authorization and Cross-Type Disclosure in Deleted Inventory History Endpoints
**Vulnerability:** In `GET /inventory/{inventory_id}/history` and `GET /checklist/{inventory_id}/history`, when querying history for a deleted container (`not inv`), queries did not filter `InventoryVersion` by container type, did not return 404 when no version history existed, and failed to reject users with the `viewer` role. This allowed cross-type version disclosure between checklists and inventories and unauthorized history exposure for deleted entities.
**Learning:** Historical version queries for deleted resources must strictly filter by the specific resource type (`type == "INVENTORY"` or `type == "CHECKLIST"`), return 404 when nonexistent, and enforce the same role-based restrictions (e.g. rejecting viewers) as rollback and management endpoints.
**Prevention:** Ensure audit and history fallback logic explicitly enforces type scoping, handles empty records with 404 Not Found, and consistently checks both role permissions and ownership before returning audit versions.

## 2026-11-05 - Inactive Metadata Definition Information Disclosure in Applicable Definitions Endpoint
**Vulnerability:** In `GET /metadata/applicable`, the `include_inactive` query parameter was forwarded directly to `_resolve_applicable_definitions` without role verification. While `GET /metadata/definitions` restricted inactive definition visibility to admins (`user.role.name == RoleEnum.admin.value`), `GET /metadata/applicable` allowed any user with view access to an inventory to view deactivated metadata definitions by passing `include_inactive=true`.
**Learning:** Reusable query helpers that accept administrative flags (such as `include_inactive`) must have role-based constraints consistently applied across all calling endpoints, not just primary listing routes.
**Prevention:** Whenever a query parameter allows exposing soft-deleted or inactive entities, enforce defense-in-depth authorization by checking the user's role and restricting the parameter to administrators only (`effective_include_inactive = include_inactive if user.role.name == RoleEnum.admin.value else False`).

## 2026-11-06 - Missing Source Item Authorization Check in List Assignment Update and Deletion (IDOR)
**Vulnerability:** In `PATCH /assignment/{assignment_id}` and `DELETE /assignment/{assignment_id}`, permission checks verified only that the user had edit permissions on the associated checklist row (`can_access_item(user, assignment.list_item, action="edit")`). Neither endpoint verified that the user had permissions on the linked inventory source item (`can_access_item(user, assignment.source_item, action="view")`), allowing users whose access to the source inventory was revoked (or who managed a checklist item pointing to an unauthorized inventory) to inspect available stock, manipulate reserved quantities, or release stock reservations.
**Learning:** Relational associations bridging two independent domains or containers (e.g. checklist items and inventory source items) require authorization checks across both entities on mutation and deletion, not just upon creation.
**Prevention:** Whenever mutating or deleting an entity that bridges two security boundaries, verify that the caller holds active access rights to both the target container entity and the linked source/referenced entity (`can_access_item(user, assignment.list_item, action="edit") and can_access_item(user, assignment.source_item, action="view")`).

## 2026-11-07 - Missing 404 Validation and Viewer Access Control in Deleted Item History
**Vulnerability:** In `GET /item/{item_id}/history`, when querying history for an item that is not present in the live `items` table, the route did not return a 404 Not Found if no version history existed (`not latest`), returning an empty list `[]` instead. Furthermore, unlike deleted inventory and checklist history endpoints, it failed to reject users with the `viewer` role (`user.role.name == "viewer"`), allowing viewer accounts to inspect deleted item audit history.
**Learning:** Historical version queries on individual entities must handle nonexistent records consistently by returning 404 Not Found, and align role-based permissions with container history endpoints to prevent unauthorized inspection by read-only viewers.
**Prevention:** Always verify existence of version records with a 404 check when the primary entity does not exist, and enforce consistent role limitations across all audit/history endpoints.
## 2026-11-07 - Revoked and Expired Device Session Profile Exposure in Me Endpoint
**Vulnerability:** In `GET /auth/me`, token verification decoded JWT credentials and checked `user.is_blocked`, but failed to validate the session ID (`jti`) against `DeviceSession`. As a result, tokens belonging to revoked sessions (such as after `POST /auth/logout` or `DELETE /auth/sessions/{id}`) or expired sessions continued to return authenticated user profile information (including unmasked email, username, ID, and role).
**Learning:** When stateful session tracking or token revocation is layered onto JWTs (e.g. via `jti` in a `DeviceSession` model), endpoints that manually parse tokens without using the primary authentication dependency (`get_current_user`) bypass session validity and revocation checks.
**Prevention:** Ensure all endpoints that authenticate via JWT tokens enforce session-state validation against the backing store (checking `not device_session.revoked_at` and `device_session.expires_at > now`) identically to the centralized authentication dependency.
## 2026-11-07 - Information Disclosure / ID Enumeration in Item History for Non-Existent Resources
**Vulnerability:** In `GET /item/{item_id}/history`, when querying an `item_id` that neither exists as an active `Item` nor has any historical `ItemVersion` records, the route bypassed all access control checks without raising a `404 Not Found`. It proceeded to query `ItemVersion` and returned `200 OK` with an empty array `[]`. Because existing items in unauthorized inventories return `403 Forbidden`, this discrepancy enabled an ID enumeration oracle across tenants.
**Learning:** Fallback paths in historical query endpoints designed to handle deleted resources must verify whether version records actually exist before skipping authorization; if no historical versions exist, the endpoint must return 404 rather than empty success.
**Prevention:** When implementing audit/history endpoints that handle both active and deleted resources, check if the resource or its version history exists; if neither exists, immediately raise `404 Not Found` before performing or bypassing authorization logic.
