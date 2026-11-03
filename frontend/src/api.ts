import axios from 'axios';
import {
  User,
  Role,
  Inventory,
  InventoryItem,
  InventoryWithMatches,
  Checklist,
  ChecklistItem,
  ChecklistWithMatches,
  ItemVersion,
  ItemBarcode,
  Assignment,
  BarcodeLookupResult,
  InventoryVersion,
  MetadataDefinition,
  MetadataDefinitionCreate,
  MetadataAssignment,
  MetadataAssignmentCreate,
  MetadataDefinitionUpdate,
  ItemMetadataValue,
  ItemMetadataValueCreate,
  ItemMetadataValueUpdate,
  ItemMetadataBulkUpsertRequest,
  TextMetadataFilterRequest,
  TextMetadataFilterResponse,
  NumericMetadataFilterRequest,
  NumericMetadataFilterResponse,
  DateMetadataFilterRequest,
  DateMetadataFilterResponse,
  BooleanMetadataFilterRequest,
  BooleanMetadataFilterResponse,
  FilterTemplate,
  FilterTemplateCreate,
  FilterTemplateListItem,
  FilterTemplateUpdate,
  FilterTemplateScopePreview,
} from "./types";

function getApiBaseUrl() {
  return '/api';
}

const api = axios.create({
  baseURL: getApiBaseUrl(),
  withCredentials: false,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      localStorage.removeItem('access_token');
      if (
        typeof window !== 'undefined' &&
        window.location.pathname !== '/login' &&
        window.location.pathname !== '/register'
      ) {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export function createApiInstance() {
  api.defaults.baseURL = getApiBaseUrl();
}

export { api };

/* LOGIN UTENTI */
export async function loginUser(username: string, password: string): Promise<{ access_token: string }> {
  const response = await api.post(
    "/auth/login",
    new URLSearchParams({ username, password }),
    {
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-Client-Timezone': Intl.DateTimeFormat().resolvedOptions().timeZone || '',
      },
    }
  )
  return response.data as { access_token: string }
}

export interface DeviceSession {
  id: number;
  device_type: string | null;
  browser: string | null;
  operating_system: string | null;
  language: string | null;
  timezone: string | null;
  region: string | null;
  created_at: string;
  expires_at: string;
  is_expired: boolean;
  revoked_at: string | null;
  is_current: boolean;
}

export async function getDeviceSessions(): Promise<DeviceSession[]> {
  const response = await api.get<DeviceSession[]>('/auth/sessions');
  return response.data;
}

export async function revokeDeviceSession(sessionId: number): Promise<void> {
  await api.delete(`/auth/sessions/${sessionId}`);
}

/* REGISTRAZIONE UTENTI */
export async function registerUser(username: string, password: string, email: string): Promise<void> {
  await api.post("/auth/register", {
    username,
    password,
    email
  });
}

/* RECUPERO DATI UTENTE */
export async function getUserInfo() {
  const response = await api.get("/auth/me");
  return response.data;
}

/* RECUPERO LISTA UTENTI */
export async function getUsers(): Promise<User[]> {
  const response = await api.get<User[]>("/user/users/");
  return response.data;
}

/* RECUPERO VERSIONE API */
export async function getApiVersion(): Promise<{ version: string }> {
  const response = await api.get<{ version: string }>("/system/version");
  return response.data;
}

export interface AboutStats {
  available: boolean;
  active_installations: number | null;
  active_window_days: number | null;
  countries: { country: string; n: number }[];
  versions: { version: string; n: number }[];
  channels: { channel: string; n: number }[];
}

/* STATISTICHE AGGREGATE DELLA COMMUNITY (TAB ABOUT) */
export async function getAboutStats(): Promise<AboutStats> {
  const response = await api.get<AboutStats>("/system/about-stats");
  return response.data;
}

/* EFFETTUA LOGOUT */
export async function logoutApi() {
  await api.post("/auth/logout")
}

/* AGGIORNAMENTO DATI UTENTE */
export async function updateMe(email: string, password: string): Promise<void> {
  await api.put("/auth/me", {
    email,
    password
  });
}

/* LISTING RUOLI */
export async function getRoles(): Promise<Role[]> {
  const response = await api.get("/user/roles/");
  if (Array.isArray(response.data)) {
    return response.data;
  } else {
    console.error("Formato ruoli non valido:", response.data);
    return [];
  }
}

/* CREAZIONE, AGGIORNAMENTO E CANCELLAZIONE UTENTI */
export const createUser = async (data: {
  username: string;
  email: string;
  password: string;
  roleId: number;
}) => {
  const payload = {
    username: data.username,
    email: data.email,
    password: data.password,
    role_id: data.roleId,
  };
  const response = await api.post("/user/users/", payload);
  return response.data;
};

export const updateUser = async (
  id: number,
  data: {
    username: string;
    email: string;
    password?: string;
    is_blocked: boolean;
    role_id: number;
  }) => {
  const response = await api.put(`/user/users/${id}`, data);
  return response.data;
};

export const deleteUser = async (id: number) => {
  const response = await api.delete(`/user/users/${id}`);
  return response.data;
};

/* PAGINA DI WELCOME */
export async function getApiWelcomeInfo(): Promise<{
  title: string;
  message: string;
  stats: {
    total_inventories: number;
    total_inventories_items: number;
    total_checklists: number;
    total_checklists_items: number;
    total_users: number;
  };
}> {
  const response = await api.get('/');
  return response.data as {
    title: string;
    message: string;
    stats: {
      total_inventories: number;
      total_inventories_items: number;
      total_checklists: number;
      total_checklists_items: number;
      total_users: number;
    };
  };
}

/* REPERIMENTO LISTA IMPOSTAZIONI */
export async function getAllSettings(): Promise<{ key: string; value: string; protected: boolean }[]> {
  const response = await api.get('/settings/settings');
  return response.data as { key: string; value: string; protected: boolean }[];
}

/* CREAZIONE, AGGIORNAMENTO E CANCELLAZIONE IMPOSTAZIONI */
export async function getSetting(key: string): Promise<{ key: string; value: string; protected: boolean }> {
  const response = await api.get(`/settings/settings/${key}`);
  return response.data as { key: string; value: string; protected: boolean };
}

/* AGGIORNAMENTO IMPOSTAZIONI */
export async function setSetting(key: string, value: string): Promise<{ key: string; value: string; protected: boolean }> {
  const response = await api.post(`/settings/settings`, {
    key,
    value,
  });
  return response.data as { key: string; value: string; protected: boolean };
}

/* CANCELLAZIONE IMPOSTAZIONI */
export async function deleteSetting(key: string): Promise<void> {
  await api.delete(`/settings/settings/${key}`);
}

/* CREAZIONE INVENTARIO */
export async function createInventory(name: string): Promise<Inventory> {
  const response = await api.post('/inventory/', { name });
  return response.data as Inventory;
}

/* CANCELLAZIONE INVENTARIO */
export async function deleteInventory(id: number) {
  await api.delete(`/inventory/${id}`);
}

/* LISTA INVENTARI con filtro opzionale */
export async function getInventories(filtro?: string): Promise<(InventoryWithMatches)[]> {
  const response = await api.get('/inventory/', {
    params: filtro ? { filtro } : {},
  });
  return response.data as (InventoryWithMatches)[];
}

/* RECUPERO INVENTARIO PER ID */
export async function getInventoryById(id: number): Promise<Inventory> {
  const response = await api.get(`/inventory/${id}`);
  return response.data as Inventory;
}

/* RECUPERO ELENCO ITEM PER ID INVENTARIO */
export async function getInventoryItems(id: number): Promise<InventoryItem[]> {
  const response = await api.get(`/inventory/item/${id}/`);
  return response.data as InventoryItem[];
}

/* CREAZIONE CHECKLIST */
export async function createChecklist(name: string): Promise<Checklist> {
  const response = await api.post('/checklist/', { name });
  return response.data as Checklist;
}

/* CANCELLAZIONE CHECKLIST */
export async function deleteChecklist(id: number) {
  await api.delete(`/checklist/${id}`);
}

/* LISTA CHECKLISTS con filtro opzionale */
export async function getChecklists(filtro?: string): Promise<(ChecklistWithMatches)[]> {
  const response = await api.get('/checklist/', {
    params: filtro ? { filtro } : {},
  });
  return response.data as (ChecklistWithMatches)[];
}

/* RECUPERO CHECKLIST PER ID */
export async function getChecklistById(id: number): Promise<Checklist> {
  const response = await api.get(`/checklist/${id}`);
  return response.data as Checklist;
}

/* RECUPERO ELENCO ITEM PER ID CHECKLIST */
export async function getChecklistItems(id: number): Promise<ChecklistItem[]> {
  const response = await api.get(`/checklist/item/${id}/`);
  return response.data as ChecklistItem[];
}

/* CREAZIONE ITEM */
export async function createItem(data: {
  name: string;
  description?: string;
  quantity: number;
  inventory_id: number;
  barcodes?: { code: string; format?: string | null }[];
}): Promise<InventoryItem> {
  const response = await api.post('/item/', data);
  return response.data as InventoryItem;
}

/* BARCODE */
export async function lookupBarcode(code: string, external = true): Promise<BarcodeLookupResult> {
  const response = await api.get('/barcode/lookup', { params: { code, external } });
  return response.data as BarcodeLookupResult;
}

export interface AdminBarcodeRecord {
  id: number;
  code: string;
  format: string | null;
  item_id: number;
  item_name: string;
  inventory_id: number;
  inventory_name: string;
  data_mod: string;
}

export interface AdminBarcodeCacheEntry {
  code: string;
  found: boolean;
  name: string | null;
  brand: string | null;
  quantity_label: string | null;
  image_url: string | null;
  source: string | null;
  fetched_at: string;
}

export interface AdminBarcodeDebugResult {
  raw_code: string;
  normalized_code: string;
  format: string | null;
  is_valid_gtin: boolean;
  is_isbn: boolean;
  lookup_enabled: boolean;
  source_checks: { source: string; outcome: 'found' | 'missing' | 'error' | 'pending'; detail?: string }[];
  force_refresh: boolean;
  matches: { barcode_id: number; item_id: number; item_name: string; inventory_id: number; inventory_name: string }[];
  product: { name: string | null; brand: string | null; quantity_label: string | null; image_url: string | null; source: string | null } | null;
  cache: { found: boolean; name: string | null; brand: string | null; source: string | null; fetched_at: string } | null;
  checked_at: string;
}

export async function getAdminBarcodes(query = ''): Promise<AdminBarcodeRecord[]> {
  const response = await api.get('/barcode/admin/codes', { params: { query } });
  return response.data as AdminBarcodeRecord[];
}

export async function getAdminBarcodeCache(query = ''): Promise<AdminBarcodeCacheEntry[]> {
  const response = await api.get('/barcode/admin/cache', { params: { query } });
  return response.data as AdminBarcodeCacheEntry[];
}

export async function debugAdminBarcode(code: string, format: string | null, forceRefresh = false): Promise<AdminBarcodeDebugResult> {
  const response = await api.post('/barcode/admin/debug', { code, format, force_refresh: forceRefresh });
  return response.data as AdminBarcodeDebugResult;
}

export async function correctAdminBarcode(barcodeId: number, code: string, format: string | null): Promise<void> {
  await api.put(`/barcode/admin/codes/${barcodeId}`, { code, format });
}

export async function deleteAdminBarcodeCache(code: string): Promise<void> {
  await api.delete(`/barcode/admin/cache/${encodeURIComponent(code)}`);
}

export async function clearAdminBarcodeCache(): Promise<number> {
  const response = await api.delete('/barcode/admin/cache');
  return response.data.deleted as number;
}

export async function addItemBarcode(itemId: number, code: string, format?: string | null): Promise<ItemBarcode> {
  const response = await api.post(`/item/${itemId}/barcodes`, { code, format: format ?? null });
  return response.data as ItemBarcode;
}

export async function deleteItemBarcode(itemId: number, barcodeId: number): Promise<void> {
  await api.delete(`/item/${itemId}/barcodes/${barcodeId}`);
}

/* MODIFICA ITEM */
export async function updateItem(itemId: number, data: {
  name: string;
  description?: string;
  quantity: number;
  inventory_id: number;
}, onInsufficient?: 'zero'): Promise<InventoryItem> {
  const response = await api.patch(`/item/${itemId}`, data, {
    params: onInsufficient ? { on_insufficient: onInsufficient } : undefined,
  });
  return response.data as InventoryItem;
}

/* ASSEGNAZIONI lista -> inventario */
export async function createAssignment(listItemId: number, sourceItemId: number, qty: number): Promise<Assignment> {
  const response = await api.post('/assignment/', { list_item_id: listItemId, source_item_id: sourceItemId, qty });
  return response.data as Assignment;
}

export async function updateAssignment(id: number, qty: number): Promise<Assignment> {
  const response = await api.patch(`/assignment/${id}`, { qty });
  return response.data as Assignment;
}

export async function deleteAssignment(id: number): Promise<void> {
  await api.delete(`/assignment/${id}`);
}

export async function getAssignmentsBySource(itemId: number): Promise<Assignment[]> {
  const response = await api.get(`/assignment/by-source/${itemId}`);
  return response.data as Assignment[];
}

/* CANCELLAZIONE ITEM */
export async function deleteItem(itemId: number): Promise<void> {
  await api.request({
    url: `/item/${itemId}`,
    method: 'DELETE',
    data: { confirm: true }
  });
}

// === UTENTI ===
export async function getSharableUsers(inventoryId: number) {
  const res = await api.get(`/user/users/shareable/${inventoryId}`);
  return res.data;
}

export async function shareInventoryWithUser(inventoryId: number, username: string) {
  return api.post(`/inventory/share/${inventoryId}/${username}`);
}

export async function unshareInventoryWithUser(inventoryId: number, username: string) {
  return api.delete(`/inventory/share/${inventoryId}/${username}`);
}

export async function shareChecklistWithUser(inventoryId: number, username: string) {
  return api.post(`/checklist/share/${inventoryId}/${username}`);
}

export async function unshareChecklistWithUser(inventoryId: number, username: string) {
  return api.delete(`/checklist/share/${inventoryId}/${username}`);
}

// === GRUPPI ===
export async function getAllGroups() {
  const res = await api.get('/user/groups/');
  return res.data;
}

export async function shareInventoryWithGroup(inventoryId: number, groupId: number) {
  return api.post(`/inventory/share_group/${inventoryId}/${groupId}`);
}

export async function unshareInventoryFromGroup(inventoryId: number, groupId: number) {
  return api.delete(`/inventory/share_group/${inventoryId}/${groupId}`);
}

export async function shareChecklistWithGroup(inventoryId: number, groupId: number) {
  return api.post(`/checklist/share_group/${inventoryId}/${groupId}`);
}

export async function unshareChecklistFromGroup(inventoryId: number, groupId: number) {
  return api.delete(`/checklist/share_group/${inventoryId}/${groupId}`);
}

export async function createGroup(data: { name: string; role_id: number }) {
  const res = await api.post('/user/groups/', data);
  return res.data;
}

export async function updateGroup(groupId: number, data: { name: string; role_id: number; users?: number[] }) {
  const res = await api.put(`/user/groups/${groupId}`, data);
  return res.data;
}

export async function deleteGroup(groupId: number) {
  const res = await api.delete(`/user/groups/${groupId}`);
  return res.data;
}

// === DETTAGLI ACCESSO ===
export async function getInventoryAccessDetails(inventoryId: number) {
  const res = await api.get(`/inventory/access_details/${inventoryId}`);
  return res.data;
}

export async function getInventoryUserShares(inventoryId: number) {
  const response = await api.get(`/inventory/share/${inventoryId}`);
  return response.data;
}

export async function getInventoryGroupShares(inventoryId: number) {
  const response = await api.get(`/inventory/share_group/${inventoryId}`);
  return response.data;
}
export async function getChecklistAccessDetails(inventoryId: number) {
  const res = await api.get(`/checklist/access_details/${inventoryId}`);
  return res.data;
}

export async function getChecklistUserShares(inventoryId: number) {
  const response = await api.get(`/checklist/share/${inventoryId}`);
  return response.data;
}

export async function getChecklistGroupShares(inventoryId: number) {
  const response = await api.get(`/checklist/share_group/${inventoryId}`);
  return response.data;
}

export async function updateInventoryName(inventoryId: number, name: string): Promise<void> {
  await api.patch(`/inventory/${inventoryId}`, { name });
}
export async function updateChecklistName(inventoryId: number, name: string): Promise<void> {
  await api.patch(`/checklist/${inventoryId}`, { name });
}

export async function getAllRoles() {
  const res = await api.get('/user/roles/');
  return res.data;
}

// === GESTIONE UTENTI NEI GRUPPI ===
export async function addUserToGroup(groupId: number, userId: number) {
  const res = await api.post(`/user/groups/${groupId}/add_user/${userId}`);
  return res.data;
}

export async function removeUserFromGroup(groupId: number, userId: number) {
  const res = await api.delete(`/user/groups/${groupId}/remove_user/${userId}`);
  return res.data;
}

// Elenco dei backup disponibili
export async function listBackups() {
  const res = await api.get('/backup/');
  return res.data;
}

export async function getBackupCompatibilityMap(): Promise<{
  revisions: string[];
  revision_labels?: Record<string, string | null>;
  matrix: Array<{
    source_revision: string;
    targets: Array<{
      target_revision: string;
      compatible: boolean;
      strategy?: string;
      reason?: string;
    }>;
  }>;
  explicit_rules: Array<{
    source_revision: string;
    target_revision: string;
    strategy?: string;
    reason?: string;
  }>;
}> {
  const res = await api.get('/backup/compatibility-map');
  return res.data as {
    revisions: string[];
    revision_labels?: Record<string, string | null>;
    matrix: Array<{
      source_revision: string;
      targets: Array<{
        target_revision: string;
        compatible: boolean;
        strategy?: string;
        reason?: string;
      }>;
    }>;
    explicit_rules: Array<{
      source_revision: string;
      target_revision: string;
      strategy?: string;
      reason?: string;
    }>;
  };
}

// Creazione di un nuovo backup
export async function createBackup() {
  const res = await api.post(`/backup/create`);
  return res.data;
}

// Download di un backup esistente
export async function downloadBackup(filename: string): Promise<void> {
  const response = await api.get(`/backup/download/${encodeURIComponent(filename)}`, {
    responseType: 'blob'
  });

  const blob = new Blob([response.data as Blob]);
  const url = window.URL.createObjectURL(blob);

  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();

  window.URL.revokeObjectURL(url);
}

// Ripristino di un backup esistente
export async function restoreBackup(filename: string): Promise<void> {
  await api.request({
    url: `/backup/restore/${encodeURIComponent(filename)}`,
    method: 'POST',
    data: {
      confirm: true,
      mode: 'base',
      overwrite_users_roles: false,
      overwrite_settings: false,
      overwrite_admin: false,
    }
  });
}

export async function restoreBackupGuided(
  filename: string,
  options: {
    mode: 'base' | 'advanced';
    overwrite_users_roles?: boolean;
    overwrite_settings?: boolean;
    overwrite_admin?: boolean;
  }
): Promise<void> {
  await api.request({
    url: `/backup/restore/${encodeURIComponent(filename)}`,
    method: 'POST',
    data: {
      confirm: true,
      mode: options.mode,
      overwrite_users_roles: options.overwrite_users_roles ?? false,
      overwrite_settings: options.overwrite_settings ?? false,
      overwrite_admin: options.overwrite_admin ?? false,
    }
  });
}

// Cancellazione di un backup esistente
export async function deleteBackup(filename: string): Promise<void> {
  await api.request({
    url: `/backup/delete/${encodeURIComponent(filename)}`,
    method: 'DELETE',
    data: true
  });
}

export async function deleteBackupsBulk(filenames: string[]): Promise<{
  message: string;
  deleted: string[];
  missing: string[];
  invalid: string[];
}> {
  const response = await api.post('/backup/delete-bulk', {
    confirm: true,
    filenames,
  });
  return response.data as {
    message: string;
    deleted: string[];
    missing: string[];
    invalid: string[];
  };
}

// Upload di un backup esistente
export async function uploadBackup(file: File): Promise<void> {
  const formData = new FormData();
  formData.append('file', file);

  await api.post('/backup/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
}

// === BACKUP SCHEDULAZIONI ===
export async function getBackupSchedule(): Promise<{
  frequency: string;
  interval_days?: number;
  interval_hours?: number;
  interval_minutes?: number;
  retention: number;
}> {
  const res = await api.get<Record<string, { value: string }>>('/backup/schedule');
  return {
    frequency: res.data.BACKUP_FREQUENCY.value,
    interval_days: parseInt(res.data.BACKUP_INTERVAL_DAYS.value),
    interval_hours: parseInt(res.data.BACKUP_INTERVAL_HOURS.value),
    interval_minutes: parseInt(res.data.BACKUP_INTERVAL_MINUTES.value),
    retention: parseInt(res.data.BACKUP_RETENTION.value),
  };
}

export async function updateBackupSchedule(data: {
  frequency: string;
  interval_days?: number;
  interval_hours?: number;
  interval_minutes?: number;
  retention: number;
}): Promise<void> {
  await api.post('/backup/schedule', {
    backup_frequency: data.frequency,
    backup_int_days: data.interval_days ?? 0,
    backup_int_hours: data.interval_hours ?? 0,
    backup_int_minutes: data.interval_minutes ?? 0,
    backup_retention: data.retention
  });
}

export async function triggerScheduledBackup(): Promise<void> {
  await api.post('/backup/schedule/trigger');
}

// Tipo per recenti inventari e checklist
export type InventoryOrChecklistRecent = InventoryWithMatches & {
  type: "INVENTORY" | "CHECKLIST";
  username_mod?: string | null;
};

/* RECUPERO RECENTI INVENTARI E CHECKLIST */
export async function getRecentInventoriesAndChecklists(limit?: number): Promise<InventoryOrChecklistRecent[]> {
  const response = await api.get<InventoryOrChecklistRecent[]>('/recents', {
    params: limit ? { limit } : {},
  });
  return response.data;
}

/* === CRONOLOGIA VERSIONI ITEM === */
export async function getItemHistory(itemId: number): Promise<ItemVersion[]> {
  const response = await api.get(`/item/${itemId}/history`);
  return response.data as ItemVersion[];
}

export async function rollbackItem(itemId: number, versionNum: number): Promise<InventoryItem> {
  const response = await api.post(`/item/${itemId}/rollback/${versionNum}`);
  return response.data as InventoryItem;
}

export async function deleteItemHistoryVersion(itemId: number, versionNum: number): Promise<void> {
  await api.delete(`/item/${itemId}/history/${versionNum}`);
}

export async function deleteItemHistoryVersions(itemId: number, versionNums: number[]): Promise<void> {
  await api.post(`/item/${itemId}/history/delete`, { version_nums: versionNums });
}

/* === CRONOLOGIA VERSIONI INVENTARIO/CHECKLIST === */
export async function getInventoryHistory(inventoryId: number): Promise<InventoryVersion[]> {
  const response = await api.get(`/inventory/${inventoryId}/history`);
  return response.data as InventoryVersion[];
}

export async function rollbackInventory(inventoryId: number, versionNum: number): Promise<Inventory> {
  const response = await api.post(`/inventory/${inventoryId}/rollback/${versionNum}`);
  return response.data as Inventory;
}

export async function deleteInventoryHistoryVersion(inventoryId: number, versionNum: number): Promise<void> {
  await api.delete(`/inventory/${inventoryId}/history/${versionNum}`);
}

export async function deleteInventoryHistoryVersions(inventoryId: number, versionNums: number[]): Promise<void> {
  await api.post(`/inventory/${inventoryId}/history/delete`, { version_nums: versionNums });
}

export async function getChecklistHistory(checklistId: number): Promise<InventoryVersion[]> {
  const response = await api.get(`/checklist/${checklistId}/history`);
  return response.data as InventoryVersion[];
}

export async function rollbackChecklist(checklistId: number, versionNum: number): Promise<Checklist> {
  const response = await api.post(`/checklist/${checklistId}/rollback/${versionNum}`);
  return response.data as Checklist;
}

export async function deleteChecklistHistoryVersion(checklistId: number, versionNum: number): Promise<void> {
  await api.delete(`/checklist/${checklistId}/history/${versionNum}`);
}

export async function deleteChecklistHistoryVersions(checklistId: number, versionNums: number[]): Promise<void> {
  await api.post(`/checklist/${checklistId}/history/delete`, { version_nums: versionNums });
}

/* === AUDIT LOGS CENTRALIZZATI === */
export async function getItemAuditLogs(
  inventoryId?: number,
  userId?: number,
  userScope?: "active" | "none" | "deleted",
  operation?: string,
  fromDate?: string,
  toDate?: string
): Promise<ItemVersion[]> {
  const response = await api.get('/audit/logs/items', {
    params: {
      ...(inventoryId && { inventory_id: inventoryId }),
      ...(userId && { user_id: userId }),
      ...(userScope && { user_scope: userScope }),
      ...(operation && { operation }),
      ...(fromDate && { from_date: fromDate }),
      ...(toDate && { to_date: toDate }),
    },
  });
  return response.data as ItemVersion[];
}

export async function getInventoryAuditLogs(
  inventoryId?: number,
  userId?: number,
  userScope?: "active" | "none" | "deleted",
  operation?: string,
  inventoryType?: "INVENTORY" | "CHECKLIST",
  fromDate?: string,
  toDate?: string
): Promise<InventoryVersion[]> {
  const response = await api.get('/audit/logs/inventories', {
    params: {
      ...(inventoryId && { inventory_id: inventoryId }),
      ...(userId && { user_id: userId }),
      ...(userScope && { user_scope: userScope }),
      ...(operation && { operation }),
      ...(inventoryType && { inventory_type: inventoryType }),
      ...(fromDate && { from_date: fromDate }),
      ...(toDate && { to_date: toDate }),
    },
  });
  return response.data as InventoryVersion[];
}

/* === METADATA DEFINITIONS === */
export async function getMetadataDefinitions(
  inventoryId: number,
  includeInactive = false,
): Promise<MetadataDefinition[]> {
  const response = await api.get('/metadata/applicable', {
    params: {
      inventory_id: inventoryId,
      include_inactive: includeInactive,
    },
  });
  return response.data as MetadataDefinition[];
}

export async function listAllMetadataDefinitions(
  includeInactive = true,
): Promise<MetadataDefinition[]> {
  const response = await api.get('/metadata/definitions', {
    params: {
      include_inactive: includeInactive,
    },
  });
  return response.data as MetadataDefinition[];
}

export async function getMetadataDefinition(definitionId: number): Promise<MetadataDefinition> {
  const response = await api.get(`/metadata/definitions/${definitionId}`);
  return response.data as MetadataDefinition;
}

export async function createMetadataDefinition(
  payload: MetadataDefinitionCreate,
): Promise<MetadataDefinition> {
  const response = await api.post('/metadata/definitions', payload);
  return response.data as MetadataDefinition;
}

export async function updateMetadataDefinition(
  definitionId: number,
  payload: MetadataDefinitionUpdate,
): Promise<MetadataDefinition> {
  const response = await api.patch(`/metadata/definitions/${definitionId}`, payload);
  return response.data as MetadataDefinition;
}

export async function deleteMetadataDefinition(definitionId: number): Promise<{ detail: string }> {
  const response = await api.delete(`/metadata/definitions/${definitionId}`);
  return response.data as { detail: string };
}

export async function createMetadataAssignment(
  definitionId: number,
  payload: MetadataAssignmentCreate,
): Promise<MetadataAssignment> {
  const response = await api.post(`/metadata/definitions/${definitionId}/assignments`, payload);
  return response.data as MetadataAssignment;
}

export async function deleteMetadataAssignment(assignmentId: number): Promise<{ detail: string }> {
  const response = await api.delete(`/metadata/assignments/${assignmentId}`);
  return response.data as { detail: string };
}

/* === ITEM METADATA VALUES === */
export async function getItemMetadataValues(itemId: number): Promise<ItemMetadataValue[]> {
  const response = await api.get('/metadata/values', {
    params: { item_id: itemId },
  });
  return response.data as ItemMetadataValue[];
}

export async function getItemMetadataValue(valueId: number): Promise<ItemMetadataValue> {
  const response = await api.get(`/metadata/values/${valueId}`);
  return response.data as ItemMetadataValue;
}

export async function createItemMetadataValue(
  payload: ItemMetadataValueCreate,
): Promise<ItemMetadataValue> {
  const response = await api.post('/metadata/values', payload);
  return response.data as ItemMetadataValue;
}

export async function updateItemMetadataValue(
  valueId: number,
  payload: ItemMetadataValueUpdate,
): Promise<ItemMetadataValue> {
  const response = await api.patch(`/metadata/values/${valueId}`, payload);
  return response.data as ItemMetadataValue;
}

export async function deleteItemMetadataValue(valueId: number): Promise<{ detail: string }> {
  const response = await api.delete(`/metadata/values/${valueId}`);
  return response.data as { detail: string };
}

export async function bulkUpsertItemMetadataValues(
  payload: ItemMetadataBulkUpsertRequest,
): Promise<ItemMetadataValue[]> {
  const response = await api.put('/metadata/values/bulk-upsert', payload);
  return response.data as ItemMetadataValue[];
}

/* === METADATA ADVANCED FILTERS === */
export async function filterItemsByTextMetadata(
  payload: TextMetadataFilterRequest,
): Promise<TextMetadataFilterResponse> {
  const response = await api.post('/metadata/filters/text', payload);
  return response.data as TextMetadataFilterResponse;
}

export async function filterItemsByNumericMetadata(
  payload: NumericMetadataFilterRequest,
): Promise<NumericMetadataFilterResponse> {
  const response = await api.post('/metadata/filters/numeric', payload);
  return response.data as NumericMetadataFilterResponse;
}

export async function filterItemsByDateMetadata(
  payload: DateMetadataFilterRequest,
): Promise<DateMetadataFilterResponse> {
  const response = await api.post('/metadata/filters/date', payload);
  return response.data as DateMetadataFilterResponse;
}

export async function filterItemsByBooleanMetadata(
  payload: BooleanMetadataFilterRequest,
): Promise<BooleanMetadataFilterResponse> {
  const response = await api.post('/metadata/filters/boolean', payload);
  return response.data as BooleanMetadataFilterResponse;
}

/* === FILTER TEMPLATES === */
export async function getFilterTemplates(
  inventoryId: number,
  includeShared = true,
  includeIncompatible = false,
): Promise<FilterTemplateListItem[]> {
  const response = await api.get('/filter-templates', {
    params: {
      inventory_id: inventoryId,
      include_shared: includeShared,
      include_incompatible: includeIncompatible,
    },
  });
  return response.data as FilterTemplateListItem[];
}

export async function getFilterTemplate(templateId: number): Promise<FilterTemplate> {
  const response = await api.get(`/filter-templates/${templateId}`);
  return response.data as FilterTemplate;
}

export async function createFilterTemplate(
  payload: FilterTemplateCreate,
): Promise<FilterTemplate> {
  const response = await api.post('/filter-templates', payload);
  return response.data as FilterTemplate;
}

export async function getFilterTemplateScopePreview(
  definitionIds: number[],
): Promise<FilterTemplateScopePreview> {
  const response = await api.get('/filter-templates/scope-preview', {
    params: { definition_ids: definitionIds.join(',') },
  });
  return response.data as FilterTemplateScopePreview;
}

export async function updateFilterTemplate(
  templateId: number,
  payload: FilterTemplateUpdate,
): Promise<FilterTemplate> {
  const response = await api.patch(`/filter-templates/${templateId}`, payload);
  return response.data as FilterTemplate;
}

export async function deleteFilterTemplate(templateId: number): Promise<{ detail: string }> {
  const response = await api.delete(`/filter-templates/${templateId}`);
  return response.data as { detail: string };
}
