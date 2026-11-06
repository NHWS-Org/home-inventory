import { api } from "./api";

export type NotificationEventType = "inventory_shared" | "item_quantity_changed" | "checklist_completed";
export interface NotificationPreference {
  event_type: NotificationEventType;
  in_app_enabled: boolean;
  push_enabled: boolean;
  include_own_actions: boolean;
}
export interface NotificationRecipient {
  kind: "owner" | "participants" | "user" | "group" | "event_recipient";
  id?: number;
}
export interface NotificationRuleInput {
  event_type: NotificationEventType;
  threshold: number | null;
  recipients: NotificationRecipient[];
  enabled: boolean;
}
export interface NotificationRule extends NotificationRuleInput {
  id: number;
  inventory_id: number;
}
export interface InboxNotification {
  id: number;
  created_at: string;
  read_at: string | null;
  inventory_type: "INVENTORY" | "CHECKLIST";
  inventory_name: string;
  event: {
    event_type: NotificationEventType;
    inventory_id: number;
    item_id?: number;
    previous_quantity?: number;
    quantity?: number;
  };
}
export interface RuleRecipientOptions {
  users: { id: number; username: string }[];
  groups: { id: number; name: string }[];
}
export const notificationLabels: Record<NotificationEventType, string> = {
  inventory_shared: "Condivisione contenitore",
  item_quantity_changed: "Quantità sotto soglia",
  checklist_completed: "Lista completata",
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
export async function getNotificationRules(id: number): Promise<NotificationRule[]> {
  return (await api.get<NotificationRule[]>(`/notifications/rules/${id}`)).data;
}
export async function getRuleRecipients(id: number): Promise<RuleRecipientOptions> {
  return (await api.get<RuleRecipientOptions>(`/notifications/rules/${id}/recipients`)).data;
}
export async function saveNotificationRule(id: number, input: NotificationRuleInput, ruleId?: number): Promise<void> {
  if (ruleId !== undefined) await api.put(`/notifications/rules/${id}/${ruleId}`, input);
  else await api.post(`/notifications/rules/${id}`, input);
}
export async function deleteNotificationRule(id: number, ruleId: number): Promise<void> {
  await api.delete(`/notifications/rules/${id}/${ruleId}`);
}
export const NOTIFICATIONS_CHANGED = "notifications-changed";
export function notifyInboxChanged(): void {
  window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));
}
