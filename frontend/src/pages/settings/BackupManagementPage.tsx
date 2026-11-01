import { useEffect, useMemo, useState } from "react";
import {
  listBackups,
  getBackupCompatibilityMap,
  createBackup,
  downloadBackup,
  deleteBackup,
  deleteBackupsBulk,
  restoreBackup,
  restoreBackupGuided,
  uploadBackup,
  getBackupSchedule,
  getSetting
} from "../../api";
import BackupScheduleManager from "./BackupScheduleManager";
import { useBottomSheetDrag } from "../../components/useBottomSheetDrag";

export default function BackupManagementPage() {
  const [backups, setBackups] = useState<{
    filename: string;
    size: number;
    modified: string;
    has_metadata?: boolean;
    db_alembic_version?: string | null;
    db_alembic_version_label?: string | null;
    current_db_alembic_version?: string | null;
    current_db_alembic_version_label?: string | null;
    restorable_on_current_db?: boolean;
    restore_compatibility?: {
      compatible?: boolean;
      strategy?: string;
      reason?: string;
    };
    metadata?: {
      format?: string;
      created_at?: string;
      db_alembic_version?: string;
    } | null;
  }[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string>("");
  const [messageType, setMessageType] = useState<"success" | "error" | "">("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [showScheduleModal, setShowScheduleModal] = useState(false);
  const [scheduleConfig, setScheduleConfig] = useState<{
    frequency: string;
    interval_days?: number;
    interval_hours?: number;
    interval_minutes?: number;
    retention: number;
  } | null>(null);
  const [lastRun, setLastRun] = useState<string | null>(null);
  const [compatibilityMap, setCompatibilityMap] = useState<{
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
  } | null>(null);

  const [filterText, setFilterText] = useState("");
  const [backupTypeFilter, setBackupTypeFilter] = useState<"all" | "manual" | "auto" | "uploaded">("all");
  const [sortField, setSortField] = useState<"filename" | "modified" | "size">("modified");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [selectedBackupNames, setSelectedBackupNames] = useState<string[]>([]);
  const [restoreTarget, setRestoreTarget] = useState<{
    filename: string;
    metadata?: {
      format?: string;
      created_at?: string;
      db_alembic_version?: string;
    } | null;
    db_alembic_version?: string | null;
    db_alembic_version_label?: string | null;
    current_db_alembic_version?: string | null;
    current_db_alembic_version_label?: string | null;
    restorable_on_current_db?: boolean;
    restore_compatibility?: {
      compatible?: boolean;
      strategy?: string;
      reason?: string;
    };
  } | null>(null);
  const scheduleSheetDrag = useBottomSheetDrag(() => setShowScheduleModal(false));
  const restoreSheetDrag = useBottomSheetDrag(() => setRestoreTarget(null));

  const revisionDisplay = (revision?: string | null): string => {
    if (!revision) return "n/d";
    const label = compatibilityMap?.revision_labels?.[revision];
    return label || revision;
  };

  useEffect(() => {
    fetchBackups();
  }, []);

  useEffect(() => {
    const fetchCompatibilityMap = async () => {
      try {
        const data = await getBackupCompatibilityMap();
        setCompatibilityMap(data);
      } catch (error) {
        console.error("Errore nel caricamento mappa compatibilita backup:", error);
        setCompatibilityMap(null);
      }
    };

    fetchCompatibilityMap();
  }, []);

  useEffect(() => {
    const fetchSchedule = async () => {
      try {
        const settings = await getBackupSchedule();
        if (settings && typeof settings === "object") {
          setScheduleConfig({
            frequency: settings.frequency || "none",
            interval_days: settings.interval_days || 0,
            interval_hours: settings.interval_hours || 0,
            interval_minutes: settings.interval_minutes || 0,
            retention: settings.retention || 7
          });
        } else {
          setScheduleConfig(null);
        }
        // Caricamento di lastRunSetting separato dal controllo su settings
        try {
          const lastRunSetting = await getSetting("BACKUP_LAST_RUN");
          if (typeof lastRunSetting === "string") {
            setLastRun(new Date(lastRunSetting).toLocaleString());
          } else if (lastRunSetting && typeof lastRunSetting === "object" && "value" in lastRunSetting) {
            setLastRun(new Date(lastRunSetting.value).toLocaleString());
          }
        } catch (err) {
          console.error("Errore nel caricamento di BACKUP_LAST_RUN:", err);
        }
      } catch (error) {
        console.error("Errore nel caricamento della schedulazione:", error);
      }
    };
    fetchSchedule();
  }, []);

  useEffect(() => {
    if (message !== "") {
      const timer = setTimeout(() => {
        setMessage("");
        setMessageType("");
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [message]);

  const fetchBackups = async () => {
    setLoading(true);
    try {
      const data = await listBackups();
      setBackups(
        (
          data as {
            filename: string;
            size: number;
            modified: string;
            has_metadata?: boolean;
            db_alembic_version?: string | null;
            db_alembic_version_label?: string | null;
            current_db_alembic_version?: string | null;
            current_db_alembic_version_label?: string | null;
            restorable_on_current_db?: boolean;
            restore_compatibility?: {
              compatible?: boolean;
              strategy?: string;
              reason?: string;
            };
            metadata?: {
              format?: string;
              created_at?: string;
              db_alembic_version?: string;
            } | null;
          }[]
        ).sort((a, b) => new Date(b.modified).getTime() - new Date(a.modified).getTime())
      );
    } catch (error) {
      console.error("Errore nel caricamento dei backup:", error);
    } finally {
      setLoading(false);
    }
  };

  const displayedBackups = useMemo(() => {
    return backups
      .filter((b) => {
        const matchText = b.filename.toLowerCase().includes(filterText.toLowerCase());
        const isAuto = b.filename.startsWith("auto_");
        const isUploaded = b.filename.startsWith("uploaded_");
        const matchType =
          backupTypeFilter === "all" ||
          (backupTypeFilter === "manual" && !isAuto && !isUploaded) ||
          (backupTypeFilter === "auto" && isAuto) ||
          (backupTypeFilter === "uploaded" && isUploaded);
        return matchText && matchType;
      })
      .sort((a, b) => {
        const aVal = a[sortField];
        const bVal = b[sortField];
        if (sortField === "modified") {
          return sortDirection === "asc"
            ? new Date(aVal).getTime() - new Date(bVal).getTime()
            : new Date(bVal).getTime() - new Date(aVal).getTime();
        }
        return sortDirection === "asc"
          ? aVal > bVal
            ? 1
            : -1
          : aVal < bVal
          ? 1
          : -1;
      });
  }, [backups, filterText, backupTypeFilter, sortField, sortDirection]);

  useEffect(() => {
    const available = new Set(displayedBackups.map((b) => b.filename));
    setSelectedBackupNames((prev) => prev.filter((name) => available.has(name)));
  }, [displayedBackups]);

  const createBackupLocal = async () => {
    setLoading(true);
    try {
      const success = await createBackup();
      if (success) {
        setMessage("Backup creato con successo!");
        setMessageType("success");
        fetchBackups();
      } else {
        setMessage("Errore nella creazione del backup.");
        setMessageType("error");
      }
    } catch (error) {
      console.error("Errore nella creazione del backup:", error);
      setMessage("Errore nella creazione del backup.");
      setMessageType("error");
    } finally {
      setLoading(false);
    }
  };

  const uploadBackupLocal = async () => {
    if (!selectedFile) {
      setMessage("Nessun file selezionato.");
      setMessageType("error");
      return;
    }
    setLoading(true);
    try {
      await uploadBackup(selectedFile);
      setMessage("Backup caricato con successo!");
      setMessageType("success");
      setSelectedFile(null);
      fetchBackups();
    } catch (error) {
      console.error("Errore nel caricamento del backup:", error);
      setMessage("Errore nel caricamento del backup.");
      setMessageType("error");
    } finally {
      setLoading(false);
    }
  };

  const downloadBackupLocal = (filename: string) => {
    downloadBackup(filename);
  };

  const deleteBackupLocal = async (filename: string) => {
    if (!window.confirm(`Sei sicuro di voler eliminare il backup ${filename}?`)) return;
    setLoading(true);
    try {
      await deleteBackup(filename);
      setMessage("Backup eliminato con successo!");
      setMessageType("success");
      fetchBackups();
    } catch (error) {
      console.error("Errore nell'eliminazione del backup:", error);
      setMessage("Errore nell'eliminazione del backup.");
      setMessageType("error");
    } finally {
      setLoading(false);
    }
  };

  const toggleBackupSelection = (filename: string) => {
    setSelectedBackupNames((prev) =>
      prev.includes(filename) ? prev.filter((f) => f !== filename) : [...prev, filename]
    );
  };

  const selectAllDisplayed = () => {
    setSelectedBackupNames(displayedBackups.map((b) => b.filename));
  };

  const clearSelection = () => {
    setSelectedBackupNames([]);
  };

  const downloadSelectedBackups = () => {
    if (selectedBackupNames.length === 0) return;
    selectedBackupNames.forEach((filename) => downloadBackupLocal(filename));
    setMessage(`Avviato download di ${selectedBackupNames.length} backup`);
    setMessageType("success");
  };

  const deleteSelectedBackups = async () => {
    if (selectedBackupNames.length === 0) return;
    if (!window.confirm(`Sei sicuro di voler eliminare ${selectedBackupNames.length} backup selezionati?`)) return;

    setLoading(true);
    try {
      const result = await deleteBackupsBulk(selectedBackupNames);
      const deletedCount = result.deleted.length;
      const skippedCount = result.missing.length + result.invalid.length;
      setMessage(
        skippedCount > 0
          ? `Eliminati ${deletedCount} backup. Saltati ${skippedCount} elementi non validi/non trovati.`
          : `Eliminati ${deletedCount} backup con successo!`
      );
      setMessageType(skippedCount > 0 ? "error" : "success");
      clearSelection();
      fetchBackups();
    } catch (error) {
      console.error("Errore nell'eliminazione massiva dei backup:", error);
      setMessage("Errore nell'eliminazione massiva dei backup.");
      setMessageType("error");
    } finally {
      setLoading(false);
    }
  };

  const restoreBackupLocal = async (filename: string) => {
    setLoading(true);
    try {
      await restoreBackup(filename);
      setMessage("Ripristino base avviato con successo!");
      setMessageType("success");
    } catch (error) {
      console.error("Errore nel ripristino del backup:", error);
      setMessage("Errore nel ripristino del backup.");
      setMessageType("error");
    } finally {
      setLoading(false);
    }
  };

  const restoreBackupAdvancedLocal = async (filename: string) => {
    const overwriteUsersRoles = window.confirm("Vuoi sovrascrivere anche utenti e ruoli?");
    const overwriteSettings = window.confirm("Vuoi sovrascrivere anche i settings?");

    let overwriteAdmin = false;
    if (overwriteUsersRoles) {
      overwriteAdmin = window.confirm("Per sovrascrivere utenti/ruoli devi sovrascrivere anche admin. Confermi?");
      if (!overwriteAdmin) {
        setMessage("Ripristino avanzato annullato: senza sovrascrivere admin non è possibile sovrascrivere utenti/ruoli.");
        setMessageType("error");
        return;
      }
    }

    setLoading(true);
    try {
      await restoreBackupGuided(filename, {
        mode: "advanced",
        overwrite_users_roles: overwriteUsersRoles,
        overwrite_settings: overwriteSettings,
        overwrite_admin: overwriteAdmin,
      });
      setMessage("Ripristino avanzato avviato con successo!");
      setMessageType("success");
    } catch (error) {
      console.error("Errore nel ripristino avanzato:", error);
      setMessage("Errore nel ripristino avanzato.");
      setMessageType("error");
    } finally {
      setLoading(false);
    }
  };

  const handleRestoreBaseFromModal = async () => {
    if (!restoreTarget) return;
    if (!window.confirm(`Confermi il ripristino BASE del backup ${restoreTarget.filename}?`)) return;
    await restoreBackupLocal(restoreTarget.filename);
    setRestoreTarget(null);
  };

  const handleRestoreAdvancedFromModal = async () => {
    if (!restoreTarget) return;
    if (!window.confirm(`Confermi il ripristino AVANZATO del backup ${restoreTarget.filename}?`)) return;
    await restoreBackupAdvancedLocal(restoreTarget.filename);
    setRestoreTarget(null);
  };

  const giorniSettimana = ["Domenica", "Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato"];

  return (
    <div className="min-w-0 max-w-full space-y-4 overflow-x-hidden p-4">
      <h2 className="text-lg font-semibold">Gestione Backup</h2>
      <div className="p-2 bg-gray-100 dark:bg-gray-800 rounded">
        <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center">
          <div>
            <p className="font-medium">Backup automatico:</p>
            <p className="text-sm text-gray-700 dark:text-white">
              {scheduleConfig && scheduleConfig.frequency !== "none"
                ? `Attivo - Frequenza: ${scheduleConfig.frequency} ${
                    scheduleConfig.frequency === "hourly"
                      ? `ogni ${scheduleConfig.interval_minutes ?? 60} minuti`
                      : scheduleConfig.frequency === "daily"
                        ? `alle ${scheduleConfig.interval_hours?.toString().padStart(2, "0")}:${scheduleConfig.interval_minutes?.toString().padStart(2, "0")}`
                        : scheduleConfig.frequency === "weekly"
                          ? ` giorno: ${giorniSettimana[scheduleConfig.interval_days ?? 0]} alle ${scheduleConfig.interval_hours ?? 0}:${scheduleConfig.interval_minutes ?? 0}`
                          : ""
                } - Retention: ${scheduleConfig.retention} backup${
                  lastRun ? ` - Ultimo backup: ${lastRun}` : ""
                }`
                : "Nessuna schedulazione configurata."}
            </p>
          </div>
          <button
            onClick={() => setShowScheduleModal(true)}
            className="mt-2 sm:mt-0 px-3 py-1 bg-yellow-600 text-white rounded hover:bg-yellow-700"
          >
            Modifica Schedulazione
          </button>
        </div>
      </div>
      <div className="flex flex-col sm:flex-row sm:items-center sm:space-x-2 space-y-2 sm:space-y-0">
        <input
          type="file"
          accept=".sql"
          onChange={(e) => setSelectedFile(e.target.files ? e.target.files[0] : null)}
          className="border border-gray-300 dark:border-gray-600 dark:bg-gray-800 rounded p-1"
        />
        <button
          onClick={uploadBackupLocal}
          disabled={loading || !selectedFile}
          className="px-3 py-1 bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50"
        >
          Carica Backup
          {loading && <span className="ml-2 animate-spin">⏳</span>}
        </button>
      </div>
      <button
        onClick={createBackupLocal}
        disabled={loading}
        className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
      >
        Crea Backup
        {loading && <span className="ml-2 animate-spin">⏳</span>}
      </button>

      <details className="border border-gray-200 dark:border-gray-700 rounded p-3 bg-gray-50 dark:bg-gray-800" open={false}>
        <summary className="cursor-pointer font-medium select-none">
          Mappa compatibilita versioni DB
        </summary>
        <div className="mt-3 space-y-3">
          {!compatibilityMap ? (
            <p className="text-sm text-gray-600 dark:text-gray-300">Mappa non disponibile.</p>
          ) : (
            <>
              <p className="text-xs text-gray-600 dark:text-gray-300">
                Cella verde: restore consentito dalla revisione sorgente (riga) alla revisione target (colonna).
              </p>
              <div className="overflow-auto border rounded">
                <table className="min-w-max text-xs">
                  <thead>
                    <tr className="bg-gray-100 dark:bg-gray-700">
                      <th className="sticky left-0 bg-gray-100 dark:bg-gray-700 p-2 text-left">Da \ A</th>
                      {compatibilityMap.revisions.map((revision) => (
                        <th key={`head-${revision}`} className="p-2 text-left whitespace-nowrap">{revisionDisplay(revision)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {compatibilityMap.matrix.map((row) => (
                      <tr key={`row-${row.source_revision}`} className="border-t border-gray-200 dark:border-gray-700">
                        <td className="sticky left-0 bg-white dark:bg-gray-900 p-2 font-semibold whitespace-nowrap">
                          {revisionDisplay(row.source_revision)}
                        </td>
                        {row.targets.map((cell) => (
                          <td
                            key={`cell-${row.source_revision}-${cell.target_revision}`}
                            className={`p-2 whitespace-nowrap ${
                              cell.compatible
                                ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
                                : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300"
                            }`}
                            title={`${cell.strategy || "n/a"} - ${cell.reason || ""}`}
                          >
                            {cell.compatible ? "SI" : "NO"}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div>
                <h4 className="text-sm font-semibold">Regole esplicite</h4>
                {compatibilityMap.explicit_rules.length === 0 ? (
                  <p className="text-xs text-gray-600 dark:text-gray-300">Nessuna regola esplicita.</p>
                ) : (
                  <ul className="mt-1 text-xs space-y-1">
                    {compatibilityMap.explicit_rules.map((rule, idx) => (
                      <li key={`rule-${idx}`}>
                        {rule.source_revision} → {rule.target_revision} ({rule.strategy || "n/a"}) - {rule.reason || ""}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </div>
      </details>

      {message && (
        <div className={`fixed bottom-4 right-4 z-50 p-3 rounded shadow-lg text-white ${messageType === "success" ? "bg-green-500" : "bg-red-500"} transition-opacity duration-1000`}>
          {message}
        </div>
      )}

      {/* Filtri e ordinamenti */}
      <div className="flex flex-col md:flex-row md:items-end md:space-x-4 space-y-2 md:space-y-0">
        <div>
          <label className="block text-sm font-medium">Filtra per nome:</label>
          <input
            type="text"
            placeholder="Filtra per nome..."
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setFilterText("");
            }}
            className="border border-gray-300 dark:border-gray-600 dark:bg-gray-800 rounded p-1 w-full sm:w-64"
          />
        </div>
        <div>
          <label className="block text-sm font-medium">Visualizza:</label>
          <select
            value={backupTypeFilter}
            onChange={(e) => setBackupTypeFilter(e.target.value as "all" | "manual" | "auto" | "uploaded")}
            className="border border-gray-300 dark:border-gray-600 dark:bg-gray-800 rounded px-2 py-1"
          >
            <option value="all">Tutti</option>
            <option value="manual">Manuali</option>
            <option value="auto">Automatici</option>
            <option value="uploaded">Caricati</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium">Ordina per:</label>
          <select
            value={sortField}
            onChange={(e) => setSortField(e.target.value as "filename" | "modified" | "size")}
            className="border border-gray-300 dark:border-gray-600 dark:bg-gray-800 rounded px-2 py-1"
          >
            <option value="modified">Data</option>
            <option value="filename">Nome</option>
            <option value="size">Dimensione</option>
          </select>
          <button
            onClick={() => setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"))}
            className="ml-2 px-2 py-1 border border-gray-300 dark:border-gray-600 dark:bg-gray-800 rounded"
          >
            {sortDirection === "asc" ? "↑" : "↓"}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={selectAllDisplayed}
          className="px-3 py-1 bg-gray-200 dark:bg-gray-700 rounded hover:bg-gray-300 dark:hover:bg-gray-600 text-sm"
        >
          Seleziona tutti (visibili)
        </button>
        <button
          onClick={clearSelection}
          className="px-3 py-1 bg-gray-200 dark:bg-gray-700 rounded hover:bg-gray-300 dark:hover:bg-gray-600 text-sm"
        >
          Deseleziona
        </button>
        <button
          onClick={downloadSelectedBackups}
          disabled={selectedBackupNames.length === 0}
          className="px-3 py-1 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
        >
          Scarica selezionati ({selectedBackupNames.length})
        </button>
        <button
          onClick={deleteSelectedBackups}
          disabled={selectedBackupNames.length === 0}
          className="px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
        >
          Elimina selezionati ({selectedBackupNames.length})
        </button>
      </div>

      <ul className="space-y-2">
        {displayedBackups.map((backup) => {
            const isAuto = backup.filename.startsWith("auto_");
            const isUploaded = backup.filename.startsWith("uploaded_");
            return (
              <li
                key={backup.filename}
                className={`flex min-w-0 flex-col overflow-hidden border p-2 rounded sm:flex-row sm:justify-between sm:items-center ${
                  isAuto
                    ? "bg-yellow-50 border-yellow-400 dark:bg-amber-950/30 dark:border-amber-700/60 dark:text-gray-100"
                    : "border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800/40 dark:text-gray-100"
                }`}
              >
                <div className="flex min-w-0 w-full items-start gap-3 sm:flex-1">
                  <input
                    type="checkbox"
                    checked={selectedBackupNames.includes(backup.filename)}
                    onChange={() => toggleBackupSelection(backup.filename)}
                    className="mt-1 w-4 h-4"
                    title={`Seleziona ${backup.filename}`}
                  />
                  <div className="min-w-0 flex-1">
                  <div className="break-all font-medium">{backup.filename}
                    {isAuto && <span className="inline-block text-xs font-semibold text-yellow-800 bg-yellow-200 dark:bg-amber-900/50 dark:text-amber-200 rounded px-2 py-0.5 ml-2">Automatico</span>}
                    {isUploaded && <span className="inline-block text-xs font-semibold text-blue-800 bg-blue-100 dark:bg-blue-900/50 dark:text-blue-200 rounded px-2 py-0.5 ml-2">Caricato</span>}
                  </div>
                  <div className="text-sm text-gray-600 dark:text-gray-400">
                    {(backup.size / 1024).toFixed(2)} KB - {new Date(backup.modified).toLocaleString()}
                  </div>
                  <div className="mt-1 space-y-1 break-words text-xs text-gray-600 dark:text-gray-300">
                    <div>
                      <span className="font-semibold">Formato:</span>{" "}
                      {backup.metadata?.format || (backup.has_metadata ? "n/d" : "legacy/no-metadata")}
                    </div>
                    <div>
                      <span className="font-semibold">Revisione backup:</span>{" "}
                      {backup.db_alembic_version_label || revisionDisplay(backup.db_alembic_version)}
                    </div>
                    <div>
                      <span className="font-semibold">Revisione DB corrente:</span>{" "}
                      {backup.current_db_alembic_version_label || revisionDisplay(backup.current_db_alembic_version)}
                    </div>
                    <div>
                      <span className="font-semibold">Ripristinabile:</span>{" "}
                      {backup.restorable_on_current_db ? (
                        <span className="text-green-700 dark:text-green-400 font-semibold">SI</span>
                      ) : (
                        <span className="text-red-700 dark:text-red-400 font-semibold">NO</span>
                      )}
                    </div>
                    {backup.restore_compatibility?.strategy && (
                      <div>
                        <span className="font-semibold">Strategia:</span>{" "}
                        {backup.restore_compatibility.strategy}
                      </div>
                    )}
                    {backup.restore_compatibility?.reason && (
                      <div>
                        <span className="font-semibold">Motivo:</span>{" "}
                        {backup.restore_compatibility.reason}
                      </div>
                    )}
                    {backup.metadata?.created_at && (
                      <div>
                        <span className="font-semibold">Creato (meta):</span>{" "}
                        {new Date(backup.metadata.created_at).toLocaleString()}
                      </div>
                    )}
                  </div>
                  </div>
                </div>
                <div className="flex flex-col sm:flex-row gap-2 mt-2 sm:mt-0">
                  <button
                    onClick={() => downloadBackupLocal(backup.filename)}
                    className="px-2 py-1 text-sm bg-green-600 text-white rounded hover:bg-green-700"
                  >
                    Scarica
                  </button>
                  <button
                    onClick={() =>
                      setRestoreTarget({
                        filename: backup.filename,
                        metadata: backup.metadata,
                        db_alembic_version: backup.db_alembic_version,
                        db_alembic_version_label: backup.db_alembic_version_label,
                        current_db_alembic_version: backup.current_db_alembic_version,
                        current_db_alembic_version_label: backup.current_db_alembic_version_label,
                        restorable_on_current_db: backup.restorable_on_current_db,
                        restore_compatibility: backup.restore_compatibility,
                      })
                    }
                    className="px-2 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
                  >
                    Ripristina
                  </button>
                  <button
                    onClick={() => deleteBackupLocal(backup.filename)}
                    className="px-2 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700"
                  >
                    Elimina
                  </button>
                </div>
              </li>
            );
          })}
      </ul>
      {showScheduleModal && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/30 sm:items-center sm:p-4">
          <div style={{ transform: `translateY(${scheduleSheetDrag.offset}px)`, transition: scheduleSheetDrag.isDragging ? 'none' : 'transform 220ms ease-out' }} className="max-h-[90dvh] w-full overflow-y-auto rounded-t-3xl bg-white p-5 pb-[calc(env(safe-area-inset-bottom)+1rem)] shadow-2xl dark:bg-gray-900 sm:max-w-lg sm:rounded-xl sm:p-4 sm:pb-4">
            <button type="button" aria-label="Chiudi o trascina verso il basso" {...scheduleSheetDrag.gripProps} className="mx-auto mb-3 flex h-8 w-16 touch-none items-center justify-center sm:hidden"><span className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" aria-hidden="true" /></button>
            <BackupScheduleManager
              currentConfig={scheduleConfig}
              onSaved={() => {
                setShowScheduleModal(false);
                fetchBackups();
              }}
            />
            <div className="text-right mt-4">
              <button
                onClick={() => setShowScheduleModal(false)}
                className="px-3 py-1 bg-gray-500 text-white rounded hover:bg-gray-600"
              >
                Chiudi
              </button>
            </div>
          </div>
        </div>
      )}

      {restoreTarget && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/30 sm:items-center sm:p-4">
          <div style={{ transform: `translateY(${restoreSheetDrag.offset}px)`, transition: restoreSheetDrag.isDragging ? 'none' : 'transform 220ms ease-out' }} className="max-h-[92dvh] w-full space-y-4 overflow-y-auto rounded-t-3xl bg-white p-5 pb-[calc(env(safe-area-inset-bottom)+1rem)] shadow-2xl dark:bg-gray-900 sm:max-w-xl sm:rounded-xl sm:p-4 sm:pb-4">
            <button type="button" aria-label="Chiudi o trascina verso il basso" {...restoreSheetDrag.gripProps} className="mx-auto mb-3 flex h-8 w-16 touch-none items-center justify-center sm:hidden"><span className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" aria-hidden="true" /></button>
            <h3 className="text-lg font-semibold">Ripristino backup</h3>
            <p className="text-sm break-all">
              <span className="font-semibold">File:</span> {restoreTarget.filename}
            </p>

            <div className="text-sm space-y-1 border rounded p-3 bg-gray-50 dark:bg-gray-800">
              <p>
                <span className="font-semibold">Formato:</span> {restoreTarget.metadata?.format || "n/d"}
              </p>
              <p>
                <span className="font-semibold">Revisione backup:</span> {restoreTarget.db_alembic_version_label || revisionDisplay(restoreTarget.db_alembic_version)}
              </p>
              <p>
                <span className="font-semibold">Revisione DB corrente:</span> {restoreTarget.current_db_alembic_version_label || revisionDisplay(restoreTarget.current_db_alembic_version)}
              </p>
              <p>
                <span className="font-semibold">Creato (meta):</span>{" "}
                {restoreTarget.metadata?.created_at ? new Date(restoreTarget.metadata.created_at).toLocaleString() : "n/d"}
              </p>
              <p>
                <span className="font-semibold">Ripristinabile:</span>{" "}
                {restoreTarget.restorable_on_current_db ? (
                  <span className="text-green-700 dark:text-green-400 font-semibold">SI</span>
                ) : (
                  <span className="text-red-700 dark:text-red-400 font-semibold">NO</span>
                )}
              </p>
              {restoreTarget.restore_compatibility?.strategy && (
                <p>
                  <span className="font-semibold">Strategia:</span> {restoreTarget.restore_compatibility.strategy}
                </p>
              )}
              {restoreTarget.restore_compatibility?.reason && (
                <p>
                  <span className="font-semibold">Motivo:</span> {restoreTarget.restore_compatibility.reason}
                </p>
              )}
            </div>

            <div className="text-sm space-y-2 border rounded p-3 bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800">
              <p className="font-semibold">Differenza tra ripristino Base e Avanzato</p>
              <p>
                <span className="font-semibold">Base:</span> ripristina i dati applicativi principali (inventari,
                elementi, condivisioni, metadati, filtri) mantenendo utenti/ruoli e impostazioni correnti.
              </p>
              <p>
                <span className="font-semibold">Avanzato:</span> stesso ripristino dei dati principali, con richieste
                aggiuntive per decidere se sovrascrivere anche utenti/ruoli e impostazioni.
              </p>
              <p className="text-xs text-gray-700 dark:text-gray-300">
                Nota: se scegli di sovrascrivere utenti/ruoli, devi confermare anche la sovrascrittura dell'utente
                admin per mantenere la coerenza.
              </p>
            </div>

            <div className="flex flex-wrap justify-end gap-2">
              <button
                onClick={handleRestoreBaseFromModal}
                disabled={!restoreTarget.restorable_on_current_db}
                className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700"
              >
                Base (dati core)
              </button>
              <button
                onClick={handleRestoreAdvancedFromModal}
                disabled={!restoreTarget.restorable_on_current_db}
                className="px-3 py-1 bg-purple-600 text-white rounded hover:bg-purple-700"
              >
                Avanzato (con opzioni)
              </button>
              <button
                onClick={() => setRestoreTarget(null)}
                className="px-3 py-1 bg-gray-500 text-white rounded hover:bg-gray-600"
              >
                Annulla
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
