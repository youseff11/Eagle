import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// Where Django runs while developing: `python -m daphne -p 8000 Core.asgi:application`
// (daphne, not runserver, so the WebSocket works too).
const DJANGO = process.env.DJANGO_ORIGIN ?? "http://localhost:8000";

/**
 * The icon sprite lives in a Django partial. In production the shell template
 * includes it; in development Vite has no template, so it is put into the page here.
 */
function iconSprite(): Plugin {
  return {
    name: "eagle-icon-sprite",
    apply: "serve",
    transformIndexHtml(html) {
      const file = resolve(import.meta.dirname, "../templates/partials/icons.html");
      // The first line is a Django comment; everything else is plain SVG.
      const sprite = readFileSync(file, "utf-8").replace(/\{#.*?#\}/g, "");
      return html.replace("<body>", `<body>\n${sprite}`);
    },
  };
}

export default defineConfig(({ command }) => ({
  plugins: [react(), iconSprite()],
  // In production Django serves these files under /static/app/. In development
  // Vite serves the page itself, from /.
  base: command === "build" ? "/static/app/" : "/",
  build: {
    outDir: "../static/app",
    emptyOutDir: true,
    // Not the default `.vite/manifest.json`: collectstatic skips dot-folders.
    manifest: "manifest.json",
    sourcemap: false,
    // The script is the entry, not index.html: Django renders the page itself
    // (templates/app/shell.html), so no HTML file should land in /static/.
    rollupOptions: { input: resolve(import.meta.dirname, "src/main.tsx") },
  },
  server: {
    port: 5173,
    proxy: {
      // The browser talks to Vite; Vite forwards to Django. Django's CSRF check compares the
      // request's Origin with its Host, so the two must still agree on the way through.
      // The browser's Origin is http://localhost:5173, so Host has to stay localhost:5173
      // too: that is why every entry is the object form, which leaves Host alone. The
      // string shorthand ("/api": DJANGO) switches on `changeOrigin`, Host becomes
      // Django's own, and every POST is refused as "does not match any trusted origins"
      // (checked against a real Django, with a Host/Origin matrix).
      // Development only: never point DJANGO_ORIGIN at a real server or start Vite with --host.
      "/api": { target: DJANGO },
      "/ws": { target: DJANGO, ws: true },
      "/static": { target: DJANGO },
      "/login": { target: DJANGO },
      "/logout": { target: DJANGO },
      "/files": { target: DJANGO },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
}));
