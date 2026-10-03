import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { App } from "./App";
import { ApiError, setUnauthorizedHandler } from "./api/client";
import { qk } from "./api/keys";
import { readConfig } from "./config";
import { PreferencesProvider } from "./i18n/Preferences";
import { redirectToLogin } from "./lib/navigation";
import { RealtimeProvider } from "./realtime/RealtimeProvider";
import "./styles.css";

const config = readConfig();

// A 401 from anywhere means the session ended: sign in again and come back.
setUnauthorizedHandler(redirectToLogin);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      // Asking again will not make a refusal go away; a dropped connection is worth one more try.
      retry: (failures, error) => !(error instanceof ApiError && error.status < 500) && failures < 1,
    },
  },
});

// What the check-in screen asks at this moment, from the page itself: on the first paint, not a beat later.
queryClient.setQueryData(qk.gate, config.gate);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <PreferencesProvider initialLang={config.lang} initialTheme={config.theme}>
        <BrowserRouter basename="/app">
          <RealtimeProvider>
            <App pollMs={config.pollMs} />
          </RealtimeProvider>
        </BrowserRouter>
      </PreferencesProvider>
    </QueryClientProvider>
  </StrictMode>,
);
