## 2026-11-06 - [Batch Item Assignment Lookups to Fix N+1 in Item Listing]
**Learning:** In `backend/routes/inventory.py`, `_list_item_assignment_fields` accessed `len(item.source_assignments)` for standard inventory items and `assignment.source_item.inventory` for checklist items during response serialization, triggering unbatched lazy load queries for every item in the inventory (N queries).
**Action:** Pre-calculate assignment counts using a batched `GROUP BY ListAssignment.source_item_id` query, and chain `joinedload(Item.list_assignment).joinedload(ListAssignment.source_item).joinedload(Item.inventory)` in `list_items_base` to keep database query counts constant O(1).

## 2025-05-18 - [Batch Item Version Queries to Fix N+1]
**Learning:** In `backend/routes/inventory.py`, `_current_item_version_num` was called per item inside response serialisation loops in `list_inventories_base` and `list_items_base`, executing 1 query per item.
**Action:** Use a batched SQLAlchemy `GROUP BY ItemVersion.item_id` query filtered by `item_id.in_(...)` to fetch item versions in 1 query for all items.
