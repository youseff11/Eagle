import { useQueryClient } from "@tanstack/react-query";
import { Route, Routes } from "react-router";
import { qk } from "./api/keys";
import { Shell } from "./components/Shell";
import { useHeartbeat } from "./hooks/useHeartbeat";
import { AssignmentPage } from "./pages/AssignmentPage";
import { AttendancePage } from "./pages/AttendancePage";
import { ClientPage } from "./pages/ClientPage";
import { ClientsPage } from "./pages/ClientsPage";
import { HomePage } from "./pages/HomePage";
import { InboxPage } from "./pages/InboxPage";
import { LeadBoardPage } from "./pages/LeadBoardPage";
import { LeadHomePage } from "./pages/LeadHomePage";
import { MailThreadPage } from "./pages/MailThreadPage";
import { NotFound } from "./pages/NotFound";
import { ChatsPage } from "./pages/ChatsPage";
import { NewTaskPage } from "./pages/NewTaskPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { PayrollPage } from "./pages/PayrollPage";
import { SalesLinePage } from "./pages/SalesLinePage";
import { TaskRoute } from "./pages/TaskRoute";
import { TasksPage } from "./pages/TasksPage";
import { TeamPage } from "./pages/TeamPage";
import { TranslatorHomePage } from "./pages/TranslatorHomePage";

export function App({ pollMs }: { pollMs: number }) {
  const client = useQueryClient();
  // The classic list pages fetch themselves again when the boards move; so do these.
  useHeartbeat(
    pollMs,
    () => void client.invalidateQueries({ queryKey: qk.boards }),
    (pending) => client.setQueryData(qk.pending, pending),
    (gate) => client.setQueryData(qk.gate, gate),
  );
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<HomePage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="translator" element={<TranslatorHomePage />} />
        <Route path="payroll" element={<PayrollPage />} />
        <Route path="assignments/:id" element={<AssignmentPage />} />
        <Route path="attendance" element={<AttendancePage />} />
        <Route path="inbox" element={<InboxPage />} />
        <Route path="inbox/thread/:id" element={<MailThreadPage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="tasks/new" element={<NewTaskPage />} />
        <Route path="tasks/:code" element={<TaskRoute />} />
        <Route path="lead" element={<LeadHomePage />} />
        <Route path="lead/translators" element={<LeadBoardPage />} />
        <Route path="line" element={<SalesLinePage />} />
        <Route path="clients" element={<ClientsPage />} />
        <Route path="clients/:code" element={<ClientPage />} />
        <Route path="team" element={<TeamPage />} />
        <Route path="chats" element={<ChatsPage />} />
        <Route path="chats/:code" element={<ChatsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
