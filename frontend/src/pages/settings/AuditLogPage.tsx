import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  getInventoryAuditLogs,
  getItemAuditLogs,
  getUsers,
  getSetting,
  setSetting,
  getInventories,
  getChecklists,
} from "../../api";
import { User, InventoryVersion, ItemVersion } from "../../types";
import {
  parseDiffEntries,
  getInventoryTypeIcon,
  getInventoryPath,
} from "../../utils/auditDiff";

type OperationFilter = "" | "CREATE" | "UPDATE" | "DELETE";
type TargetFilter = "ALL" | "ITEMS" | "INVENTORIES";
type UserScopeFilter = "" | "active" | "none" | "deleted";

interface InventoryOption {
  id: number;
  name: string;
  type: "INVENTORY" | "CHECKLIST";
}

function toLocalInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export default function AuditLogPage() {
  const [target, setTarget] = useState<TargetFilter>("ALL");
  const [operation, setOperation] = useState<OperationFilter>("");
  const [selectedInventoryId, setSelectedInventoryId] = useState("");
  const [inventories, setInventories] = useState<InventoryOption[]>([]);
  const [selectedUserId, setSelectedUserId] = useState("");
  const [userScope, setUserScope] = useState<UserScopeFilter>("");
  const [users, setUsers] = useState<User[]>([]);
  const [fromDate, setFromDate] = useState(() => {
    const now = new Date();
    const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    return toLocalInputValue(sevenDaysAgo);
  });
  const [toDate, setToDate] = useState(() => toLocalInputValue(new Date()));
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const [retentionDays, setRetentionDays] = useState("90");
  const [itemLogs, setItemLogs] = useState<ItemVersion[]>([]);
  const [inventoryLogs, setInventoryLogs] = useState<InventoryVersion[]>([]);

  const sortedItemLogs = useMemo(
    () => [...itemLogs].sort((a, b) => new Date(b.changed_at).getTime() - new Date(a.changed_at).getTime()),
    [itemLogs]
  );
  const sortedInventoryLogs = useMemo(
    () => [...inventoryLogs].sort((a, b) => new Date(b.changed_at).getTime() - new Date(a.changed_at).getTime()),
    [inventoryLogs]
  );

  const renderDiff = (log: ItemVersion | InventoryVersion) => {
    if (log.operation === "CREATE") {
      return <span className="text-green-700 dark:text-green-400">Record creato</span>;
    }
    if (log.operation === "DELETE") {
      return <span className="text-red-700 dark:text-red-400">Record eliminato</span>;
    }
    if (!log.diff) {
      return <span className="text-gray-500">Nessuna modifica dettagliata</span>;
    }

    const isChecklist =
      "inventory_type" in log
        ? log.inventory_type === "CHECKLIST"
        : "type" in log && log.type === "CHECKLIST";
    const entries = parseDiffEntries(log.diff, isChecklist);

    if (entries.length === 0) {
      return <span className="text-gray-500">Nessuna modifica rilevata</span>;
    }

    return (
      <div className="space-y-1">
        {entries.map((entry) => (
          <div key={entry.field}>
            <span className="font-semibold">{entry.label}:</span>{" "}
            <span>{entry.formattedChange}</span>
          </div>
        ))}
      </div>
    );
  };

  const loadLogs = useCallback(async () => {
    setLoading(true);
    setMessage("");
    try {
      const userId = selectedUserId ? Number(selectedUserId) : undefined;
      const invId = selectedInventoryId ? Number(selectedInventoryId) : undefined;

      if (target === "ALL" || target === "ITEMS") {
        const logs = await getItemAuditLogs(
          invId,
          userId,
          userScope || undefined,
          operation || undefined,
          fromDate || undefined,
          toDate || undefined
        );
        setItemLogs(logs);
      } else {
        setItemLogs([]);
      }

      if (target === "ALL" || target === "INVENTORIES") {
        const logs = await getInventoryAuditLogs(
          invId,
          userId,
          userScope || undefined,
          operation || undefined,
          undefined,
          fromDate || undefined,
          toDate || undefined
        );
        setInventoryLogs(logs);
      } else {
        setInventoryLogs([]);
      }
    } catch {
      setMessage("Errore nel caricamento audit logs");
    } finally {
      setLoading(false);
    }
  }, [target, selectedInventoryId, selectedUserId, userScope, operation, fromDate, toDate]);

  const loadUsers = useCallback(async () => {
    try {
      const list = await getUsers();
      setUsers(list);
    } catch {
      setUsers([]);
    }
  }, []);

  const loadInventories = useCallback(async () => {
    try {
      const [invList, chkList] = await Promise.all([
        getInventories(),
        getChecklists(),
      ]);
      const combined: InventoryOption[] = [
        ...invList.map((i) => ({ id: i.id, name: i.name, type: "INVENTORY" as const })),
        ...chkList.map((c) => ({ id: c.id, name: c.name, type: "CHECKLIST" as const })),
      ].sort((a, b) => a.name.localeCompare(b.name));
      setInventories(combined);
    } catch {
      setInventories([]);
    }
  }, []);

  const loadRetention = useCallback(async () => {
    try {
      const setting = await getSetting("AUDIT_RETENTION_DAYS");
      setRetentionDays(setting.value || "90");
    } catch {
      setRetentionDays("90");
    }
  }, []);

  useEffect(() => {
    loadUsers();
    loadInventories();
    loadRetention();
    loadLogs();
  }, [loadUsers, loadInventories, loadRetention, loadLogs]);

  const onChangeSelectedUser = (value: string) => {
    setSelectedUserId(value);
    if (value) {
      setUserScope("");
    }
  };

  const onChangeUserScope = (value: UserScopeFilter) => {
    setUserScope(value);
    if (value) {
      setSelectedUserId("");
    }
  };

  const saveRetention = async () => {
    const parsed = Number(retentionDays);
    if (!Number.isInteger(parsed) || parsed <= 0) {
      setMessage("AUDIT_RETENTION_DAYS deve essere un intero positivo");
      return;
    }

    try {
      await setSetting("AUDIT_RETENTION_DAYS", String(parsed));
      setMessage("Retention audit aggiornata con successo");
    } catch {
      setMessage("Errore durante il salvataggio della retention audit");
    }
  };

  const applyPreset = (preset: "24h" | "7d" | "30d" | "all") => {
    const now = new Date();
    if (preset === "all") {
      setFromDate("");
      setToDate("");
      return;
    }

    const from = new Date(now);
    if (preset === "24h") {
      from.setHours(from.getHours() - 24);
    } else if (preset === "7d") {
      from.setDate(from.getDate() - 7);
    } else {
      from.setMonth(from.getMonth() - 1);
    }

    setFromDate(toLocalInputValue(from));
    setToDate(toLocalInputValue(now));
  };

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Audit</h2>

      <div className="border rounded p-4 space-y-3">
        <h3 className="font-semibold">Retention storico audit</h3>
        <p className="text-sm text-gray-600 dark:text-gray-300">
          I record di audit orfani piu vecchi di questo valore verranno puliti dal job schedulato.
        </p>
        <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
          <input
            type="number"
            min={1}
            value={retentionDays}
            onChange={(e) => setRetentionDays(e.target.value)}
            className="border rounded px-2 py-1 w-36"
          />
          <span className="text-sm text-gray-600 dark:text-gray-300">giorni</span>
          <button
            onClick={saveRetention}
            className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            Salva
          </button>
        </div>
      </div>

      <div className="border rounded p-4 space-y-3">
        <h3 className="font-semibold">Audit logs</h3>

        <div className="flex flex-wrap gap-2">
          <select
            value={target}
            onChange={(e) => setTarget(e.target.value as TargetFilter)}
            className="border rounded px-2 py-1"
          >
            <option value="ALL">Tutti</option>
            <option value="ITEMS">Solo item</option>
            <option value="INVENTORIES">Solo inventari/liste</option>
          </select>

          <select
            value={selectedInventoryId}
            onChange={(e) => setSelectedInventoryId(e.target.value)}
            className="border rounded px-2 py-1"
          >
            <option value="">Inventario/Lista: tutti</option>
            {inventories.map((inv) => (
              <option key={`${inv.type}-${inv.id}`} value={String(inv.id)}>
                {inv.type === "CHECKLIST" ? "📝" : "📦"} {inv.name} (#{inv.id})
              </option>
            ))}
          </select>

          <select
            value={operation}
            onChange={(e) => setOperation(e.target.value as OperationFilter)}
            className="border rounded px-2 py-1"
          >
            <option value="">Operazioni: tutte</option>
            <option value="CREATE">CREATE</option>
            <option value="UPDATE">UPDATE</option>
            <option value="DELETE">DELETE</option>
          </select>

          <select
            value={selectedUserId}
            onChange={(e) => onChangeSelectedUser(e.target.value)}
            className="border rounded px-2 py-1"
          >
            <option value="">Utente: tutti</option>
            {users.map((user) => (
              <option key={user.id} value={String(user.id)}>
                {user.username} (id {user.id})
              </option>
            ))}
          </select>

          <select
            value={userScope}
            onChange={(e) => onChangeUserScope(e.target.value as UserScopeFilter)}
            className="border rounded px-2 py-1"
          >
            <option value="">Stato utente: tutti</option>
            <option value="active">Solo utente esistente</option>
            <option value="none">Solo senza utente</option>
            <option value="deleted">Solo utente eliminato/non risolto</option>
          </select>

          <button
            onClick={loadLogs}
            className="px-3 py-1 bg-purple-500 text-white rounded hover:bg-purple-600"
          >
            Aggiorna
          </button>
        </div>

        <div className="flex flex-col md:flex-row gap-2 md:items-end">
          <div className="flex flex-col">
            <label className="text-sm">Da</label>
            <input
              type="datetime-local"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
              className="border rounded px-2 py-1"
            />
          </div>
          <div className="flex flex-col">
            <label className="text-sm">A</label>
            <input
              type="datetime-local"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
              className="border rounded px-2 py-1"
            />
          </div>
          <button
            onClick={() => {
              setFromDate("");
              setToDate("");
            }}
            className="px-3 py-1 bg-gray-500 text-white rounded hover:bg-gray-600"
          >
            Reset periodo
          </button>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => applyPreset("24h")}
            className="px-3 py-1 bg-gray-200 dark:bg-gray-700 rounded hover:bg-gray-300 dark:hover:bg-gray-600 text-sm"
          >
            Ultime 24h
          </button>
          <button
            onClick={() => applyPreset("7d")}
            className="px-3 py-1 bg-gray-200 dark:bg-gray-700 rounded hover:bg-gray-300 dark:hover:bg-gray-600 text-sm"
          >
            Ultimi 7 giorni
          </button>
          <button
            onClick={() => applyPreset("30d")}
            className="px-3 py-1 bg-gray-200 dark:bg-gray-700 rounded hover:bg-gray-300 dark:hover:bg-gray-600 text-sm"
          >
            Ultimi 30 giorni
          </button>
          <button
            onClick={() => applyPreset("all")}
            className="px-3 py-1 bg-gray-200 dark:bg-gray-700 rounded hover:bg-gray-300 dark:hover:bg-gray-600 text-sm"
          >
            Tutto
          </button>
        </div>

        {loading && <p className="text-sm text-gray-500">Caricamento logs...</p>}

        {!loading && (target === "ALL" || target === "ITEMS") && (
          <div className="space-y-2">
            <h4 className="font-semibold">Item logs ({sortedItemLogs.length})</h4>
            <div className="max-h-72 overflow-auto border rounded">
              <table className="min-w-full text-sm">
                <thead className="bg-gray-100 dark:bg-gray-800">
                  <tr>
                    <th className="text-left p-2">Quando</th>
                    <th className="text-left p-2">Operazione</th>
                    <th className="text-left p-2">Inventario/Lista</th>
                    <th className="text-left p-2">Item</th>
                    <th className="text-left p-2">Utente</th>
                    <th className="text-left p-2">Versione</th>
                    <th className="text-left p-2">Modifiche</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedItemLogs.map((log) => (
                    <tr key={`item-${log.id}`} className="border-t">
                      <td className="p-2">{new Date(log.changed_at).toLocaleString()}</td>
                      <td className="p-2">{log.operation}</td>
                      <td className="p-2">
                        {(() => {
                          const path = getInventoryPath(log.inventory_type, log.inventory_id);
                          const label = `${getInventoryTypeIcon(log.inventory_type)} #${log.inventory_id} - ${log.inventory_name || "-"}`;
                          return path ? (
                            <Link to={path} className="text-blue-600 hover:underline dark:text-blue-400">
                              {label}
                            </Link>
                          ) : (
                            <span>{label}</span>
                          );
                        })()}
                      </td>
                      <td className="p-2">#{log.item_id} - {log.name}</td>
                      <td className="p-2">{log.changed_by_username || "-"}</td>
                      <td className="p-2">v{log.version_num}</td>
                      <td className="p-2">{renderDiff(log)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {!loading && (target === "ALL" || target === "INVENTORIES") && (
          <div className="space-y-2">
            <h4 className="font-semibold">Inventario/lista logs ({sortedInventoryLogs.length})</h4>
            <div className="max-h-72 overflow-auto border rounded">
              <table className="min-w-full text-sm">
                <thead className="bg-gray-100 dark:bg-gray-800">
                  <tr>
                    <th className="text-left p-2">Quando</th>
                    <th className="text-left p-2">Operazione</th>
                    <th className="text-left p-2">Entita</th>
                    <th className="text-left p-2">Utente</th>
                    <th className="text-left p-2">Versione</th>
                    <th className="text-left p-2">Modifiche</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedInventoryLogs.map((log) => (
                    <tr key={`inv-${log.id}`} className="border-t">
                      <td className="p-2">{new Date(log.changed_at).toLocaleString()}</td>
                      <td className="p-2">{log.operation}</td>
                      <td className="p-2">
                        {(() => {
                          const path = getInventoryPath(log.type, log.inventory_id);
                          const label = `${getInventoryTypeIcon(log.type)} #${log.inventory_id} - ${log.name}`;
                          return path ? (
                            <Link to={path} className="text-blue-600 hover:underline dark:text-blue-400">
                              {label}
                            </Link>
                          ) : (
                            <span>{label}</span>
                          );
                        })()}
                      </td>
                      <td className="p-2">{log.changed_by_username || "-"}</td>
                      <td className="p-2">v{log.version_num}</td>
                      <td className="p-2">{renderDiff(log)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {message && (
        <p className={`text-sm ${message.toLowerCase().includes("errore") ? "text-red-600" : "text-green-600"}`}>
          {message}
        </p>
      )}
    </div>
  );
}
