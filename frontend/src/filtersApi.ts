import { api } from "./api";

export type FilterContainerType = "INVENTORY" | "CHECKLIST";
export type FilterFieldType = "TEXT" | "NUMBER" | "BOOLEAN" | "DATE" | "LIST";
export type FilterOperator =
  | "equals" | "not_equals" | "contains" | "not_contains"
  | "gt" | "gte" | "lt" | "lte" | "between" | "is_null" | "is_not_null";
export type RelativeDate = { relative_days: number };
export type FilterValue = string | number | boolean | RelativeDate | null;

export interface FilterField {
  field: string;
  label: string;
  source: "item" | "metadata";
  field_type: FilterFieldType;
  definition_id?: number;
  operators: FilterOperator[];
  container_types: FilterContainerType[];
  list_options?: Array<{ value: string; label: string }>;
}

export interface FilterCondition {
  source: "item" | "metadata";
  field: string;
  definition_id?: number;
  operator: FilterOperator;
  value?: FilterValue;
  range_from?: FilterValue;
  range_to?: FilterValue;
}

export interface FilterInput {
  name: string;
  description?: string;
  is_shared: boolean;
  container_type: FilterContainerType | null;
  match_mode: "all" | "any";
  conditions: FilterCondition[];
}

export function validateFilterInput(input: FilterInput): void {
  if (!input.name.trim()) throw new Error("Inserisci il nome del filtro.");
  if (!input.conditions.length) throw new Error("Aggiungi almeno una condizione.");
}

export interface FilterScopePreview {
  scope_type: "global" | "all_inventories" | "all_checklists" | "specific" | "none";
  summary: string;
  inventories: Array<{ id: number; name: string; type: FilterContainerType }>;
}

export interface FilterResponse extends FilterInput {
  id: number;
  user_ins: string;
  user_mod: string;
  data_ins: string;
  data_mod: string;
  scope_preview: FilterScopePreview;
  trigger_count: number;
  can_manage: boolean;
  validation_error?: string | null;
}

export interface FilterEvaluation {
  containers: Array<{ id: number; name: string; type: FilterContainerType; item_ids: number[]; count: number }>;
  total_count: number;
}

export interface FilterPreviewInput extends FilterInput {
  inventory_id?: number;
  timezone?: string;
}

export interface TriggerInput {
  name: string;
  filter_id: number;
  enabled: boolean;
  time: string;
  timezone: string;
  weekdays: number[];
  inventory_ids: number[] | null;
  notify_mode: "always" | "changed";
}

export interface TriggerResponse extends TriggerInput {
  id: number;
  filter_name: string;
  scope_preview: FilterScopePreview;
  can_manage: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  last_result_count: number | null;
  last_container_count: number | null;
  last_error: string | null;
}

export interface TriggerSubscription {
  trigger_id: number;
  enabled: boolean;
}

export async function getFilters(inventoryId?: number): Promise<FilterResponse[]> {
  const response = await api.get<FilterResponse[]>("/filters", {
    params: inventoryId ? { inventory_id: inventoryId } : undefined,
  });
  return response.data;
}

export async function getFilter(id: number): Promise<FilterResponse> {
  return (await api.get<FilterResponse>(`/filters/${id}`)).data;
}

export async function getFilterFields(): Promise<FilterField[]> {
  return (await api.get<FilterField[]>("/filters/fields")).data;
}

export async function createFilter(input: FilterInput): Promise<FilterResponse> {
  return (await api.post<FilterResponse>("/filters", input)).data;
}

export async function updateFilter(id: number, input: FilterInput): Promise<FilterResponse> {
  return (await api.patch<FilterResponse>(`/filters/${id}`, input)).data;
}

export async function deleteFilter(id: number): Promise<void> {
  await api.delete(`/filters/${id}`);
}

export async function previewFilter(input: FilterPreviewInput): Promise<FilterEvaluation> {
  return (await api.post<FilterEvaluation>("/filters/preview", input)).data;
}

export async function evaluateFilter(
  id: number,
  input: { inventory_id?: number; timezone?: string } = {},
): Promise<FilterEvaluation> {
  return (await api.post<FilterEvaluation>(`/filters/${id}/evaluate`, input)).data;
}

export async function getTriggers(): Promise<TriggerResponse[]> {
  return (await api.get<TriggerResponse[]>("/triggers")).data;
}

export async function getTrigger(id: number): Promise<TriggerResponse> {
  return (await api.get<TriggerResponse>(`/triggers/${id}`)).data;
}

export async function createTrigger(input: TriggerInput): Promise<TriggerResponse> {
  return (await api.post<TriggerResponse>("/triggers", input)).data;
}

export async function updateTrigger(id: number, input: TriggerInput): Promise<TriggerResponse> {
  return (await api.patch<TriggerResponse>(`/triggers/${id}`, input)).data;
}

export async function deleteTrigger(id: number): Promise<void> {
  await api.delete(`/triggers/${id}`);
}

export async function previewTrigger(id: number): Promise<FilterEvaluation> {
  return (await api.post<FilterEvaluation>(`/triggers/${id}/preview`)).data;
}

export async function getTriggerSubscriptions(): Promise<TriggerSubscription[]> {
  return (await api.get<TriggerSubscription[]>("/triggers/subscriptions")).data;
}

export async function saveTriggerSubscription(id: number, enabled: boolean): Promise<void> {
  await api.put(`/triggers/${id}/subscription`, { enabled });
}

export const FILTER_WEEKDAYS = [
  { value: 1, label: "Lun" },
  { value: 2, label: "Mar" },
  { value: 3, label: "Mer" },
  { value: 4, label: "Gio" },
  { value: 5, label: "Ven" },
  { value: 6, label: "Sab" },
  { value: 7, label: "Dom" },
] as const;

export function formatWeekdays(days: number[]): string {
  const sorted = [...new Set(days)].sort((a, b) => a - b);
  if (sorted.length === 7) return "Ogni giorno";
  if (sorted.length === 5 && sorted.every((day, index) => day === index + 1)) return "Lun – Ven";
  if (sorted.length === 0) return "Nessun giorno";
  return sorted.map(day => FILTER_WEEKDAYS.find(option => option.value === day)?.label ?? String(day)).join(", ");
}
