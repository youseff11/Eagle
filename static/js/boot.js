/*
 * Loads before the app's script. If that script fails to arrive (a server restarting during a deploy answers 503 or 404,
 * and a browser or the edge may keep the answer), it asks again under a new address, a few times, and after that says
 * so with a button instead of leaving a blank page. No inline script: the page's policy allows scripts from this site only.
 */
(function () {
  var DELAYS = [1500, 3000, 6000, 10000];
  var tries = 0;

  function say(root) {
    if (!root || root.childNodes.length) return;
    var ar = (document.documentElement.lang || "ar").slice(0, 2) !== "en";
    var box = document.createElement("div");
    box.style.cssText = "display:flex;flex-direction:column;align-items:center;gap:12px;padding:48px 16px;font:14px sans-serif;color:#9aa4b2;text-align:center";
    var text = document.createElement("p");
    text.textContent = ar ? "تعذّر تحميل التطبيق. حاول مرة تانية." : "The app could not be loaded. Please try again.";
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = ar ? "إعادة التحميل" : "Reload";
    button.style.cssText = "padding:8px 18px;border-radius:8px;border:1px solid #3a4250;background:transparent;color:inherit;cursor:pointer";
    button.addEventListener("click", function () { window.location.reload(); });
    box.appendChild(text);
    box.appendChild(button);
    root.appendChild(box);
  }

  window.addEventListener("error", function (event) {
    var failed = event.target;
    if (!failed || failed.tagName !== "SCRIPT" || failed.type !== "module" || !failed.src) return;
    if (tries >= DELAYS.length) {
      say(document.getElementById("root"));
      return;
    }
    var delay = DELAYS[tries];
    tries += 1;
    var base = failed.src.split("?")[0];
    window.setTimeout(function () {
      var again = document.createElement("script");
      again.type = "module";
      again.src = base + "?retry=" + tries + "-" + Date.now();
      document.body.appendChild(again);
    }, delay);
  }, true);
})();
