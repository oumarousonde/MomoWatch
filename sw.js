// MomoWatch — service worker : reçoit les notifications push et les affiche.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (e) { d = {}; }
  event.waitUntil(
    self.registration.showNotification(d.titre || "MomoWatch", {
      body: d.corps || "",
      icon: "/icon-192.png",
      requireInteraction: true,
      data: { url: d.url || "/dashboard.html" }
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/dashboard.html";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((fenetres) => {
      for (const f of fenetres) {
        if (f.url.indexOf("/dashboard") !== -1 && "focus" in f) return f.focus();
      }
      return self.clients.openWindow(url);
    })
  );
});
