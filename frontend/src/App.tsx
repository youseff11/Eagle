import { useQueryClient } from "@tanstack/react-query";
import { Route, Routes } from "react-router";
import { qk } from "./api/keys";
import { Shell } from "./components/Shell";
import { useHeartbeat } from "./hooks/useHeartbeat";
import { HomePage } from "./pages/HomePage";
import { NotFound } from "./pages/NotFound";
import { NotificationsPage } from "./pages/NotificationsPage";
import { TranslatorHomePage } from "./pages/TranslatorHomePage";

export function App({ pollMs }: { pollMs: number }) {
  const client = useQueryClient();
  // The classic list pages fetch themselves again when the boards move; so do these.
  useHeartbeat(pollMs, () => void client.invalidateQueries({ queryKey: qk.boards }));
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<HomePage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="translator" element={<TranslatorHomePage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
