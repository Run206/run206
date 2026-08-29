/* Run206 — progressive enhancement only.
 *
 * Every event is already in the HTML when this file runs. Nothing is fetched
 * and nothing is rendered here; this only hides rows that don't match the
 * current filters, keeps the group counts honest, and mirrors filter state into
 * the URL so a filtered view can be shared.
 *
 * Type and distance are multi-select: an empty selection means "all", so the
 * "All" chip is a clear button rather than a separate mode. Someone can ask for
 * races and club runs but not brand events, which single-select couldn't do.
 */
(function () {
  "use strict";

  var root = document.documentElement;
  var list = document.getElementById("list");
  if (!list) return;

  var rows = Array.prototype.slice.call(list.querySelectorAll(".row"));
  var groups = Array.prototype.slice.call(list.querySelectorAll(".group"));
  var empty = document.getElementById("empty");
  var searchInput = document.getElementById("search");
  var summary = document.getElementById("summary");
  var freeToggle = document.getElementById("f-free");

  var state = { types: [], dists: [], free: false, q: "" };

  /* ---------- theme ---------- */

  var toggle = document.getElementById("theme");
  function applyTheme(mode) {
    if (mode === "light" || mode === "dark") {
      root.setAttribute("data-theme", mode);
    } else {
      root.removeAttribute("data-theme");
    }
    if (toggle) {
      var dark = mode === "dark" ||
        (mode !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
      toggle.textContent = dark ? "☀" : "☾";
      toggle.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
    }
  }
  try { applyTheme(localStorage.getItem("run206-theme")); } catch (e) { applyTheme(null); }

  if (toggle) {
    toggle.addEventListener("click", function () {
      var isDark = root.getAttribute("data-theme") === "dark" ||
        (!root.getAttribute("data-theme") &&
          window.matchMedia("(prefers-color-scheme: dark)").matches);
      var next = isDark ? "light" : "dark";
      applyTheme(next);
      try { localStorage.setItem("run206-theme", next); } catch (e) {}
    });
  }

  /* ---------- filtering ---------- */

  /* Search text comes from the row itself rather than a duplicated data-text
     attribute, computed once per row and cached. */
  var cache = typeof WeakMap !== "undefined" ? new WeakMap() : null;
  function haystack(row) {
    if (cache) {
      var hit = cache.get(row);
      if (hit !== undefined) return hit;
    }
    var text = (row.textContent || "").toLowerCase().replace(/\s+/g, " ");
    if (cache) cache.set(row, text);
    return text;
  }

  function matches(row) {
    // An empty selection means no constraint, so "All" needs no special case.
    if (state.types.length &&
        state.types.indexOf(row.getAttribute("data-type")) === -1) return false;

    if (state.dists.length) {
      var tags = (row.getAttribute("data-tags") || "").split(",");
      var hit = false;
      for (var i = 0; i < state.dists.length; i++) {
        if (tags.indexOf(state.dists[i]) !== -1) { hit = true; break; }
      }
      if (!hit) return false;   // union, not intersection: 5K OR Half
    }

    if (state.free && row.getAttribute("data-free") !== "1") return false;
    if (state.q && haystack(row).indexOf(state.q) === -1) return false;
    return true;
  }

  function apply() {
    var visible = 0;
    for (var i = 0; i < rows.length; i++) {
      var ok = matches(rows[i]);
      rows[i].hidden = !ok;
      if (ok) visible++;
    }

    for (var g = 0; g < groups.length; g++) {
      var shown = groups[g].querySelectorAll(".row:not([hidden])").length;
      groups[g].hidden = shown === 0;
      var count = groups[g].querySelector(".group-count");
      if (count) count.textContent = shown;
    }

    if (empty) empty.style.display = visible ? "none" : "block";
    if (summary) {
      summary.textContent = visible === rows.length
        ? "Showing all " + rows.length + " events"
        : "Showing " + visible + " of " + rows.length + " events";
    }
    syncUrl();
  }

  function syncUrl() {
    if (!window.history || !window.history.replaceState) return;
    var params = new URLSearchParams();
    function slug(v) { return v.toLowerCase().replace(/ /g, "-"); }
    if (state.types.length) params.set("type", state.types.map(slug).join(","));
    if (state.dists.length) params.set("d", state.dists.map(slug).join(","));
    if (state.free) params.set("free", "1");
    if (state.q) params.set("q", state.q);
    var qs = params.toString();
    window.history.replaceState(null, "", qs ? "?" + qs : window.location.pathname);
  }

  /* ---------- multi-select chip groups ---------- */

  function paint(container, selected) {
    var chips = container.querySelectorAll(".chip");
    for (var i = 0; i < chips.length; i++) {
      var value = chips[i].getAttribute("data-value");
      var on = value === "All" ? selected.length === 0
                               : selected.indexOf(value) !== -1;
      chips[i].setAttribute("aria-pressed", on ? "true" : "false");
    }
  }

  function bindChips(containerId, key) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.addEventListener("click", function (event) {
      var chip = event.target.closest(".chip");
      if (!chip || !container.contains(chip)) return;
      var value = chip.getAttribute("data-value");

      if (value === "All") {
        state[key] = [];                       // "All" clears the selection
      } else {
        var at = state[key].indexOf(value);
        if (at === -1) state[key].push(value);
        else state[key].splice(at, 1);
      }
      paint(container, state[key]);
      apply();
    });
    paint(container, state[key]);
  }

  if (freeToggle) {
    freeToggle.addEventListener("click", function () {
      state.free = !state.free;
      freeToggle.setAttribute("aria-pressed", state.free ? "true" : "false");
      apply();
    });
  }

  if (searchInput) {
    var timer = null;
    searchInput.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        state.q = searchInput.value.trim().toLowerCase();
        apply();
      }, 120);
    });
  }

  /* ---------- restore state from the URL ---------- */

  function restore(containerId, param, key) {
    var container = document.getElementById(containerId);
    var raw = new URLSearchParams(window.location.search).get(param);
    if (!container || !raw) return;
    var wanted = raw.split(",");
    var chips = container.querySelectorAll(".chip");
    for (var i = 0; i < chips.length; i++) {
      var value = chips[i].getAttribute("data-value");
      if (value === "All") continue;
      if (wanted.indexOf(value.toLowerCase().replace(/ /g, "-")) !== -1) {
        state[key].push(value);
      }
    }
  }

  var initial = new URLSearchParams(window.location.search);
  restore("f-type", "type", "types");
  restore("f-dist", "d", "dists");
  if (initial.get("free") === "1" && freeToggle) {
    state.free = true;
    freeToggle.setAttribute("aria-pressed", "true");
  }
  if (initial.get("q") && searchInput) {
    searchInput.value = initial.get("q");
    state.q = initial.get("q").trim().toLowerCase();
  }

  bindChips("f-type", "types");
  bindChips("f-dist", "dists");
  apply();
})();
