import { useQueryClient } from "@tanstack/react-query";
import { Route, Routes } from "react-router";
import { qk } from "./api/keys";
import { Shell } from "./components/Shell";
import { calls } from "./lib/calls";
import { useHeartbeat } from "./hooks/useHeartbeat";
import { AdminAuditPage } from "./pages/AdminAuditPage";
import { AdminClientFormPage } from "./pages/AdminClientFormPage";
import { AdminClientsPage } from "./pages/AdminClientsPage";
import { AdminOverviewPage } from "./pages/AdminOverviewPage";
import { AdminResetPage } from "./pages/AdminResetPage";
import { AdminSettingsPage } from "./pages/AdminSettingsPage";
import { AdminSimulatePage } from "./pages/AdminSimulatePage";
import { AdminUserNewPage, AdminUserPage } from "./pages/AdminUserPage";
import { AdminUsersPage } from "./pages/AdminUsersPage";
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
    // A call ringing for this person rings here, on whatever page they are on.
    (call) => calls.incoming(call),
  );
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<HomePage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="admin" element={<AdminOverviewPage />} />
        <Route path="admin/audit" element={<AdminAuditPage />} />
        <Route path="admin/clients" element={<AdminClientsPage />} />
        <Route path="admin/clients/new" element={<AdminClientFormPage />} />
        <Route path="admin/clients/:code/edit" element={<AdminClientFormPage />} />
        <Route path="admin/settings" element={<AdminSettingsPage />} />
        <Route path="admin/simulate" element={<AdminSimulatePage />} />
        <Route path="admin/reset-tasks" element={<AdminResetPage kind="tasks" />} />
        <Route path="admin/reset-mail" element={<AdminResetPage kind="mail" />} />
        <Route path="admin/users" element={<AdminUsersPage />} />
        <Route path="admin/users/new" element={<AdminUserNewPage />} />
        <Route path="admin/users/:id" element={<AdminUserPage />} />
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
