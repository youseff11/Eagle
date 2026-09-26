/* =========================================================================
   File previews - a file shown by its look, not only by its name.

   Every stored file the dashboard links to is served from /files/ (see
   dashboard/files.py). This script finds those links wherever they are drawn
   - the mailbox, the chat, a task page, the admin overview - and puts a card
   in front of each one:

     image  -> the picture itself
     PDF    -> its first page, drawn by pdf.js (loaded only when a PDF is on
               screen, from cdnjs)
     Word   -> the thumbnail Word saved inside the file, or else the opening
               lines of text on a page (/files/<path>?preview=1)
     other  -> left alone: the name link stays as it was

   Cards are filled only when they scroll into view, so a long mailbox does
   not download every attachment at once. A preview that cannot be drawn
   falls back to a plain page with the file type on it - the link still works.

   New links (the live chat, the inbox feed) are picked up by a
   MutationObserver, so no page has to call anything.
   ========================================================================= */

(function () {
  "use strict";

  var IMAGE = /\.(jpe?g|png|gif|webp|bmp)$/i;
  var PDF = /\.pdf$/i;
  var WORD = /\.(docx|docm|dotx|doc)$/i;
  var PDFJS = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js";
  var PDFJS_WORKER = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

  function t(ar, en) {
    return window.Eagle && window.Eagle.t ? window.Eagle.t(ar, en) : ar;
  }

  function pathOf(href) {
    try { return decodeURIComponent(new URL(href, location.href).pathname); }
    catch (error) { return href || ""; }
  }

  function kindOf(link) {
    var path = pathOf(link.getAttribute("href"));
    if (path.indexOf("/files/") !== 0) { return ""; }
    // The name the person sees is the better guide to the type: stored
    // names from before the rename may have lost nothing, new ones keep the
    // extension - either way one of the two has it.
    var shown = (link.textContent || "").trim();
    var probe = function (re) { return re.test(path) || re.test(shown); };
    if (probe(IMAGE)) { return "image"; }
    if (probe(PDF)) { return "pdf"; }
    if (probe(WORD)) { return "word"; }
    return "";
  }

  function extensionOf(link) {
    var match = /\.([a-z0-9]{1,5})$/i.exec(pathOf(link.getAttribute("href")));
    return match ? match[1].toUpperCase() : "FILE";
  }

  function skip(link) {
    return link.hasAttribute("data-no-preview") ||
      link.closest(".fprev") ||
      link.querySelector("img") ||
      link.closest(".voice") ||
      link.getAttribute("data-fprev-done") === "1";
  }

  /* ------------------------------------------------------------- the card */

  function makeCard(link, kind) {
    var card = document.createElement("a");
    card.className = "fprev fprev--" + kind;
    card.href = link.getAttribute("href");
    card.target = "_blank";
    card.rel = "noopener";
    var name = (link.textContent || "").trim();
    card.title = name;

    var page = document.createElement("span");
    page.className = "fprev__page is-loading";
    page.setAttribute("data-ext", extensionOf(link));
    card.appendChild(page);

    var label = document.createElement("span");
    label.className = "fprev__name";
    label.textContent = name || extensionOf(link);
    card.appendChild(label);

    card.setAttribute("data-kind", kind);
    return card;
  }

  function place(link, card) {
    link.setAttribute("data-fprev-done", "1");
    var holder = link.parentElement;
    // A chat bubble's file row: the card takes the row's place, the tick box
    // for "select files" stays where it was.
    if (holder && holder.classList.contains("bub__file")) {
      holder.classList.add("bub__file--card");
    }
    link.parentNode.insertBefore(card, link);
    link.classList.add("fprev-src");
  }

  /* ------------------------------------------------------------- fillers */

  function fallback(page, note) {
    page.classList.remove("is-loading");
    page.classList.add("is-plain");
    var ext = document.createElement("b");
    ext.textContent = page.getAttribute("data-ext") || "FILE";
    page.appendChild(ext);
    if (note) {
      var small = document.createElement("small");
      small.textContent = note;
      page.appendChild(small);
    }
  }

  function fillImage(card, page) {
    var img = new Image();
    img.alt = "";
    img.loading = "lazy";
    img.onload = function () { page.classList.remove("is-loading"); };
    img.onerror = function () { img.remove(); fallback(page); };
    img.src = card.getAttribute("href");
    page.appendChild(img);
  }

  var pdfjsReady = null;
  function loadPdfJs() {
    if (window.pdfjsLib) { return Promise.resolve(window.pdfjsLib); }
    if (pdfjsReady) { return pdfjsReady; }
    pdfjsReady = new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = PDFJS;
      script.async = true;
      script.onload = function () {
        if (!window.pdfjsLib) { reject(new Error("pdf.js")); return; }
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
        resolve(window.pdfjsLib);
      };
      script.onerror = function () { reject(new Error("pdf.js")); };
      document.head.appendChild(script);
    });
    return pdfjsReady;
  }

  function fillPdf(card, page) {
    loadPdfJs().then(function (lib) {
      return lib.getDocument({ url: card.getAttribute("href"), withCredentials: true }).promise;
    }).then(function (doc) {
      return doc.getPage(1).then(function (first) {
        var width = page.clientWidth || 150;
        var base = first.getViewport({ scale: 1 });
        var ratio = window.devicePixelRatio || 1;
        var viewport = first.getViewport({ scale: (width / base.width) * ratio });
        var canvas = document.createElement("canvas");
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        page.appendChild(canvas);
        return first.render({ canvasContext: canvas.getContext("2d"), viewport: viewport }).promise
          .then(function () {
            page.classList.remove("is-loading");
            if (doc.numPages > 1) {
              var count = document.createElement("span");
              count.className = "fprev__pages";
              count.textContent = doc.numPages + " " + t("صفحة", "pages");
              page.appendChild(count);
            }
          });
      });
    }).catch(function () { fallback(page); });
  }

  function fillWord(card, page) {
    var href = card.getAttribute("href");
    if (/\.doc$/i.test(pathOf(href)) && !/\.docx$/i.test(pathOf(href))) {
      // The old binary .doc: nothing a browser or the standard library can
      // read. Its type on a page is the honest preview.
      fallback(page, "Word");
      return;
    }
    var sep = href.indexOf("?") === -1 ? "?" : "&";
    fetch(href + sep + "preview=1", { credentials: "same-origin" })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        if (!data || !data.ok) { fallback(page, "Word"); return; }
        if (data.thumb) {
          var img = new Image();
          img.alt = "";
          img.onload = function () { page.classList.remove("is-loading"); };
          img.onerror = function () { img.remove(); textPage(page, data.text); };
          img.src = href + sep + "preview=thumb";
          page.appendChild(img);
          return;
        }
        textPage(page, data.text);
      })
      .catch(function () { fallback(page, "Word"); });
  }

  function textPage(page, text) {
    if (!text) { fallback(page, "Word"); return; }
    page.classList.remove("is-loading");
    page.classList.add("is-text");
    var sheet = document.createElement("span");
    sheet.className = "fprev__text";
    sheet.setAttribute("dir", "auto");
    sheet.textContent = text;
    page.appendChild(sheet);
  }

  function fill(card) {
    if (card.getAttribute("data-filled") === "1") { return; }
    card.setAttribute("data-filled", "1");
    var page = card.querySelector(".fprev__page");
    var kind = card.getAttribute("data-kind");
    if (kind === "image") { fillImage(card, page); }
    else if (kind === "pdf") { fillPdf(card, page); }
    else if (kind === "word") { fillWord(card, page); }
  }

  /* ------------------------------------------------------------- wiring */

  var observer = "IntersectionObserver" in window
    ? new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            observer.unobserve(entry.target);
            fill(entry.target);
          }
        });
      }, { rootMargin: "200px" })
    : null;

  function scan(root) {
    if (!root || !root.querySelectorAll) { return; }
    var links = root.querySelectorAll('a[href^="/files/"]');
    Array.prototype.forEach.call(links, function (link) {
      if (skip(link)) { return; }
      var kind = kindOf(link);
      if (!kind) { return; }
      var card = makeCard(link, kind);
      place(link, card);
      if (observer) { observer.observe(card); } else { fill(card); }
    });
  }

  function start() {
    scan(document.body);
    if (!("MutationObserver" in window)) { return; }
    var pending = false;
    new MutationObserver(function () {
      // Many nodes arrive at once when a chat redraws: one scan per frame.
      if (pending) { return; }
      pending = true;
      requestAnimationFrame(function () { pending = false; scan(document.body); });
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
