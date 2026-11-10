## 2026-11-06 - [Eager Load Inventory Shares in Audit Log Filtering]
**Learning:** In `backend/routes/audit.py`, `get_item_audit_logs` and `get_inventory_audit_logs` evaluated `can_access_inventory(current_user, inv, action="view")` across `all_inventories` for non-admin users. Because `Inventory.shared_with_users` and `Inventory.shared_with_groups` were not eager loaded, checking N inventories fired 2 * N lazy-load queries (e.g., 35 queries for 15 inventories).
**Action:** Always eager load `joinedload(Inventory.shared_with_users)` and `joinedload(Inventory.shared_with_groups)` whenever querying `Inventory` lists that will be passed to `can_access_inventory()` to maintain constant O(1) query counts.

## 2026-11-06 - [Batch Item Assignment Lookups to Fix N+1 in Item Listing]
**Learning:** In `backend/routes/inventory.py`, `_list_item_assignment_fields` accessed `len(item.source_assignments)` for standard inventory items and `assignment.source_item.inventory` for checklist items during response serialization, triggering unbatched lazy load queries for every item in the inventory (N queries).
**Action:** Pre-calculate assignment counts using a batched `GROUP BY ListAssignment.source_item_id` query, and chain `joinedload(Item.list_assignment).joinedload(ListAssignment.source_item).joinedload(Item.inventory)` in `list_items_base` to keep database query counts constant O(1).

## 2025-05-18 - [Batch Item Version Queries to Fix N+1]
**Learning:** In `backend/routes/inventory.py`, `_current_item_version_num` was called per item inside response serialisation loops in `list_inventories_base` and `list_items_base`, executing 1 query per item.
**Action:** Use a batched SQLAlchemy `GROUP BY ItemVersion.item_id` query filtered by `item_id.in_(...)` to fetch item versions in 1 query for all items.
