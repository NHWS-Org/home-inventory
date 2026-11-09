import { api } from "./api";

export type NotificationEventType = "item_quantity_changed" | "item_updated" | "inventory_updated";
export interface NotificationPreference {
  event_type: NotificationEventType;
  in_app_enabled: boolean;
  push_enabled: boolean;
  include_own_actions: boolean;
}
export type InboxEvent =
  | { event_type: "item_quantity_changed"; inventory_id: number; item_id: number; previous_quantity: number; quantity: number }
  | { event_type: "item_updated"; inventory_id: number; item_id: number; changed_fields: string[]; details?: Record<string, string | number | null> } & ({ operation: "created"; quantity: number } | { operation?: null; quantity?: null })
  | { event_type: "inventory_updated"; inventory_id: number; changed_fields: string[]; details?: Record<string, string | number | null> };
export interface InboxNotification {
  id: number;
  created_at: string;
  action_at?: string;
  read_at: string | null;
  inventory_type: "INVENTORY" | "CHECKLIST";
  inventory_name: string;
  item_name: string | null;
  event: InboxEvent;
}
export const notificationLabels: Record<NotificationEventType, string> = {
  item_quantity_changed: "Quantità / spunte",
  item_updated: "Creazione e dettagli degli elementi",
  inventory_updated: "Inventari / liste",
};
export function notificationLink(row: InboxNotification): string {
  const path = row.inventory_type === "CHECKLIST" ? "checklists" : "inventories";
  const target = `/${path}/${row.event.inventory_id}`;
  return row.read_at ? target : `${target}?notification_id=${row.id}`;
}
export function notificationAction(row: InboxNotification): string {
  const event = row.event;
  if (event.event_type === "item_updated" && event.operation === "created") {
    const quantity = event.quantity;
    const status = row.inventory_type === "CHECKLIST"
      ? `Spunta: ${quantity >= 1 ? "completato" : "da completare"}`
      : `Quantità: ${quantity}`;
    return `Nuovo elemento · ${status}`;
  }
  if (event.event_type === "item_quantity_changed") {
    if (row.inventory_type === "CHECKLIST") return event.quantity >= 1 ? "Spunta: completato" : "Spunta: da completare";
    const delta = event.quantity - event.previous_quantity;
    return `Quantità: ${delta > 0 ? "+" : ""}${delta}`;
  }
  const labels: Record<string, string> = {
    name: "Titolo", description: "Descrizione", priority: "Priorità", inventory_id: "Inventario/lista",
    barcodes: "Barcode", metadata: "Metadati", assignment: "Assegnazione", assignments: "Assegnazioni",
  };
  return event.changed_fields.map(field => {
    const label = labels[field] ?? field;
    if (event.details && field in event.details) return `${label}: ${event.details[field] ?? "(vuoto)"}`;
    return `${label}: modificato`;
  }).join(" · ");
}
export function notificationItemName(row: InboxNotification): string | null {
  const event = row.event;
  if (event.event_type === "item_updated" && event.operation === "created" && typeof event.details?.name === "string") {
    return event.details.name;
  }
  return row.item_name;
}
export function notificationDate(row: InboxNotification): Date {
  const value = row.action_at ?? row.created_at;
  return new Date(/[zZ]$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`);
}
export async function getInbox(offset = 0): Promise<InboxNotification[]> {
  return (await api.get<InboxNotification[]>("/notifications", { params: { limit: 50, offset } })).data;
}
export async function getUnreadCount(): Promise<number> {
  return (await api.get<{ count: number }>("/notifications/unread-count")).data.count;
}
export async function markNotificationRead(id: number): Promise<void> {
  await api.put(`/notifications/${id}/read`);
}
export async function markNotificationEventRead(eventKey: string): Promise<void> {
  await api.put(`/notifications/events/${encodeURIComponent(eventKey)}/read`);
}
export async function markOpenedNotificationRead(search: string): Promise<boolean> {
  const params = new URLSearchParams(search);
  const eventKey = params.get("notification_event");
  const id = params.get("notification_id");
  if (eventKey !== null && id !== null) throw new Error("Ambiguous notification link");
  if (id !== null) {
    if (!/^[1-9]\d*$/.test(id) || !Number.isSafeInteger(Number(id))) throw new Error("Invalid notification id");
    await markNotificationRead(Number(id));
  } else if (eventKey !== null) {
    if (!eventKey) throw new Error("Invalid notification event");
    await markNotificationEventRead(eventKey);
  } else {
    return false;
  }
  notifyInboxChanged();
  return true;
}
export async function markAllNotificationsRead(): Promise<void> {
  await api.put("/notifications/read-all");
}
export async function getNotificationPreferences(): Promise<NotificationPreference[]> {
  return (await api.get<NotificationPreference[]>("/notifications/preferences")).data;
}
export async function saveNotificationPreference(row: NotificationPreference): Promise<void> {
  const { event_type, ...input } = row;
  await api.put(`/notifications/preferences/${event_type}`, input);
}
export const NOTIFICATIONS_CHANGED = "notifications-changed";
export function notifyInboxChanged(): void {
  window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));
}
