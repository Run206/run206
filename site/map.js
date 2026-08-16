/* Run206 map.
 *
 * EVENTS is injected by the build as a compact array — [name, date, type,
 * location, url, lat, lon, distances, time] — rather than objects, because at
 * ~400 events the repeated JSON keys cost more than the data.
 *
 * Circle markers, not Leaflet's default icons: they're pure SVG, so the page
 * never requests Leaflet's marker PNGs and the only external traffic is map
 * tiles.
 */
(function () {
  "use strict";

  var NAME = 0, DATE = 1, TYPE = 2, LOC = 3, URL = 4, LAT = 5, LON = 6,
      DIST = 7, TIME = 8;

  var COLOURS = {
    "Race": "#C0402A",
    "Club Run": "#0F6248",
    "Brand Event": "#443DA0",
  };

  var map = L.map("map", { scrollWheelZoom: false })
             .setView([47.6062, -122.3321], 10);

  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  // Scroll-wheel zoom hijacks page scrolling on a long page, so require a
  // deliberate click first.
  map.on("click", function () { map.scrollWheelZoom.enable(); });
  map.on("mouseout", function () { map.scrollWheelZoom.disable(); });

  var layer = L.layerGroup().addTo(map);
  var state = { type: "All", within: "all" };
  var today = new Date(); today.setHours(0, 0, 0, 0);

  function daysOut(iso) {
    var parts = String(iso).split("-");
    var when = new Date(+parts[0], +parts[1] - 1, +parts[2]);
    return Math.round((when - today) / 86400000);
  }

  function escapeHtml(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function formatDate(iso) {
    var months = ["Jan","Feb","Mar","Apr","May","Jun",
                  "Jul","Aug","Sep","Oct","Nov","Dec"];
    var parts = String(iso).split("-");
    return parts[2].replace(/^0/, "") + " " + months[+parts[1] - 1];
  }

  function matches(event) {
    if (state.type !== "All" && event[TYPE] !== state.type) return false;
    if (state.within !== "all") {
      var out = daysOut(event[DATE]);
      if (out < 0 || out > +state.within) return false;
    }
    return true;
  }

  function popup(event) {
    var bits = [];
    if (event[DIST]) bits.push(escapeHtml(event[DIST]));
    if (event[LOC]) bits.push(escapeHtml(event[LOC]));
    if (event[TIME]) bits.push(escapeHtml(event[TIME]));

    var html = '<strong class="pop-name">' + escapeHtml(event[NAME]) + "</strong>" +
               '<span class="pop-date">' + escapeHtml(formatDate(event[DATE])) + "</span>";
    if (bits.length) html += '<span class="pop-meta">' + bits.join(" &middot; ") + "</span>";
    if (event[URL]) {
      html += '<a class="pop-link" href="' + escapeHtml(event[URL]) +
              '" target="_blank" rel="noopener nofollow sponsored">Details &rarr;</a>';
    }
    return html;
  }

  function draw() {
    layer.clearLayers();
    var shown = 0;
    // Sort so the soonest events draw last and sit on top of later ones.
    var visible = EVENTS.filter(matches).sort(function (a, b) {
      return b[DATE] < a[DATE] ? -1 : 1;
    });

    for (var i = 0; i < visible.length; i++) {
      var event = visible[i];
      shown++;
      L.circleMarker([event[LAT], event[LON]], {
        radius: 7,
        color: "#fff",
        weight: 1.5,
        fillColor: COLOURS[event[TYPE]] || COLOURS.Race,
        fillOpacity: 0.85,
      }).bindPopup(popup(event)).addTo(layer);
    }

    var counter = document.getElementById("map-count");
    if (counter) counter.textContent = shown + (shown === 1 ? " event" : " events");
  }

  function bind(containerId, key) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.addEventListener("click", function (ev) {
      var chip = ev.target.closest(".chip");
      if (!chip || !container.contains(chip)) return;
      var chips = container.querySelectorAll(".chip");
      for (var i = 0; i < chips.length; i++) {
        chips[i].setAttribute("aria-pressed", chips[i] === chip ? "true" : "false");
      }
      state[key] = chip.getAttribute("data-value");
      draw();
    });
  }

  bind("f-type", "type");
  bind("f-when", "within");
  draw();
})();
