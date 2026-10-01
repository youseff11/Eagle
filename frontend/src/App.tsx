import { Route, Routes } from "react-router";
import { Shell } from "./components/Shell";
import { useHeartbeat } from "./hooks/useHeartbeat";
import { HomePage } from "./pages/HomePage";
import { NotFound } from "./pages/NotFound";
import { NotificationsPage } from "./pages/NotificationsPage";

export function App({ pollMs }: { pollMs: number }) {
  useHeartbeat(pollMs);
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<HomePage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
