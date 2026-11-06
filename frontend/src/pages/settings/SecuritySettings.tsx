import { useEffect, useState, type FormEvent } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import {
  getSecurityAudit, getSecurityStatus, performSecurityAction,
  type SecurityAuditEntry, type SecurityStatus,
} from "../../api";
import { useAuth } from "../../useAuth";

type Action = "revoke-sessions" | "rotate-key";

export default function SecuritySettings() {
  const { setUser } = useAuth();
  const navigate = useNavigate();
  const [status, setStatus] = useState<SecurityStatus | null>(null);
  const [audit, setAudit] = useState<SecurityAuditEntry[]>([]);
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

  function chooseAction(next: Action | null) {
    setAction(next);
    setPassword("");
    setConfirmed(false);
    setError("");
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
      <p>Entrambe le azioni disconnettono tutti gli utenti, incluso questo account. Password e dati restano invariati.</p>
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
