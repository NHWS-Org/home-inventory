import { useEffect, useState, type FormEvent } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import {
  cleanupSecuritySessions, getSecurityAudit, getSecurityStatus, getSecuritySessions, performSecurityAction,
  type SecurityAuditEntry, type SecurityStatus, type SecuritySession,
} from "../../api";
import { useAuth } from "../../useAuth";

type Action = "revoke-sessions" | "rotate-key";

export default function SecuritySettings() {
  const { setUser } = useAuth();
  const navigate = useNavigate();
  const [status, setStatus] = useState<SecurityStatus | null>(null);
  const [audit, setAudit] = useState<SecurityAuditEntry[]>([]);
  const [sessions, setSessions] = useState<SecuritySession[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState("");
  const [cleanupNotice, setCleanupNotice] = useState("");
  const [action, setAction] = useState<Action | null>(null);
  const [password, setPassword] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([getSecurityStatus(), getSecurityAudit()])
      .then(([configuration, entries]) => {
        if (active) {
          setStatus(configuration);
          setAudit(entries);
        }
      })
      .catch(() => {
        if (active) setError("Errore nel caricamento della configurazione di sicurezza.");
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    getSecuritySessions().then((entries) => {
      if (active) setSessions(entries);
    }).catch(() => {
      if (active) setSessionsError("Errore nel caricamento delle sessioni.");
    }).finally(() => {
      if (active) setSessionsLoading(false);
    });
    return () => { active = false; };
  }, []);

  async function refreshSessions() {
    setSessionsLoading(true);
    setSessionsError("");
    try {
      setSessions(await getSecuritySessions());
    } catch {
      setSessionsError("Errore nel caricamento delle sessioni.");
    } finally {
      setSessionsLoading(false);
    }
  }

  function chooseAction(next: Action | null) {
    setAction(next);
    setPassword("");
    setConfirmed(false);
    setError("");
  }

  async function cleanupSessions() {
    if (busy || sessionsLoading) return;
    setBusy(true);
    setSessionsError("");
    setCleanupNotice("");
    try {
      const deleted = await cleanupSecuritySessions();
      setCleanupNotice(`Sessioni eliminate: ${deleted}. Tutti i dispositivi attivi restano connessi.`);
      await refreshSessions();
    } catch {
      setSessionsError("Pulizia delle sessioni non riuscita. Riprovare.");
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!action || !confirmed || busy) return;
    setBusy(true);
    setError("");
    try {
      await performSecurityAction(action, password);
      localStorage.removeItem("access_token");
      setUser(null);
      navigate("/login", { replace: true });
    } catch (failure) {
      const detail = axios.isAxiosError<{ detail?: string }>(failure) ? failure.response?.data.detail : null;
      setError(detail || "Operazione non riuscita. Verificare lo stato e i log prima di riprovare.");
    } finally {
      setPassword("");
      setBusy(false);
    }
  }

  return (
    <section className="p-4 space-y-4">
      <h2 className="text-lg font-semibold">Sicurezza dell'installazione</h2>
      <p>La revoca globale e la rotazione della chiave disconnettono tutti gli utenti, incluso questo account. La semplice pulizia no. Password e dati restano invariati.</p>
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 id="security-sessions-heading" className="font-semibold">
            Sessioni non revocate{!sessionsLoading && !sessionsError && ` (${sessions.length})`}
          </h3>
          <button type="button" onClick={refreshSessions} disabled={sessionsLoading || busy}
            className="min-h-11 border rounded px-3 py-2 disabled:opacity-50">
            {sessionsLoading ? "Caricamento..." : "Aggiorna elenco"}
          </button>
        </div>
        <button type="button" onClick={cleanupSessions} disabled={busy || sessionsLoading}
          className="min-h-11 border rounded px-3 py-2 disabled:opacity-50">
          Pulisci sessioni scadute / disconnesse di tutti gli utenti
        </button>
        <p className="text-sm">La pulizia elimina subito solo sessioni scadute o revocate, senza password e senza disconnettere nessuno. Include anche quelle revocate, non mostrate nell'elenco.</p>
        {cleanupNotice && <p role="status" className="text-sm">{cleanupNotice}</p>}
        <p className="text-sm">La revoca riguarda tutte queste sessioni, anche quelle scadute. L'elenco fotografa lo stato al caricamento; altri accessi possono avvenire nel frattempo.</p>
        <p className="text-sm">Eventuali token precedenti al tracciamento dei dispositivi non sono elencati, ma vengono comunque invalidati.</p>
        {sessionsError && <p role="alert" className="text-red-600">{sessionsError}</p>}
        <div role="region" aria-labelledby="security-sessions-heading" tabIndex={0}
          aria-busy={sessionsLoading}
          className="max-h-80 sm:max-h-96 overflow-y-auto overscroll-contain border rounded p-3 focus-visible:outline-2 focus-visible:outline-blue-500">
          {sessionsLoading ? <p role="status">Caricamento sessioni...</p> : sessionsError ? (
            <p>Elenco non disponibile. Premi Aggiorna elenco per riprovare.</p>
          ) : sessions.length === 0 ? <p>Nessuna sessione non revocata.</p> : (
            <ul className="space-y-3">
              {sessions.map((session) => (
                <li key={session.id} className="border rounded p-3 space-y-1 [overflow-wrap:anywhere]">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold min-w-0 max-w-full">{session.username}</span>
                    {session.is_current && <span className="text-sm border rounded px-2 py-1">Questa sessione</span>}
                    <span className="text-sm">{session.is_expired ? "Scaduta" : "Non scaduta"}</span>
                  </div>
                  <p className="text-sm">{[session.device_type, session.browser, session.operating_system].filter(Boolean).join(" · ") || "Dispositivo sconosciuto"}</p>
                  <dl className="text-sm grid gap-1 sm:grid-cols-2">
                    <div><dt className="font-medium">Accesso</dt><dd>{new Date(`${session.created_at}Z`).toLocaleString()}</dd></div>
                    <div><dt className="font-medium">Scadenza</dt><dd>{new Date(`${session.expires_at}Z`).toLocaleString()}</dd></div>
                  </dl>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="space-y-2">
        <p>Revoca tutte le sessioni senza cambiare la chiave di firma.</p>
        <button type="button" disabled={!status || busy} onClick={() => chooseAction("revoke-sessions")}
          className="bg-red-700 text-white rounded px-3 py-2 disabled:opacity-50">
          Revoca tutte le sessioni
        </button>
      </div>
      <div className="space-y-2">
        <p>Ruota la chiave automatica e revoca tutte le sessioni. La nuova chiave non viene mostrata.</p>
        {status?.rotation_message && <p role="status">{status.rotation_message}</p>}
        <button type="button" disabled={!status?.can_rotate || busy} onClick={() => chooseAction("rotate-key")}
          className="bg-red-700 text-white rounded px-3 py-2 disabled:opacity-50">
          Ruota la chiave automatica
        </button>
      </div>
      {action && (
        <form onSubmit={submit} className="border rounded p-4 space-y-3">
          <h3 className="font-semibold">{action === "rotate-key" ? "Conferma rotazione chiave" : "Conferma revoca sessioni"}</h3>
          <label className="block" htmlFor="security-password">Password attuale dell'amministratore</label>
          <input id="security-password" type="password" autoComplete="current-password" required
            maxLength={1024} value={password} disabled={busy} onChange={(event) => setPassword(event.target.value)}
            className="border rounded px-2 py-1" />
          <label className="flex items-center gap-2">
            <input type="checkbox" required checked={confirmed} disabled={busy}
              onChange={(event) => setConfirmed(event.target.checked)} />
            Confermo la disconnessione di tutti gli utenti, incluso il mio account.
          </label>
          <div className="flex gap-2">
            <button type="submit" disabled={!confirmed || !password || busy}
              className="bg-red-700 text-white rounded px-3 py-2 disabled:opacity-50">
              {busy ? "Operazione in corso..." : "Conferma operazione"}
            </button>
            <button type="button" disabled={busy} onClick={() => chooseAction(null)}>Annulla</button>
          </div>
        </form>
      )}
      {error && <p role="alert" className="text-red-600">{error}</p>}
      <h3 className="font-semibold">Ultime operazioni di sicurezza</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead><tr><th>Data (UTC)</th><th>Amministratore</th><th>Azione</th><th>Esito</th><th>Sessioni revocate</th></tr></thead>
          <tbody>{audit.map((entry) => (
            <tr key={entry.id}>
              <td>{entry.created_at}</td><td>{entry.actor_username}</td><td>{entry.action}</td>
              <td>{entry.outcome}</td><td>{entry.sessions_revoked}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}
