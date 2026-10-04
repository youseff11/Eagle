/* =========================================================================
   The pages that are still plain Django: sign-in, the public legal pages, the 403 page.
   The app itself (React, static/app/) carries its own language and theme; this is only
   - the language switch (texts live in the HTML as data-ar / data-en)
   - the dark / light switch
   and the cookie the server reads back (eagle_lang, eagle_theme). A signed-in person's choice is
   also stored on their account (cfg.prefsUrl); for somebody who is not signed in that call is
   refused and ignored, the cookie is enough.
   ========================================================================= */

(function () {
  "use strict";

  var cfg = window.EAGLE_CFG || {};
  var state = { lang: cfg.lang || "ar", theme: cfg.theme || "dark" };

  function $(selector) { return document.querySelector(selector); }
  function $$(selector) { return Array.prototype.slice.call(document.querySelectorAll(selector)); }

  function cookie(name) {
    var match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
    return match ? decodeURIComponent(match[2]) : "";
  }

  function remember(name, value) {
    document.cookie = name + "=" + value + ";path=/;max-age=31536000;samesite=Lax";
    if (!cfg.prefsUrl) { return; }
    var body = new FormData();
    body.append(name === "eagle_lang" ? "lang" : "theme", value);
    fetch(cfg.prefsUrl, {
      method: "POST",
      headers: { "X-CSRFToken": cookie("csrftoken"), "X-Requested-With": "XMLHttpRequest" },
      body: body,
      credentials: "same-origin"
    }).catch(function () { /* not signed in, or offline: the cookie already holds it */ });
  }

  function applyLang(lang, persist) {
    state.lang = lang;
    var root = document.documentElement;
    root.setAttribute("lang", lang === "ar" ? "ar" : "en");
    root.setAttribute("dir", lang === "ar" ? "rtl" : "ltr");

    $$("[data-ar]").forEach(function (el) {
      var value = el.getAttribute("data-" + lang);
      if (value === null || value === undefined) { return; }
      // data-html opts a node into rich markup (authored in our own templates).
      if (el.hasAttribute("data-html")) { el.innerHTML = value; } else { el.textContent = value; }
    });
    $$("[data-ar-ph]").forEach(function (el) {
      var value = el.getAttribute("data-" + lang + "-ph");
      if (value) { el.setAttribute("placeholder", value); }
    });
    $$("[data-ar-title]").forEach(function (el) {
      var value = el.getAttribute("data-" + lang + "-title");
      if (value) { el.setAttribute("title", value); }
    });
    $$("[data-lang-btn]").forEach(function (el) {
      el.classList.toggle("is-active", el.getAttribute("data-lang-btn") === lang);
    });
    if (persist !== false) { remember("eagle_lang", lang); }
  }

  function applyTheme(theme, persist) {
    state.theme = theme;
    document.documentElement.setAttribute("data-theme", theme);
    var icon = $("#themeIcon use");
    if (icon) { icon.setAttribute("href", theme === "dark" ? "#i-moon" : "#i-sun"); }
    if (persist !== false) { remember("eagle_theme", theme); }
  }

  document.addEventListener("DOMContentLoaded", function () {
    applyLang(state.lang, false);
    applyTheme(state.theme, false);
    $$("[data-lang-btn]").forEach(function (el) {
      el.addEventListener("click", function () { applyLang(el.getAttribute("data-lang-btn")); });
    });
    var toggle = $("#themeToggle");
    if (toggle) {
      toggle.addEventListener("click", function () { applyTheme(state.theme === "dark" ? "light" : "dark"); });
    }
  });
})();
