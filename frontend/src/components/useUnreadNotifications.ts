import { useEffect, useState } from "react";
import { getUnreadCount, NOTIFICATIONS_CHANGED } from "../notificationsApi";

export function useUnreadNotifications(userId: number | null) {
  const [result, setResult] = useState<{ userId: number; count: number | null; error: boolean } | null>(null);
  const [previousUserId, setPreviousUserId] = useState(userId);
  if (previousUserId !== userId) {
    setPreviousUserId(userId);
    setResult(null);
  }
  useEffect(() => {
    if (userId === null) return;
    let active = true;
    let fetching = false;
    let pending = false;
    const refresh = async (): Promise<void> => {
      if (fetching) { pending = true; return; }
      fetching = true;
      try {
        const next = await getUnreadCount();
        if (active) setResult({ userId, count: next, error: false });
      } catch {
        if (active) setResult({ userId, count: null, error: true });
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
  }, [userId]);
  return result?.userId === userId ? result : { count: null, error: false };
}
