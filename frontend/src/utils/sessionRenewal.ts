import { api } from "../api";
import { pushRenewalSnapshot } from "./pushNotifications";

type TokenTiming = { iat: number; exp: number };
type RenewalResponse = {
  access_token: string;
  renewed: boolean;
  push_extended: boolean | null;
};

export const SESSION_RENEWED = "home-inventory:session-renewed";

function tokenTiming(token: string): TokenTiming {
  try {
    const encoded = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const claims: unknown = JSON.parse(atob(encoded + "=".repeat((4 - encoded.length % 4) % 4)));
    if (typeof claims === "object" && claims !== null && "iat" in claims && "exp" in claims
      && typeof claims.iat === "number" && typeof claims.exp === "number"
      && Number.isFinite(claims.iat) && Number.isFinite(claims.exp) && claims.exp > claims.iat) {
      return { iat: claims.iat, exp: claims.exp };
    }
  } catch {
    throw new Error("Impossibile leggere la scadenza della sessione.");
  }
  throw new Error("Impossibile leggere la scadenza della sessione.");
}

let pending: Promise<string | null> | null = null;

export function renewSessionOnActivity(username: string): Promise<string | null> {
  if (pending) return pending;
  const task = renew(username);
  pending = task.finally(() => { pending = null; });
  return pending;
}

async function renew(username: string): Promise<string | null> {
  const token = localStorage.getItem("access_token");
  if (!token) return null;
  const { iat, exp } = tokenTiming(token);
  if (exp - Date.now() / 1000 >= (exp - iat) / 2) return null;

  let push: Awaited<ReturnType<typeof pushRenewalSnapshot>> = null;
  let pushError = false;
  try {
    push = await pushRenewalSnapshot(username);
  } catch {
    pushError = true;
  }
  if (localStorage.getItem("access_token") !== token) return null;
  const response = await api.post<RenewalResponse>("/auth/renew", { push });
  if (localStorage.getItem("access_token") !== token) return null;
  if (response.data.renewed) {
    const next = tokenTiming(response.data.access_token);
    if (next.exp <= exp) throw new Error("Il server non ha prolungato la sessione.");
    localStorage.setItem("access_token", response.data.access_token);
    if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
      window.dispatchEvent(new Event(SESSION_RENEWED));
    }
  }
  if (pushError || response.data.push_extended === false) {
    return response.data.renewed
      ? "Sessione rinnovata, ma le notifiche push non sono state aggiornate. Controlla l’attivazione nel profilo."
      : "Impossibile verificare le notifiche push. Controlla l’attivazione nel profilo.";
  }
  return null;
}
