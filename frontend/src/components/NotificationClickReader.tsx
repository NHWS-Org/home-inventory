import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../useAuth";
import { markNotificationEventRead, notifyInboxChanged } from "../notificationsApi";

export default function NotificationClickReader() {
  const { user, isLoading } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const eventKey = new URLSearchParams(location.search).get("notification_event");
  const resourcePage = /^\/(?:inventories|checklists)\/\d+$/.test(location.pathname);
  useEffect(() => {
    if (!eventKey || !resourcePage || !user || isLoading) return;
    let active = true;
    void markNotificationEventRead(eventKey).then(() => {
      if (!active) return;
      notifyInboxChanged();
      setError("");
      const params = new URLSearchParams(location.search);
      params.delete("notification_event");
      const search = params.toString();
      navigate({ pathname: location.pathname, search: search ? `?${search}` : "", hash: location.hash }, { replace: true });
    }).catch(() => {
      if (active) setError("Impossibile segnare la notifica come letta: verifica account e accesso, oppure riprova.");
    });
    return () => { active = false; };
  }, [eventKey, resourcePage, user, isLoading, location.pathname, location.search, location.hash, navigate, attempt]);
  if (!error || !eventKey || !resourcePage || !user || isLoading) return null;
  return (
    <div className="mb-2 rounded border border-red-500 p-2 text-sm">
      <p role="alert">{error}</p>
      <button type="button" className="min-h-11 underline" onClick={() => { setError(""); setAttempt(previous => previous + 1); }}>Riprova lettura notifica</button>
    </div>
  );
}
