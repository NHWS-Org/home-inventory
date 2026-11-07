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
  | { event_type: "item_updated"; inventory_id: number; item_id: number; changed_fields: string[] }
  | { event_type: "inventory_updated"; inventory_id: number; changed_fields: string[] };
export interface InboxNotification {
  id: number;
  created_at: string;
  read_at: string | null;
  inventory_type: "INVENTORY" | "CHECKLIST";
  inventory_name: string;
  item_name: string | null;
  event: InboxEvent;
}
export const notificationLabels: Record<NotificationEventType, string> = {
  item_quantity_changed: "Quantità / spunte",
  item_updated: "Dettagli degli elementi",
  inventory_updated: "Inventari / liste",
};
export function notificationLink(row: InboxNotification): string {
  const path = row.inventory_type === "CHECKLIST" ? "checklists" : "inventories";
  return `/${path}/${row.event.inventory_id}`;
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
