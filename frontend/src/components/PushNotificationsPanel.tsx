import { useCallback, useEffect, useRef, useState } from "react";
import { FiBell, FiBellOff, FiRefreshCw } from "react-icons/fi";
import {
  disablePushForBrowser,
  enablePushForBrowser,
  inspectPushBrowser,
  activationErrorMessage,
  PushActivationError,
  testPushOnBrowser,
  type PushBrowserState,
} from "../utils/pushNotifications";
import { useAuth } from "../useAuth";

const stateLabels: Record<PushBrowserState, string> = {
  checking: "Verifica delle notifiche su questo browser…",
  unsupported: "Questo browser non supporta tutte le funzioni Web Push necessarie.",
  insecure: "Le notifiche richiedono HTTPS. Per i test locali usa localhost.",
  "install-required": "Su iPhone/iPad aggiungi prima l’app alla schermata Home e aprila da lì.",
  "ios-version-required": "Su iPhone/iPad serve iOS/iPadOS 16.4 o successivo.",
  denied: "Permesso negato. Modifica le notifiche nelle impostazioni del browser.",
  disabled: "Web Push non è abilitato dall’amministratore dell’installazione.",
  "permission-required": "Notifiche non attivate per questa sessione su questo browser.",
  expired: "Sottoscrizione assente, scaduta o non associata a questa sessione.",
  active: "Notifiche attive su questo browser e su questa sessione.",
  error: "Non è stato possibile verificare le notifiche. Riprova.",
};

function isPermissionDenied(): boolean {
  return typeof Notification !== "undefined" && Notification.permission === "denied";
}

export default function PushNotificationsPanel({ state, setState }: {
  state: PushBrowserState;
  setState: (state: PushBrowserState) => void;
}) {
  const { user } = useAuth();
  const username = user?.username ?? "";
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [cleanupFailed, setCleanupFailed] = useState(false);
  const inspection = useRef(0);
  const busyRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!username || busyRef.current) return;
    const request = ++inspection.current;
    setState("checking");
    try {
      const result = await inspectPushBrowser(username);
      if (request === inspection.current) setState(result.state);
    } catch {
      if (request === inspection.current) setState("error");
    }
  }, [username, setState]);

  useEffect(() => {
    const inspectionRef = inspection;
    void refresh();
    window.addEventListener("focus", refresh);
    return () => {
      inspectionRef.current++;
      window.removeEventListener("focus", refresh);
    };
  }, [refresh]);

  async function enable() {
    if (busy || !username) return;
    busyRef.current = true;
    inspection.current++;
    setBusy(true);
    setMessage("");
    try {
      await enablePushForBrowser(username);
      setState("active");
      setMessage("Notifiche attivate su questo browser.");
    } catch (error) {
      if (error instanceof Error && error.message === "denied") {
        setState(isPermissionDenied() ? "denied" : "permission-required");
      } else if (error instanceof Error && [
        "unsupported", "insecure", "install-required", "ios-version-required",
      ].includes(error.message)) {
        setState(error.message as PushBrowserState);
      } else if (error instanceof PushActivationError && error.stage === "configuration" && error.status === 503) {
        setState("disabled");
      } else {
        setState("error");
        setMessage(error instanceof PushActivationError
          ? activationErrorMessage(error)
          : "Attivazione non riuscita. Controlla la connessione e riprova.");
      }
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function disable() {
    if (busy || !username) return;
    busyRef.current = true;
    inspection.current++;
    setBusy(true);
    setMessage("");
    try {
      await disablePushForBrowser(username);
      setCleanupFailed(false);
      setState(isPermissionDenied() ? "denied" : "permission-required");
      setMessage("Notifiche disattivate su questo browser.");
    } catch {
      setCleanupFailed(true);
      setState("error");
      setMessage("Disattivazione incompleta. Aggiorna lo stato e riprova.");
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function test() {
    if (busy) return;
    busyRef.current = true;
    setBusy(true);
    setMessage("");
    try {
      await testPushOnBrowser();
      setMessage("Notifica locale di prova inviata a questo browser; non verifica la consegna Web Push.");
    } catch {
      setMessage("Impossibile mostrare la notifica di prova. Verifica i permessi del browser.");
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  const canEnable = ["permission-required", "expired", "error"].includes(state);
  const canDisable = ["active", "denied", "expired"].includes(state)
    || state === "error" && cleanupFailed;
  const canTest = state === "active";

  return (
    <section aria-labelledby="profile-push-heading" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" onClick={() => void refresh()} disabled={busy || state === "checking"}
          aria-label="Aggiorna stato notifiche push"
          className="inline-flex min-h-11 items-center gap-2 rounded border px-3 py-2 disabled:opacity-50">
          <FiRefreshCw aria-hidden="true" />
          Aggiorna
        </button>
      </div>
      <p role="status" aria-live="polite" className="text-sm">
        {stateLabels[state]}
      </p>
      {["install-required", "ios-version-required"].includes(state) && (
        <ol className="list-decimal space-y-1 pl-5 text-sm">
          <li>Apri il sito con Safari su iPhone/iPad.</li>
          <li>Tocca Condividi e scegli “Aggiungi alla schermata Home”.</li>
          <li>Apri l’icona dalla schermata Home e torna qui.</li>
        </ol>
      )}
      <p className="text-sm text-gray-600 dark:text-gray-300">
        La scelta vale solo per questo browser. Serve anche il consenso push per il tipo di evento;
        configura le preferenze per evento nella sezione Preferenze notifiche del Profilo.
        I banner mostrano nomi di inventari/liste, elementi e modifiche, anche sulla schermata
        bloccata se le impostazioni delle anteprime lo consentono.
      </p>
      <div className="flex flex-wrap gap-2">
        {canEnable && (
          <button type="button" onClick={() => void enable()} disabled={busy}
            className="inline-flex min-h-11 items-center gap-2 rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50">
            <FiBell aria-hidden="true" />
            {busy ? "Attivazione…" : "Attiva su questo browser"}
          </button>
        )}
        {canDisable && (
          <button type="button" onClick={() => void disable()} disabled={busy}
            className="inline-flex min-h-11 items-center gap-2 rounded border border-red-500 px-4 py-2 text-red-700 dark:text-red-300 disabled:opacity-50">
            <FiBellOff aria-hidden="true" />
            Disattiva su questo browser
          </button>
        )}
        {canTest && (
          <button type="button" onClick={() => void test()} disabled={busy}
            className="min-h-11 rounded border px-4 py-2 disabled:opacity-50">
            Mostra notifica di prova
          </button>
        )}
      </div>
      {message && <p role="status" className="text-sm">{message}</p>}
    </section>
  );
}
