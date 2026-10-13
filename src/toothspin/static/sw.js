// Minimal service worker so browsers treat the page as an installable app.
// Everything is live state, so it always goes to the network (no caching).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
