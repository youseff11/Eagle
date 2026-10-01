# Eagle front end (React)

The new interface. Django serves one page at `/app/` (`dashboard/spa.py`,
`templates/app/shell.html`) and this app draws everything inside it. It talks only to
`/api/v1/` and to `/ws/events/`; every permission is decided by Django.

It lives beside the classic interface and replaces it screen by screen. Nothing here
changes a classic page.

## Commands

```
cd frontend
npm ci              # install exactly what package-lock.json says
npm test            # the unit tests (Vitest + Testing Library)
npm run typecheck   # tsc, no output
npm run build       # writes ../static/app (gitignored); `npm run build` also type-checks
npm run dev         # Vite on http://localhost:5173/app/, proxying to Django
```

The Python side of the gate (`python .claude/verify.py`) does not run these; run
`npm test` and `npm run build` yourself before pushing a change in `frontend/`.

## Developing

Django must run as an ASGI server for the WebSocket to work, so not `runserver`:

```
python -m daphne -p 8000 Core.asgi:application
```

Sign in once at `http://localhost:8000/login/`, then open `http://localhost:5173/app/`.
Vite forwards `/api`, `/ws`, `/static`, `/login`, `/logout` and `/files` to Django,
leaving the browser's own `Host` and `Origin` (both `localhost:5173`) alone, because that
is what Django's CSRF check compares. Keep every proxy entry in the object form
(`{ target: ... }`): the string shorthand turns on `changeOrigin`, which makes Host
Django's own and every POST is refused. The session cookie is shared because both are
`localhost`. This is for development only: never point `DJANGO_ORIGIN` at a real server
(a production session cookie would sit in the `localhost` cookie jar) and never start
Vite with `--host`.

## How it is served

`npm run build` writes `static/app/assets/main-<hash>.js|css` and `manifest.json`.
`dashboard/spa.py` reads that manifest to put the right file names in the page, and
`collectstatic` hashes them again for production. On Render the build command runs
the front-end build first (`render.yaml`). `static/app/` is never committed.

## What is here

| Path | What |
|---|---|
| `src/api/client.ts` | The one `fetch` wrapper: JSON, CSRF header, `ApiError` with the server's error code, one handler for 401. |
| `src/api/queries.ts`, `keys.ts` | TanStack Query hooks and the keys a doorbell invalidates. |
| `src/realtime/connection.ts` | The WebSocket: ping, pong watchdog, jittered reconnect (the delay starts over only after ten stable seconds), 4401 stops, 4429 waits. The server sends those two codes only after accepting; refused at the handshake the browser sees a plain failure and the normal delays apply. No React in it. |
| `src/realtime/RealtimeProvider.tsx` | Turns a doorbell into "refetch that". While the socket is not open the queries poll every 15 s instead. |
| `src/hooks/useHeartbeat.ts` | Keeps `/api/heartbeat/` going: presence and housekeeping. What the answer carries that only the classic interface can show sends the person there: the mandatory check-in screen, an assignment waiting for its 60-second answer, a ringing call. The check-out and extra-time reminders can be put off, so they do not. |
| `src/i18n/Preferences.tsx` | Language and theme. Saved through `/api/prefs/`, like the classic pages. |
| `src/components/`, `src/pages/` | The shell and the screens. |

## Rules

- **Every text in both languages**, at the place it is written: `t("عربي", "English")`.
  Arabic is the default and the page is right-to-left.
- **Icons come from the server's sprite** (`templates/partials/icons.html`). A name that is
  not there draws an empty box; `src/test/icons.test.tsx` fails if the app draws one.
  There is no `chat` icon (use `message`) and no `ic--xs` size.
- **Use the design tokens and classes of `static/css/app.css`** (`--border`, `.card`, `.btn`,
  `.note`, `.nav__item` ...). `src/styles.css` holds only what the new app adds.
- **No emoji**, in code or comments.
- **Times and dates come formatted from the server** (Cairo, 12 hours). The app never
  formats a time itself.
- **A link from the server is checked** with `safeInternalPath` before it goes in an `href`.
- **The socket carries no data**, only "something changed"; the answer comes from the API.
