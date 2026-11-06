import axios from "axios";
import {
  deletePushSubscription,
  getPushConfiguration,
  getPushSubscriptions,
  savePushSubscription,
  type PushConfiguration,
} from "../api";

const OWNER_KEY = "web_push_owner";
const SUBSCRIPTION_ID_PREFIX = "web_push_subscription_id:";
const PUBLIC_KEY_PREFIX = "web_push_public_key:";

export type PushAvailability =
  | "supported"
  | "unsupported"
  | "insecure"
  | "install-required"
  | "ios-version-required";

export type PushBrowserState =
  | "checking"
  | "unsupported"
  | "insecure"
  | "install-required"
  | "ios-version-required"
  | "denied"
  | "disabled"
  | "permission-required"
  | "expired"
  | "active"
  | "error";

type PushEnvironment = {
  secureContext: boolean;
  hostname: string;
  userAgent: string;
  platform: string;
  maxTouchPoints: number;
  standalone: boolean;
  hasNotification: boolean;
  hasServiceWorker: boolean;
  hasPushManager: boolean;
};

function isIOS(userAgent: string, platform: string, maxTouchPoints: number): boolean {
  return /iPad|iPhone|iPod/i.test(userAgent)
    || /Macintosh/i.test(userAgent) && /Mobile/i.test(userAgent)
    || platform === "MacIntel" && maxTouchPoints > 1;
}

function iosVersion(userAgent: string): number[] | null {
  const match = userAgent.match(/(?:CPU (?:iPhone )?OS|iPhone OS) (\d+)[._](\d+)/i);
  return match ? [Number(match[1]), Number(match[2])] : null;
}

export function detectPushAvailability(environment: PushEnvironment): PushAvailability {
  if (!environment.secureContext && environment.hostname !== "localhost") return "insecure";
  if (isIOS(environment.userAgent, environment.platform, environment.maxTouchPoints)) {
    const version = iosVersion(environment.userAgent);
    if (version && (version[0] < 16 || version[0] === 16 && version[1] < 4)) {
      return "ios-version-required";
    }
    if (!environment.standalone) return "install-required";
  }
  if (
    !environment.hasNotification || !environment.hasServiceWorker
    || !environment.hasPushManager
  ) return "unsupported";
  return "supported";
}

function currentEnvironment(): PushEnvironment {
  const userAgent = navigator.userAgent;
  const standalone = window.matchMedia("(display-mode: standalone)").matches
    || ("standalone" in navigator && navigator.standalone === true);
  return {
    secureContext: window.isSecureContext,
    hostname: window.location.hostname,
    userAgent,
    platform: navigator.platform,
    maxTouchPoints: navigator.maxTouchPoints,
    standalone,
    hasNotification: "Notification" in window,
    hasServiceWorker: "serviceWorker" in navigator,
    hasPushManager: "PushManager" in window,
  };
}

export function decodeVapidPublicKey(encoded: string): Uint8Array {
  if (!/^[A-Za-z0-9_-]+$/.test(encoded)) throw new Error("Chiave VAPID non valida.");
  const base64 = encoded.replace(/-/g, "+").replace(/_/g, "/");
  let decoded: string;
  try {
    decoded = atob(base64 + "=".repeat((4 - base64.length % 4) % 4));
  } catch {
    throw new Error("Chiave VAPID non valida.");
  }
  const result = Uint8Array.from(decoded, (character) => character.charCodeAt(0));
  if (result.length !== 65 || result[0] !== 4) throw new Error("Chiave VAPID non valida.");
  return result;
}

function subscriptionStorageKey(prefix: string, username: string): string {
  return `${prefix}${encodeURIComponent(username)}`;
}

function clearStoredOwnership(username?: string): void {
  if (!username || localStorage.getItem(OWNER_KEY) === username) {
    const owner = localStorage.getItem(OWNER_KEY);
    if (owner) {
      localStorage.removeItem(subscriptionStorageKey(SUBSCRIPTION_ID_PREFIX, owner));
      localStorage.removeItem(subscriptionStorageKey(PUBLIC_KEY_PREFIX, owner));
    }
    localStorage.removeItem(OWNER_KEY);
  }
}

async function browserSubscription(): Promise<PushSubscription | null> {
  const registration = await navigator.serviceWorker.getRegistration("/");
  return registration?.pushManager.getSubscription() ?? null;
}

export async function inspectPushBrowser(username: string): Promise<{
  state: PushBrowserState;
  configuration?: PushConfiguration;
}> {
  const availability = detectPushAvailability(currentEnvironment());
  if (availability !== "supported") return { state: availability };
  if (Notification.permission === "denied") return { state: "denied" };

  let configuration: PushConfiguration;
  try {
    configuration = await getPushConfiguration();
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 503) {
      return { state: "disabled" };
    }
    return { state: "error" };
  }

  try {
    const registration = await navigator.serviceWorker.register("/push-sw.js", { scope: "/" });
    const subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      return { state: Notification.permission === "granted" ? "expired" : "permission-required", configuration };
    }
    if (subscription.expirationTime !== null && subscription.expirationTime <= Date.now()) {
      await subscription.unsubscribe();
      return { state: "expired", configuration };
    }

    const owner = localStorage.getItem(OWNER_KEY);
    if (owner && owner !== username) {
      await subscription.unsubscribe();
      clearStoredOwnership(owner);
      return { state: "expired", configuration };
    }
    const storedKey = localStorage.getItem(subscriptionStorageKey(PUBLIC_KEY_PREFIX, username));
    const browserKey = subscription.options.applicationServerKey;
    const browserKeyMatches = browserKey
      ? bytesToBase64Url(new Uint8Array(browserKey)) === configuration.public_key
      : storedKey === configuration.public_key;
    if (!browserKeyMatches) {
      await subscription.unsubscribe();
      return { state: "expired", configuration };
    }

    const storedId = localStorage.getItem(subscriptionStorageKey(SUBSCRIPTION_ID_PREFIX, username));
    if (!storedId) return { state: "expired", configuration };
    const subscriptions = await getPushSubscriptions();
    if (
      owner === username
      && subscriptions.some((item) =>
        item.id === Number(storedId) && new Date(item.expires_at).getTime() > Date.now()
      )
    ) return { state: "active", configuration };
    return { state: "expired", configuration };
  } catch {
    return { state: "error", configuration };
  }
}

function bytesToBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

async function deleteKnownSubscription(subscriptionId: number): Promise<void> {
  try {
    await deletePushSubscription(subscriptionId);
  } catch (error) {
    if (!axios.isAxiosError(error) || error.response?.status !== 404) throw error;
  }
}

export async function enablePushForBrowser(
  username: string,
  requestPermission: () => Promise<NotificationPermission> = () => Notification.requestPermission(),
): Promise<void> {
  const availability = detectPushAvailability(currentEnvironment());
  if (availability !== "supported") throw new Error(availability);
  if (Notification.permission === "denied") throw new Error("denied");

  // Invoke permission directly from the user gesture, before any asynchronous work.
  const permissionRequest = Notification.permission === "default"
    ? requestPermission()
    : Promise.resolve(Notification.permission);
  const permission = await permissionRequest;
  if (permission !== "granted") throw new Error("denied");

  const configuration = await getPushConfiguration();
  const decodedKey = decodeVapidPublicKey(configuration.public_key);
  const applicationServerKey = new Uint8Array(new ArrayBuffer(decodedKey.byteLength));
  applicationServerKey.set(decodedKey);
  const registration = await navigator.serviceWorker.register("/push-sw.js", { scope: "/" });
  let subscription = await registration.pushManager.getSubscription();
  const nativeKey = subscription?.options.applicationServerKey
    ? bytesToBase64Url(new Uint8Array(subscription.options.applicationServerKey))
    : null;
  const storedOwner = localStorage.getItem(OWNER_KEY);
  const storedKey = storedOwner === username
    ? localStorage.getItem(subscriptionStorageKey(PUBLIC_KEY_PREFIX, username))
    : null;
  const staleSubscription = Boolean(
    subscription && (
      subscription.expirationTime !== null && subscription.expirationTime <= Date.now()
      || nativeKey !== null && nativeKey !== configuration.public_key
      || nativeKey === null && storedKey !== null && storedKey !== configuration.public_key
    ),
  );
  if (staleSubscription && storedOwner === username) {
    const storedId = localStorage.getItem(subscriptionStorageKey(SUBSCRIPTION_ID_PREFIX, username));
    if (storedId) await deleteKnownSubscription(Number(storedId));
  }
  if (subscription && staleSubscription) {
    await subscription.unsubscribe();
    subscription = null;
  }
  if (!subscription && storedOwner === username) {
    const storedId = localStorage.getItem(subscriptionStorageKey(SUBSCRIPTION_ID_PREFIX, username));
    if (storedId && !staleSubscription) await deleteKnownSubscription(Number(storedId));
  }
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey,
    });
  }

  let savedId: number | null = null;
  try {
    const saved = await savePushSubscription({
      ...subscription.toJSON(),
      expirationTime: subscription.expirationTime,
    });
    savedId = saved.id;
    localStorage.setItem(subscriptionStorageKey(SUBSCRIPTION_ID_PREFIX, username), String(saved.id));
    localStorage.setItem(subscriptionStorageKey(PUBLIC_KEY_PREFIX, username), configuration.public_key);
    localStorage.setItem(OWNER_KEY, username);
  } catch (error) {
    try {
      if (savedId !== null) await deleteKnownSubscription(savedId);
    } finally {
      try {
        await subscription.unsubscribe();
      } finally {
        clearStoredOwnership(username);
      }
    }
    throw error;
  }
}

export async function disablePushForBrowser(username: string): Promise<void> {
  const owner = localStorage.getItem(OWNER_KEY);
  let failure: unknown;
  const storedId = owner === username
    ? localStorage.getItem(subscriptionStorageKey(SUBSCRIPTION_ID_PREFIX, username))
    : null;
  if (storedId) {
    try {
      await deleteKnownSubscription(Number(storedId));
    } catch (error) {
      failure = error;
    }
  }
  try {
    const subscription = await browserSubscription();
    if (subscription && !(await subscription.unsubscribe())) {
      throw new Error("Il browser non ha confermato la disattivazione.");
    }
  } catch (error) {
    failure ??= error;
  } finally {
    clearStoredOwnership(username);
  }
  if (failure) throw failure;
}

export async function testPushOnBrowser(): Promise<void> {
  const registration = await navigator.serviceWorker.getRegistration("/");
  if (!registration || Notification.permission !== "granted") {
    throw new Error("Attiva prima le notifiche su questo browser.");
  }
  await registration.showNotification("Home Inventory · Test", {
    body: "Notifica locale di prova su questo browser.",
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    tag: `his-local-test-${Date.now()}`,
    data: { url: "/profile" },
  });
}
