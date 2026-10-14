import json

from django.http import HttpResponse

MANIFEST = {
    "id": "/",
    "name": "فیکسوگرام",
    "short_name": "فیکسوگرام",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#0b1424",
    "theme_color": "#0b1424",
    "icons": [
        {"src": "/static/talent/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/static/talent/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
    ],
}

SERVICE_WORKER = """
const CACHE = "tamirneshan-v5";

self.addEventListener("install", function (event) {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (key) { return key !== CACHE; }).map(function (key) {
        return caches.delete(key);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

function offlinePage() {
  var html = "<!DOCTYPE html><html lang=\\"fa\\" dir=\\"rtl\\"><meta charset=\\"utf-8\\"><meta name=\\"viewport\\" content=\\"width=device-width, initial-scale=1\\"><title>فیکسوگرام</title><body style=\\"font-family:tahoma,sans-serif;background:#0b1424;color:#f5f9ff;padding:2rem\\"><h1>فیکسوگرام</h1><p>اتصال اینترنت قطع است. وقتی وصل شد، صفحه را دوباره باز کن.</p></body></html>";
  return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
}

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var target = (event.notification.data && event.notification.data.url) || "/messages/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (list) {
      for (var i = 0; i < list.length; i++) {
        if (list[i].url.indexOf(target) !== -1 && "focus" in list[i]) return list[i].focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(target);
    })
  );
});

self.addEventListener("push", function (event) {
  var data = {};
  if (event.data) {
    try { data = event.data.json(); } catch (error) { data = { body: event.data.text() }; }
  }
  var title = data.title || "پیام تازه در فیکسوگرام";
  var target = data.url || "/messages/";
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || "یک پیام تازه داری.",
    icon: "/static/talent/icon-192.png?v=4",
    dir: "rtl",
    lang: "fa",
    tag: data.tag || "msg",
    data: { url: target }
  }));
});

self.addEventListener("fetch", function (event) {
  var request = event.request;
  if (request.method !== "GET") return;
  var url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(offlinePage));
    return;
  }
  if (url.pathname.indexOf("/static/") === 0) {
    event.respondWith(
      caches.open(CACHE).then(function (cache) {
        return cache.match(request).then(function (cached) {
          var network = fetch(request).then(function (response) {
            if (response && response.ok) cache.put(request, response.clone());
            return response;
          }).catch(function () { return cached; });
          return cached || network;
        });
      })
    );
  }
});
""".strip()


INSTALL_PATHS = ("/sw.js", "/app-sw.js", "/manifest.webmanifest")


class InstallHeaders:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path not in INSTALL_PATHS:
            return response
        vary = response.headers.get("Vary", "")
        parts = [part.strip() for part in vary.split(",") if part.strip() and part.strip().lower() != "cookie"]
        if parts:
            response.headers["Vary"] = ", ".join(parts)
        elif "Vary" in response.headers:
            del response.headers["Vary"]
        if "Set-Cookie" in response.headers:
            del response.headers["Set-Cookie"]
        return response


def manifest(request):
    body = json.dumps(MANIFEST, ensure_ascii=True, separators=(",", ":"))
    response = HttpResponse(body, content_type="application/manifest+json")
    response["Cache-Control"] = "no-cache"
    return response


def service_worker(request):
    response = HttpResponse(SERVICE_WORKER, content_type="text/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response
