import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../useAuth";
import { markOpenedNotificationRead } from "../notificationsApi";

export default function NotificationClickReader() {
  const { user, isLoading } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const params = new URLSearchParams(location.search);
  const hasNotification = params.has("notification_event") || params.has("notification_id");
  const resourcePage = /^\/(?:inventories|checklists)\/\d+$/.test(location.pathname);
  useEffect(() => {
    if (!hasNotification || !resourcePage || !user || isLoading) return;
    let active = true;
    void markOpenedNotificationRead(location.search).then(() => {
      if (!active) return;
      setError("");
      const params = new URLSearchParams(location.search);
      params.delete("notification_event");
      params.delete("notification_id");
      const search = params.toString();
      navigate({ pathname: location.pathname, search: search ? `?${search}` : "", hash: location.hash }, { replace: true });
    }).catch(() => {
      if (active) setError("Impossibile segnare la notifica come letta: verifica account e accesso, oppure riprova.");
    });
    return () => { active = false; };
  }, [hasNotification, resourcePage, user, isLoading, location.pathname, location.search, location.hash, navigate, attempt]);
  if (!error || !hasNotification || !resourcePage || !user || isLoading) return null;
  return (
    <div className="mb-2 rounded border border-red-500 p-2 text-sm">
      <p role="alert">{error}</p>
      <button type="button" className="min-h-11 underline" onClick={() => { setError(""); setAttempt(previous => previous + 1); }}>Riprova lettura notifica</button>
    </div>
  );
}
