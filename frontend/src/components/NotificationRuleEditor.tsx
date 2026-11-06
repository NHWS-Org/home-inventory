import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  deleteNotificationRule, getNotificationRules, getRuleRecipients, notificationLabels,
  saveNotificationRule, type NotificationEventType, type NotificationRecipient,
  type NotificationRule, type RuleRecipientOptions,
} from "../notificationsApi";

export default function NotificationRuleEditor({ inventoryId, checklist }: { inventoryId: number; checklist: boolean }) {
  const [rules, setRules] = useState<NotificationRule[]>([]);
  const [options, setOptions] = useState<RuleRecipientOptions>({ users: [], groups: [] });
  const [eventType, setEventType] = useState<NotificationEventType>("inventory_shared");
  const [threshold, setThreshold] = useState("3");
  const [recipients, setRecipients] = useState<NotificationRecipient[]>([{ kind: "owner" }]);
  const [enabled, setEnabled] = useState(true);
  const [editing, setEditing] = useState<number>();
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextRules, nextOptions] = await Promise.all([getNotificationRules(inventoryId), getRuleRecipients(inventoryId)]);
      setRules(nextRules);
      setOptions(nextOptions);
    } catch { setError("Impossibile caricare le regole o accesso revocato. Riprova."); }
    finally { setLoading(false); }
  }, [inventoryId]);
  useEffect(() => { void load(); }, [load]);
  function reset() {
    setEditing(undefined);
    setEventType("inventory_shared");
    setThreshold("3");
    setRecipients([{ kind: "owner" }]);
    setEnabled(true);
  }
  function toggle(recipient: NotificationRecipient, checked: boolean) {
    setRecipients(previous => checked ? [...previous, recipient] : previous.filter(r => !(r.kind === recipient.kind && r.id === recipient.id)));
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await saveNotificationRule(inventoryId, {
        event_type: eventType,
        threshold: eventType === "item_quantity_changed" ? Number(threshold) : null,
        recipients,
        enabled,
      }, editing);
      reset();
      setNotice("Regola salvata.");
      await load();
    } catch { setError("Salvataggio non riuscito. Verifica destinatari e autorizzazioni e riprova."); }
    finally { setBusy(false); }
  }
  async function remove(rule: NotificationRule) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await deleteNotificationRule(inventoryId, rule.id);
      if (editing === rule.id) reset();
      setNotice("Regola eliminata.");
      await load();
    } catch { setError("Eliminazione non riuscita. Verifica l'accesso e riprova."); }
    finally { setBusy(false); }
  }
  const choices: { recipient: NotificationRecipient; label: string }[] = [
    { recipient: { kind: "owner" }, label: "Proprietario" },
    { recipient: { kind: "participants" }, label: "Partecipanti autorizzati" },
    ...(eventType === "inventory_shared" ? [{ recipient: { kind: "event_recipient" as const }, label: "Destinatario della condivisione" }] : []),
    ...options.users.map(u => ({ recipient: { kind: "user" as const, id: u.id }, label: `Utente: ${u.username}` })),
    ...options.groups.map(g => ({ recipient: { kind: "group" as const, id: g.id }, label: `Gruppo: ${g.name}` })),
  ];
  return (
    <details className="my-3 rounded border p-3">
      <summary className="min-h-11 cursor-pointer font-semibold">Regole notifiche</summary>
      <section aria-label="Editor regole notifiche" className="space-y-3">
        {loading && <p role="status">Caricamento...</p>}
        {error && <p role="alert">{error}</p>}
        <button disabled={busy || loading} onClick={() => void load()} className="min-h-11 rounded border px-3">Aggiorna regole</button>
        {!loading && !error && !rules.length && <p>Nessuna regola: non vengono generati avvisi per questo contenitore.</p>}
        <ul className="space-y-2">
          {rules.map(rule => <li key={rule.id} className="rounded border p-2">
            <p>{notificationLabels[rule.event_type]}{rule.threshold !== null ? ` (${rule.threshold})` : ""} · {rule.enabled ? "Attiva" : "Disattiva"}</p>
            <p>{rule.recipients.map(r => r.kind === "user" ? `Utente ${options.users.find(u => u.id === r.id)?.username ?? r.id}` : r.kind === "group" ? `Gruppo ${options.groups.find(g => g.id === r.id)?.name ?? r.id}` : r.kind === "owner" ? "Proprietario" : r.kind === "participants" ? "Partecipanti" : "Destinatario condivisione").join(", ")}</p>
            <div className="flex gap-2">
              <button disabled={busy || loading} onClick={() => {
                setEditing(rule.id); setEventType(rule.event_type); setThreshold(String(rule.threshold ?? 3));
                setRecipients(rule.recipients); setEnabled(rule.enabled); setNotice("");
              }} className="min-h-11 rounded border px-3">Modifica</button>
              <button disabled={busy || loading} onClick={() => void remove(rule)} className="min-h-11 rounded border px-3">Elimina</button>
            </div>
          </li>)}
        </ul>
        <form onSubmit={event => void submit(event)} className="space-y-3">
          <fieldset disabled={busy || loading} className="space-y-3">
            <legend className="font-semibold">{editing === undefined ? "Nuova regola" : "Modifica regola"}</legend>
            <label className="block">Quando
              <select value={eventType} onChange={event => {
                const next = event.target.value as NotificationEventType;
                setEventType(next);
                if (next !== "inventory_shared") setRecipients(previous => previous.filter(r => r.kind !== "event_recipient"));
              }} className="block min-h-11 w-full rounded border px-2">
                <option value="inventory_shared">Il contenitore viene condiviso</option>
                <option value={checklist ? "checklist_completed" : "item_quantity_changed"}>{checklist ? "La lista viene completata" : "La quantità scende sotto soglia"}</option>
              </select>
            </label>
            {eventType === "item_quantity_changed" && <label className="block">Soglia quantità
              <input type="number" min="0" max="2147483647" step="1" required value={threshold} onChange={event => setThreshold(event.target.value)} className="block min-h-11 w-full rounded border px-2" />
            </label>}
            <fieldset>
              <legend>Destinatari</legend>
              {choices.map(({ recipient, label }) => <label key={`${recipient.kind}:${recipient.id ?? ""}`} className="flex min-h-11 items-center gap-2">
                <input type="checkbox" checked={recipients.some(r => r.kind === recipient.kind && r.id === recipient.id)} onChange={event => toggle(recipient, event.target.checked)} />{label}
              </label>)}
            </fieldset>
            <label className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} />Regola attiva</label>
            <p>Riepilogo: {notificationLabels[eventType]}{eventType === "item_quantity_changed" ? `, soglia ${threshold}` : ""}; {recipients.length} destinatari selezionati; {enabled ? "attiva" : "disattiva"}.</p>
            <p className="text-sm">Canali: inbox e/o push secondo le preferenze di ciascun destinatario. La regola non forza consenso o permessi; azioni proprie escluse salvo scelta personale.</p>
            <Link to="/profile" className="text-blue-700 underline dark:text-blue-300">Configura i miei canali nel Profilo</Link>
            <div className="flex gap-2">
              <button type="submit" disabled={!recipients.length} className="min-h-11 rounded border px-3">Salva regola</button>
              <button type="button" onClick={reset} className="min-h-11 rounded border px-3">Annulla modifica</button>
            </div>
          </fieldset>
        </form>
        {notice && <p role="status">{notice}</p>}
      </section>
    </details>
  );
}
