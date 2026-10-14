(function () {
  function number(value) {
    var parsed = parseFloat(value);
    return isNaN(parsed) ? null : parsed;
  }

  function csrfToken() {
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    if (input && input.value) return input.value;
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  window.NaghshMap = function (opts) {
    var mapEl = document.getElementById(opts.map);
    var latInput = document.getElementById(opts.lat);
    var lngInput = document.getElementById(opts.lng);
    var openBtn = document.getElementById(opts.open);
    var confirmBtn = document.getElementById(opts.confirm);
    var statusEl = document.getElementById(opts.status);
    var box = document.getElementById(opts.box);
    if (!mapEl || !window.L) return;

    var startLat = number(latInput && latInput.value);
    var startLng = number(lngInput && lngInput.value);
    var hasPoint = startLat !== null && startLng !== null;
    var map = L.map(mapEl, { scrollWheelZoom: false }).setView(
      hasPoint ? [startLat, startLng] : [32.5, 53.5],
      hasPoint ? 16 : 5
    );
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap"
    }).addTo(map);

    var marker = null;
    function say(text) {
      if (statusEl) statusEl.textContent = text;
    }
    function place(lat, lng, quiet) {
      if (!marker) {
        marker = L.marker([lat, lng], { draggable: !opts.readonly }).addTo(map);
        if (!opts.readonly) {
          marker.on("dragend", function () {
            say("سنجاق جابه‌جا شد. اگر همین نقطه درست است، تایید کن.");
          });
        }
      } else {
        marker.setLatLng([lat, lng]);
      }
      map.setView([lat, lng], Math.max(map.getZoom(), 16));
      if (!quiet && !opts.readonly) say("این نقطه روی نقشه است. اگر درست است تایید کن.");
    }

    if (!opts.readonly) {
      map.on("click", function (event) {
        place(event.latlng.lat, event.latlng.lng);
      });
    }
    if (hasPoint) {
      place(startLat, startLng, true);
      say(opts.readonly ? "" : "این موقعیت ذخیره‌شده است. می‌توانی عوضش کنی و دوباره تایید کنی.");
    } else if (!opts.readonly) {
      say("موقعیت دستگاه را باز کن، یا روی نقشه نقطه را انتخاب کن.");
    }

    function reveal() {
      if (box) box.hidden = false;
      setTimeout(function () { map.invalidateSize(); }, 60);
    }
    function locate() {
      reveal();
      if (!navigator.geolocation) {
        say("این مرورگر موقعیت دستگاه را نمی‌دهد. روی نقشه بزن.");
        return;
      }
      if (openBtn) openBtn.disabled = true;
      navigator.geolocation.getCurrentPosition(function (pos) {
        place(pos.coords.latitude, pos.coords.longitude);
        say("موقعیت دستگاه آمد. اگر درست است تایید کن، یا سنجاق را بکش.");
        if (openBtn) openBtn.disabled = false;
      }, function () {
        if (openBtn) openBtn.disabled = false;
        say("اجازه مکان داده نشد. روی نقشه نقطه را انتخاب کن و تایید کن.");
      }, { enableHighAccuracy: true, timeout: 12000 });
    }

    if (openBtn) openBtn.addEventListener("click", locate);
    if (confirmBtn) {
      confirmBtn.addEventListener("click", function () {
        if (!marker) {
          say("اول موقعیت را باز کن یا روی نقشه بزن.");
          return;
        }
        var point = marker.getLatLng();
        var lat = point.lat.toFixed(6);
        var lng = point.lng.toFixed(6);
        if (latInput) latInput.value = lat;
        if (lngInput) lngInput.value = lng;
        function announce() {
          say("ثبت شد.");
          if (opts.submit) {
            try { sessionStorage.setItem("tn-saved", "1"); } catch (error) {}
            var form = document.getElementById(opts.submit);
            if (form) form.submit();
            return;
          }
          if (window.tnSaved) window.tnSaved();
        }
        if (opts.save) {
          confirmBtn.disabled = true;
          var body = new URLSearchParams();
          body.set("form", "location");
          body.set("latitude", lat);
          body.set("longitude", lng);
          fetch(window.location.pathname, {
            method: "POST",
            headers: {
              "X-CSRFToken": csrfToken(),
              "X-Requested-With": "fetch",
              "Accept": "application/json"
            },
            body: body
          }).then(function (response) {
            return response.json().then(function (data) {
              confirmBtn.disabled = false;
              if (!response.ok || !data.ok) throw new Error("save");
              announce();
            });
          }).catch(function () {
            confirmBtn.disabled = false;
            say("ذخیره نشد. دوباره تایید کن.");
          });
          return;
        }
        announce();
      });
    }
    if (hasPoint) reveal();
    setTimeout(function () { map.invalidateSize(); }, 250);
  };
})();
