export interface Role {
    id: number;
    name: string;
}
  
export interface User {
    id: number;
    username: string;
    email_masked: string;
    email: string;
    role: Role;
    is_blocked: boolean;
    data_ins: string;
    data_mod: string;
}

export interface Inventory {
    id: number;
    name: string;
    owner: User;
    item_count: number;
    data_ins: string;
    data_mod: string;
    user_ins: number | null;
    user_mod: number | null;
    version_num: number;
}

export interface ItemBarcode {
    id: number;
    code: string;
    format?: string | null;
}

export interface AssignmentSummary {
    id: number;
    list_checked: boolean;
    source_item_id: number;
    source_name: string | null;
    source_inventory_id: number | null;
    source_inventory_name: string | null;
    source_stock: number | null;
    source_net_qty: number | null;
    qty: number;
}

export interface Assignment {
    id: number;
    list_item_id: number;
    list_item_name: string | null;
    list_id: number | null;
    list_name: string | null;
    list_checked: boolean;
    source_item_id: number;
    source_name: string | null;
    source_inventory_id: number | null;
    source_inventory_name: string | null;
    source_stock: number | null;
    source_net_qty: number | null;
    qty: number;
}

export interface BarcodeMatch {
    item_id: number;
    name: string;
    quantity: number | null;
    inventory_id: number;
    inventory_name: string | null;
    inventory_type: string | null;
}

export interface BarcodeProduct {
    name: string | null;
    brand: string | null;
    quantity_label: string | null;
    image_url: string | null;
    source: string | null;
}

export interface BarcodeLookupResult {
    code: string;
    matches: BarcodeMatch[];
    product: BarcodeProduct | null;
}

export interface InventoryItem {
    barcodes?: ItemBarcode[];
    assignment?: AssignmentSummary | null;
    assignment_count?: number;
    assigned_qty?: number;
    net_qty?: number | null;
    id: number;
    name: string;
    description: string;
    quantity: number;
    inventory_id: number;
    user_ins: number;
    user_mod: number | null;
    username_ins: string;
    username_mod: string | null;
    data_ins: string;
    data_mod: string;
    metadata_values?: ItemMetadataValue[];
    version_num: number;
}

export interface Checklist {
    id: number;
    name: string;
    owner: User;
    item_count: number;
    data_ins: string;
    data_mod: string;
    user_ins: number | null;
    user_mod: number | null;
    version_num: number;
}

export interface ChecklistItem {
    barcodes?: ItemBarcode[];
    assignment?: AssignmentSummary | null;
    assignment_count?: number;
    assigned_qty?: number;
    net_qty?: number | null;
    id: number;
    name: string;
    description: string;
    quantity: number;
    inventory_id: number;
    user_ins: number;
    user_mod: number | null;
    username_ins: string;
    username_mod: string | null;
    data_ins: string;
    data_mod: string;
    metadata_values?: ItemMetadataValue[];
    version_num: number;
}

export interface Item {
    barcodes?: ItemBarcode[];
    assignment?: AssignmentSummary | null;
    assignment_count?: number;
    assigned_qty?: number;
    net_qty?: number | null;
    id: number;
    name: string;
    description: string;
    quantity: number;
    inventory_id: number;
    user_ins: number;
    user_mod: number | null;
    username_mod: string | null;
    data_ins: string;
    data_mod: string;
    metadata_values?: ItemMetadataValue[];
    version_num: number;
}

export interface ItemVersion {
    id: number;
    item_id: number;
    inventory_id: number;
    inventory_name?: string | null;
    inventory_type?: string | null;
    name: string;
    description: string | null;
    quantity: number | null;
    version_num: number;
    operation: "CREATE" | "UPDATE" | "DELETE";
    changed_at: string;
    changed_by_id: number | null;
    changed_by_username: string | null;
    diff: string | null;
}

export interface InventoryVersion {
    id: number;
    inventory_id: number;
    name: string;
    type: string;
    owner_id: number | null;
    owner_username: string | null;
    version_num: number;
    operation: "CREATE" | "UPDATE" | "DELETE";
    changed_at: string;
    changed_by_id: number | null;
    changed_by_username: string | null;
    diff: string | null;
}

export interface InventoryWithMatches extends Inventory {
    matching_items?: (Item & {
      highlighted?: {
        name: string;
        description?: string | null;
                metadata_text?: Array<{
                    definition_label: string;
                    value_text: string;
                }>;
      };
    })[];
}

export interface ChecklistWithMatches extends Checklist {
    matching_items?: (Item & {
      highlighted?: {
        name: string;
        description?: string | null;
                metadata_text?: Array<{
                    definition_label: string;
                    value_text: string;
                }>;
      };
    })[];
}

export type MetadataFieldType = "TEXT" | "NUMBER" | "BOOLEAN" | "DATE" | "LIST";

export type MetadataDefinitionScope = "GLOBAL" | "INVENTORY_TYPE" | "INVENTORY";

export type InventoryContainerType = "INVENTORY" | "CHECKLIST";

export type MetadataFilterOperator =
    | "equals"
    | "not_equals"
    | "contains"
    | "not_contains"
    | "gt"
    | "gte"
    | "lt"
    | "lte"
    | "between"
    | "is_null"
    | "is_not_null";

export interface MetadataAssignment {
    id: number;
    definition_id: number;
    scope: MetadataDefinitionScope;
    inventory_type?: InventoryContainerType | null;
    inventory_id?: number | null;
    data_ins: string;
    data_mod: string;
}

export interface MetadataAssignmentCreate {
    scope: MetadataDefinitionScope;
    inventory_type?: InventoryContainerType | null;
    inventory_id?: number | null;
}

export interface MetadataListOption {
    value: string;
    label: string;
}

export interface MetadataDefinition {
    id: number;
    key: string;
    label: string;
    description?: string | null;
    field_type: MetadataFieldType;
    list_options: MetadataListOption[];
    sort_order: number;
    is_required: boolean;
    is_active: boolean;
    assignments: MetadataAssignment[];
    data_ins: string;
    data_mod: string;
    user_ins: number | null;
    user_mod: number | null;
}

export interface MetadataDefinitionCreate {
    key: string;
    label: string;
    description?: string | null;
    field_type: MetadataFieldType;
    list_options?: MetadataListOption[];
    sort_order?: number;
    is_required?: boolean;
    is_active?: boolean;
}

export interface MetadataDefinitionUpdate {
    key?: string;
    label?: string;
    description?: string | null;
    list_options?: MetadataListOption[];
    sort_order?: number;
    is_required?: boolean;
    is_active?: boolean;
}

export interface ItemMetadataTypedValue {
    value_text?: string | null;
    value_number?: string | number | null;
    value_boolean?: boolean | null;
    value_date?: string | null;
}

export interface ItemMetadataValue extends ItemMetadataTypedValue {
    id: number;
    item_id: number;
    definition_id: number;
    definition_key?: string | null;
    definition_label?: string | null;
    field_type?: MetadataFieldType;
    display_value?: string | null;
    data_ins: string;
    data_mod: string;
    user_ins: number | null;
    user_mod: number | null;
}

export interface ItemMetadataValueCreate extends ItemMetadataTypedValue {
    item_id: number;
    definition_id: number;
}

export type ItemMetadataValueUpdate = ItemMetadataTypedValue;

export interface ItemMetadataValueUpsert extends ItemMetadataTypedValue {
    definition_id: number;
}

export interface ItemMetadataBulkUpsertRequest {
    item_id: number;
    values: ItemMetadataValueUpsert[];
}

export interface TextMetadataFilterCriterion {
    definition_id: number;
    operator: MetadataFilterOperator;
    value_text?: string | null;
}

export interface TextMetadataFilterRequest {
    inventory_id: number;
    match_mode?: "all" | "any";
    criteria: TextMetadataFilterCriterion[];
}

export interface TextMetadataFilterResponse {
    inventory_id: number;
    match_mode: "all" | "any";
    item_ids: number[];
    count: number;
}

export interface NumericMetadataFilterCriterion {
    definition_id: number;
    operator: MetadataFilterOperator;
    value_number?: string | number | null;
    range_from?: string | number | null;
    range_to?: string | number | null;
}

export interface NumericMetadataFilterRequest {
    inventory_id: number;
    match_mode?: "all" | "any";
    criteria: NumericMetadataFilterCriterion[];
}

export interface NumericMetadataFilterResponse {
    inventory_id: number;
    match_mode: "all" | "any";
    item_ids: number[];
    count: number;
}

export interface DateMetadataFilterCriterion {
    definition_id: number;
    operator: MetadataFilterOperator;
    value_date?: string | null;
    range_from?: string | null;
    range_to?: string | null;
}

export interface DateMetadataFilterRequest {
    inventory_id: number;
    match_mode?: "all" | "any";
    criteria: DateMetadataFilterCriterion[];
}

export interface DateMetadataFilterResponse {
    inventory_id: number;
    match_mode: "all" | "any";
    item_ids: number[];
    count: number;
}

export interface BooleanMetadataFilterCriterion {
    definition_id: number;
    operator: MetadataFilterOperator;
    value_boolean?: boolean | null;
}

export interface BooleanMetadataFilterRequest {
    inventory_id: number;
    match_mode?: "all" | "any";
    criteria: BooleanMetadataFilterCriterion[];
}

export interface BooleanMetadataFilterResponse {
    inventory_id: number;
    match_mode: "all" | "any";
    item_ids: number[];
    count: number;
}

export type FilterTemplateType = "numeric" | "date" | "boolean" | "text" | "composite";

export interface FilterTemplateBase {
    name: string;
    description?: string | null;
    filter_type: FilterTemplateType;
    criteria: Record<string, unknown>;
    is_shared?: boolean;
}

export interface FilterTemplate extends FilterTemplateBase {
    id: number;
    inventory_id: number | null;
    is_shared: boolean;
    data_ins: string;
    data_mod: string;
    user_ins: number | null;
    user_mod: number | null;
}

export interface FilterTemplateScopeInventory {
    id: number;
    name: string;
    type: string;
}

export interface FilterTemplateScopePreview {
    scope_type: "global" | "all_inventories" | "all_checklists" | "specific" | "none";
    summary: string;
    inventories: FilterTemplateScopeInventory[];
}

export interface FilterTemplateListItem {
    id: number;
    inventory_id: number | null;
    name: string;
    description?: string | null;
    filter_type: FilterTemplateType;
    criteria_count?: number | null;
    is_shared: boolean;
    data_ins: string;
    data_mod: string;
    scope_preview?: FilterTemplateScopePreview | null;
}

export type FilterTemplateCreate = FilterTemplateBase;

export interface FilterTemplateUpdate {
    name?: string;
    description?: string | null;
    filter_type?: FilterTemplateType;
    criteria?: Record<string, unknown>;
    is_shared?: boolean;
}