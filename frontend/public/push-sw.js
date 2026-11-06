function notificationTarget(value) {
  if (
    typeof value !== "string"
    || value.includes("\\")
    || /[\u0000-\u0020\u007f]/.test(value)
  ) return new URL("/", self.location.origin).href;

  try {
    const target = new URL(value, self.location.origin);
    if (
      target.origin !== self.location.origin
      || target.protocol !== new URL(self.location.origin).protocol
      || target.username || target.password
      || !value.startsWith("/") && !value.startsWith(self.location.origin + "/")
    ) {
      return new URL("/", self.location.origin).href;
    }
    return target.href;
  } catch {
    return new URL("/", self.location.origin).href;
  }
}

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = {};
  }

  const title = typeof payload.title === "string" && payload.title.length <= 80
    ? payload.title : "Home Inventory";
  const body = typeof payload.body === "string" && payload.body.length <= 160
    ? payload.body : "Hai una nuova notifica";
  const tag = typeof payload.tag === "string" && /^[a-zA-Z0-9-]{1,80}$/.test(payload.tag)
    ? payload.tag : "home-inventory-notification";
  const url = notificationTarget(payload.url);

  event.waitUntil(self.registration.showNotification(title, {
    body,
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    tag,
    data: { url },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = notificationTarget(event.notification.data?.url);
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const sameOrigin = windows.find((client) => new URL(client.url).origin === self.location.origin);
    if (sameOrigin) {
      const navigated = await sameOrigin.navigate(target);
      if (navigated) {
        await navigated.focus();
        return;
      }
    }
    await self.clients.openWindow(target);
  })());
});
