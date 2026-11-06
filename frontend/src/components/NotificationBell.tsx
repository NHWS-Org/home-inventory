import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FiBell } from "react-icons/fi";
import { getUnreadCount, NOTIFICATIONS_CHANGED } from "../notificationsApi";

export default function NotificationBell() {
  const [count, setCount] = useState<number | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    let fetching = false;
    let pending = false;
    const refresh = async (): Promise<void> => {
      if (fetching) { pending = true; return; }
      fetching = true;
      try {
        const next = await getUnreadCount();
        if (active) { setCount(next); setError(false); }
      } catch {
        if (active) { setCount(null); setError(true); }
      } finally {
        fetching = false;
        if (pending && active) { pending = false; void refresh(); }
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30000);
    window.addEventListener(NOTIFICATIONS_CHANGED, refresh);
    window.addEventListener("focus", refresh);
    return () => {
      active = false;
      clearInterval(timer);
      window.removeEventListener(NOTIFICATIONS_CHANGED, refresh);
      window.removeEventListener("focus", refresh);
    };
  }, []);
  return (
    <Link to="/notifications" aria-label={error ? "Notifiche: conteggio non disponibile" : count === null ? "Notifiche: caricamento" : `Notifiche: ${count} da leggere`}
      className="inline-flex min-h-11 items-center gap-2 rounded px-3 focus-visible:outline-2">
      <FiBell aria-hidden="true" /><span className="hidden md:inline">Notifiche</span>
      <span aria-live="polite">{error ? "!" : count === null ? "…" : count}</span>
    </Link>
  );
}
