/* Run206 — progressive enhancement only.
 *
 * Every event is already in the HTML when this file runs. Nothing is fetched
 * and nothing is rendered here; this only hides rows that don't match the
 * current filters, keeps the group counts honest, and mirrors filter state into
 * the URL so a filtered view can be shared.
 *
 * Groups are baked in at build time, so filtering never has to move an event
 * between sections — it only hides rows and then hides any section left empty.
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

  var state = { type: "All", dist: "All", q: "" };

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

  function matches(row) {
    if (state.type !== "All" && row.getAttribute("data-type") !== state.type) return false;

    if (state.dist === "Free") {
      if (row.getAttribute("data-free") !== "1") return false;
    } else if (state.dist !== "All") {
      var tags = (row.getAttribute("data-tags") || "").split(",");
      if (tags.indexOf(state.dist) === -1) return false;
    }

    if (state.q) {
      if (haystack(row).indexOf(state.q) === -1) return false;
    }
    return true;
  }

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
      summary.textContent = visible + (visible === 1 ? " event" : " events");
    }
    syncUrl();
  }

  function syncUrl() {
    if (!window.history || !window.history.replaceState) return;
    var params = new URLSearchParams();
    if (state.type !== "All") params.set("type", state.type.toLowerCase().replace(/ /g, "-"));
    if (state.dist !== "All") params.set("d", state.dist.toLowerCase());
    if (state.q) params.set("q", state.q);
    var qs = params.toString();
    window.history.replaceState(null, "", qs ? "?" + qs : window.location.pathname);
  }

  function bindChips(containerId, key) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.addEventListener("click", function (event) {
      var chip = event.target.closest(".chip");
      if (!chip || !container.contains(chip)) return;
      var buttons = container.querySelectorAll(".chip");
      for (var i = 0; i < buttons.length; i++) {
        buttons[i].setAttribute("aria-pressed", buttons[i] === chip ? "true" : "false");
      }
      state[key] = chip.getAttribute("data-value");
      apply();
    });
  }

  bindChips("f-type", "type");
  bindChips("f-dist", "dist");

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

  function selectChip(containerId, value, key) {
    var container = document.getElementById(containerId);
    if (!container || !value) return;
    var buttons = container.querySelectorAll(".chip");
    for (var i = 0; i < buttons.length; i++) {
      var candidate = buttons[i].getAttribute("data-value");
      if (candidate.toLowerCase().replace(/ /g, "-") === value.toLowerCase()) {
        for (var j = 0; j < buttons.length; j++) {
          buttons[j].setAttribute("aria-pressed", buttons[j] === buttons[i] ? "true" : "false");
        }
        state[key] = candidate;
        return;
      }
    }
  }

  var initial = new URLSearchParams(window.location.search);
  selectChip("f-type", initial.get("type"), "type");
  selectChip("f-dist", initial.get("d"), "dist");
  if (initial.get("q") && searchInput) {
    searchInput.value = initial.get("q");
    state.q = initial.get("q").trim().toLowerCase();
  }

  apply();
})();
