import { useCallback, useEffect, useId, useRef, useState } from "react";
import { FiBell, FiBellOff, FiInbox } from "react-icons/fi";
import { getNotificationPreferences, notificationLabels, notifyInboxChanged, saveNotificationPreference, type NotificationPreference } from "../notificationsApi";
import { getTriggerSubscriptions, getTriggers, saveTriggerSubscription, type TriggerResponse, type TriggerSubscription } from "../filtersApi";

const modes = [
  { value: "off", label: "Disattivate", Icon: FiBellOff },
  { value: "inbox", label: "Solo Inbox", Icon: FiInbox },
  { value: "inbox_push", label: "Inbox + Push", Icon: FiBell },
] as const;

export default function NotificationPreferences() {
  const groupId = useId();
  const [rows, setRows] = useState<NotificationPreference[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [triggers, setTriggers] = useState<TriggerResponse[]>([]);
  const [subscriptions, setSubscriptions] = useState<TriggerSubscription[]>([]);
  const [subscriptionsLoading, setSubscriptionsLoading] = useState(true);
  const [subscriptionsError, setSubscriptionsError] = useState("");
  const [subscriptionBusy, setSubscriptionBusy] = useState<number | null>(null);
  const saving = useRef(false);
  const focusAfterSave = useRef<HTMLInputElement | null>(null);
  async function load() {
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const preferences = await getNotificationPreferences();
      setRows(preferences.some(row => row.event_type === "filter_trigger_matched")
        ? preferences
        : [...preferences, { event_type: "filter_trigger_matched", in_app_enabled: false, push_enabled: false }]);
    }
    catch { setError("Impossibile caricare le preferenze notifiche."); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);
  const loadSubscriptions = useCallback(async () => {
    setSubscriptionsLoading(true);
    setSubscriptionsError("");
    try {
      const [availableTriggers, savedSubscriptions] = await Promise.all([getTriggers(), getTriggerSubscriptions()]);
      if (!Array.isArray(availableTriggers) || !Array.isArray(savedSubscriptions)) {
        throw new Error("Invalid trigger subscription response");
      }
      setTriggers(availableTriggers);
      setSubscriptions(savedSubscriptions);
    } catch {
      setSubscriptionsError("Impossibile caricare le iscrizioni ai trigger.");
    } finally { setSubscriptionsLoading(false); }
  }, []);
  useEffect(() => { void loadSubscriptions(); }, [loadSubscriptions]);
  useEffect(() => {
    if (busy) return;
    const input = focusAfterSave.current;
    focusAfterSave.current = null;
    if (input?.isConnected && document.activeElement === document.body
        && !input.closest("[hidden], details:not([open])")) {
      input.focus({ preventScroll: true });
    }
  }, [busy]);
  async function changeMode(row: NotificationPreference, mode: typeof modes[number]["value"], input: HTMLInputElement) {
    if (saving.current) return;
    saving.current = true;
    focusAfterSave.current = document.activeElement === input ? input : null;
    const next = { ...row, in_app_enabled: mode !== "off", push_enabled: mode === "inbox_push" };
    setRows(previous => previous.map(p => p.event_type === row.event_type ? next : p));
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await saveNotificationPreference(next);
      notifyInboxChanged();
      setNotice(`Preferenze salvate: ${notificationLabels[row.event_type]}.`);
    } catch {
      setRows(previous => previous.map(p => p.event_type === row.event_type ? row : p));
      setError("Salvataggio non riuscito: ripristinato il valore precedente. Seleziona di nuovo per riprovare.");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  async function changeSubscription(triggerId: number, enabled: boolean) {
    const previous = subscriptions;
    setSubscriptions(current => current.some(row => row.trigger_id === triggerId)
      ? current.map(row => row.trigger_id === triggerId ? { ...row, enabled } : row)
      : [...current, { trigger_id: triggerId, enabled }]);
    setSubscriptionsError("");
    setSubscriptionBusy(triggerId);
    setNotice("");
    try {
      await saveTriggerSubscription(triggerId, enabled);
      setNotice(enabled ? "Iscrizione al trigger attivata." : "Iscrizione al trigger disattivata.");
    } catch {
      setSubscriptions(previous);
      setSubscriptionsError("Iscrizione non salvata. Lo stato precedente è stato ripristinato.");
    } finally { setSubscriptionBusy(null); }
  }
  return (
    <section aria-labelledby="notification-preferences-heading" className="space-y-2">
      <p className="text-sm">Scegli Disattivate, Solo Inbox oppure Inbox + Push per ogni evento: si salva automaticamente. Il push richiede anche il consenso browser nel pannello dedicato.</p>
      <p className="text-sm">Solo per modifiche di altri utenti a inventari e liste che puoi modificare. Quantità e spunte sono notificate dopo 45 secondi dall'ultima modifica; i dettagli includono nome, descrizione, barcode e metadati.</p>
      {loading && <p role="status">Caricamento...</p>}
      {error && <p role="alert">{error}</p>}
      {error && <button type="button" disabled={busy || loading} onClick={() => void load()} className="min-h-11 rounded border px-3">Ricarica preferenze</button>}
      <div className="grid gap-3 xl:grid-cols-3">
        {rows.map(row => (
          <fieldset key={row.event_type} disabled={busy || loading} className="min-w-0 rounded-2xl border border-gray-200 px-3 pb-3 dark:border-gray-700 disabled:opacity-60">
            <legend className="px-1 text-sm font-semibold">{notificationLabels[row.event_type]}</legend>
            <div className="mt-2 grid grid-cols-3 gap-1 rounded-xl bg-gray-100 p-1 dark:bg-gray-800">
              {modes.map(({ value, label, Icon }) => (
                <label key={value} className="min-w-0 cursor-pointer">
                  <input
                    type="radio"
                    name={`${groupId}-${row.event_type}`}
                    value={value}
                    checked={value === (row.push_enabled ? "inbox_push" : row.in_app_enabled ? "inbox" : "off")}
                    onChange={event => void changeMode(row, value, event.currentTarget)}
                    className="peer sr-only"
                  />
                  <span className="flex min-h-14 flex-col items-center justify-center gap-1 rounded-lg px-1 py-2 text-center text-xs font-medium text-gray-600 transition-colors hover:bg-gray-200 peer-checked:bg-blue-600 peer-checked:text-white peer-checked:shadow-sm peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-blue-500 peer-disabled:cursor-wait motion-reduce:transition-none dark:text-gray-300 dark:hover:bg-gray-700 dark:peer-checked:bg-blue-500 dark:peer-checked:text-white">
                    <Icon aria-hidden="true" className="h-4 w-4" />
                    {label}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
        ))}
      </div>
      <p role="status" className="text-sm">{busy ? "Salvataggio..." : notice}</p>
      <section aria-labelledby="trigger-subscriptions-heading" className="space-y-2 border-t border-gray-200 pt-4 dark:border-gray-700">
        <div>
          <h3 id="trigger-subscriptions-heading" className="font-semibold">Avvisi da trigger</h3>
          <p className="text-sm">Iscriviti ai trigger disponibili. Gli avvisi rispettano anche la preferenza “Avvisi da trigger” e l’accesso al contenitore.</p>
        </div>
        {subscriptionsLoading && <p role="status" className="text-sm">Caricamento trigger…</p>}
        {subscriptionsError && <p role="alert" className="text-sm">{subscriptionsError}</p>}
        {subscriptionsError && <button type="button" disabled={subscriptionsLoading} onClick={() => void loadSubscriptions()} className="min-h-11 rounded border px-3 text-sm">Riprova iscrizioni</button>}
        {!subscriptionsLoading && !triggers.length && !subscriptionsError && <p className="text-sm text-gray-500">Nessun trigger disponibile al momento.</p>}
        <ul className="divide-y divide-gray-200 dark:divide-gray-700">
          {triggers.map(trigger => {
            const enabled = subscriptions.find(row => row.trigger_id === trigger.id)?.enabled ?? false;
            return <li key={trigger.id} className="flex min-h-14 items-center justify-between gap-3 py-2">
              <span className="min-w-0"><span className="block break-words text-sm font-medium">{trigger.name}</span><span className="block break-words text-xs text-gray-500">{trigger.filter_name} · {trigger.scope_preview.summary}</span></span>
              <button type="button" role="switch" aria-checked={enabled} disabled={subscriptionsLoading || subscriptionBusy === trigger.id} onClick={() => void changeSubscription(trigger.id, !enabled)} className={`relative h-11 w-14 shrink-0 rounded-full transition-colors disabled:opacity-50 ${enabled ? "bg-blue-600" : "bg-gray-300 dark:bg-gray-600"}`} aria-label={`${enabled ? "Annulla iscrizione a" : "Iscriviti a"} ${trigger.name}`}>
                <span className={`absolute top-[14px] h-5 w-5 rounded-full bg-white shadow transition-transform ${enabled ? "left-[30px]" : "left-1.5"}`} />
              </button>
            </li>;
          })}
        </ul>
      </section>
    </section>
  );
}
