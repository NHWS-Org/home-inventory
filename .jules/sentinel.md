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
