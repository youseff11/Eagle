import { useQueryClient } from "@tanstack/react-query";
import { Navigate, Route, Routes, useParams } from "react-router";
import { qk } from "./api/keys";
import { Shell } from "./components/Shell";
import { calls } from "./lib/calls";
import { useHeartbeat } from "./hooks/useHeartbeat";
import { AccountsAttendancePage } from "./pages/AccountsAttendancePage";
import { AccountsLinePage } from "./pages/AccountsLinePage";
import { AccountsOverviewPage } from "./pages/AccountsOverviewPage";
import { AccountsRulesPage } from "./pages/AccountsRulesPage";
import { AccountsSalaryPage } from "./pages/AccountsSalaryPage";
import { AccountsViolationsPage } from "./pages/AccountsViolationsPage";
import { HrAttendancePage } from "./pages/HrAttendancePage";
import { HrDayPage } from "./pages/HrDayPage";
import { HrLeavePage } from "./pages/HrLeavePage";
import { HrDevicesPage } from "./pages/HrDevicesPage";
import { HrOfficesPage } from "./pages/HrOfficesPage";
import { HrOvertimePage } from "./pages/HrOvertimePage";
import { HrReportPage } from "./pages/HrReportPage";
import { HrSchedulesPage } from "./pages/HrSchedulesPage";
import { HrComplaintsPage } from "./pages/HrComplaintsPage";
import { HrEmployeeNewPage } from "./pages/HrEmployeeNewPage";
import { HrEmployeePage } from "./pages/HrEmployeePage";
import { HrEmployeesPage } from "./pages/HrEmployeesPage";
import { HrPerformancePage } from "./pages/HrPerformancePage";
import { HrSalaryPlansPage } from "./pages/HrSalaryPlansPage";
import { HrSalaryRequestsPage } from "./pages/HrSalaryRequestsPage";
import { MyLeavePage } from "./pages/MyLeavePage";
import { HrShiftsPage } from "./pages/HrShiftsPage";
import { AdminClientFormPage } from "./pages/AdminClientFormPage";
import { AdminClientsPage } from "./pages/AdminClientsPage";
import { AdminOverviewPage } from "./pages/AdminOverviewPage";
import { AdminResetPage } from "./pages/AdminResetPage";
import { AdminSettingsPage } from "./pages/AdminSettingsPage";
import { AdminSimulatePage } from "./pages/AdminSimulatePage";
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
import { LeadSheetPage } from "./pages/LeadSheetPage";
import { LeadSheetsPage } from "./pages/LeadSheetsPage";
import { SalesPerformancePage } from "./pages/SalesPerformancePage";
import { VisitsPage } from "./pages/VisitsPage";
import { B2cPerformancePage } from "./pages/B2cPerformancePage";
import { CommissionsPage } from "./pages/CommissionsPage";
import { PriceListPage } from "./pages/PriceListPage";
import { AccountsInvoicePage } from "./pages/AccountsInvoicePage";
import { AccountsInvoicesPage } from "./pages/AccountsInvoicesPage";
import { CeoBoardPage } from "./pages/CeoBoardPage";
import { TaskRoute } from "./pages/TaskRoute";
import { TasksPage } from "./pages/TasksPage";
import { SupportAnnouncePage } from "./pages/SupportAnnouncePage";
import { TeamPage } from "./pages/TeamPage";
import { TranslatorHomePage } from "./pages/TranslatorHomePage";

/** An address saved from the staff panel (`/admin/users/5`) opens the same person's file in the employee files. */
function UserFile() {
  const { id } = useParams();
  return <Navigate to={`/hr/employees/${encodeURIComponent(id ?? "")}`} replace />;
}

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
        <Route path="accounts" element={<AccountsOverviewPage />} />
        <Route path="accounts/lines/:id" element={<AccountsLinePage />} />
        <Route path="accounts/attendance" element={<AccountsAttendancePage />} />
        <Route path="accounts/violations" element={<AccountsViolationsPage />} />
        <Route path="accounts/invoices" element={<AccountsInvoicesPage />} />
        <Route path="accounts/invoices/:id" element={<AccountsInvoicePage />} />
        <Route path="accounts/rules" element={<AccountsRulesPage />} />
        <Route path="accounts/salary/:id" element={<AccountsSalaryPage />} />
        <Route path="hr/attendance" element={<HrAttendancePage />} />
        <Route path="hr/attendance/:id" element={<HrDayPage />} />
        <Route path="hr/report" element={<HrReportPage />} />
        <Route path="hr/schedules" element={<HrSchedulesPage />} />
        <Route path="hr/shifts" element={<HrShiftsPage />} />
        <Route path="hr/employees" element={<HrEmployeesPage />} />
        <Route path="hr/employees/new" element={<HrEmployeeNewPage />} />
        <Route path="hr/employees/:id" element={<HrEmployeePage />} />
        <Route path="hr/performance" element={<HrPerformancePage />} />
        <Route path="hr/complaints" element={<HrComplaintsPage />} />
        <Route path="hr/salary-requests" element={<HrSalaryRequestsPage />} />
        <Route path="hr/salary-plans" element={<HrSalaryPlansPage />} />
        <Route path="hr/leave" element={<HrLeavePage />} />
        <Route path="hr/overtime" element={<HrOvertimePage />} />
        <Route path="leave" element={<MyLeavePage />} />
        <Route path="hr/offices" element={<HrOfficesPage />} />
        <Route path="hr/devices" element={<HrDevicesPage />} />
        <Route path="admin" element={<AdminOverviewPage />} />
        <Route path="admin/ceo" element={<CeoBoardPage />} />
        <Route path="admin/clients" element={<AdminClientsPage />} />
        <Route path="admin/clients/new" element={<AdminClientFormPage />} />
        <Route path="admin/clients/:code/edit" element={<AdminClientFormPage />} />
        <Route path="admin/settings" element={<AdminSettingsPage />} />
        <Route path="admin/simulate" element={<AdminSimulatePage />} />
        <Route path="admin/reset-tasks" element={<AdminResetPage kind="tasks" />} />
        <Route path="admin/reset-staff" element={<AdminResetPage kind="staff" />} />
        <Route path="admin/reset-mail" element={<AdminResetPage kind="mail" />} />
        {/* The staff panel was folded into the employee files: the addresses that were saved still arrive. */}
        <Route path="admin/users" element={<Navigate to="/hr/employees" replace />} />
        <Route path="admin/users/new" element={<Navigate to="/hr/employees/new" replace />} />
        <Route path="admin/users/:id" element={<UserFile />} />
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
        <Route path="leads" element={<LeadSheetsPage />} />
        <Route path="leads/:id" element={<LeadSheetPage />} />
        {/* B2C (15/10/2026): the companies inside Egypt are sheets too (one page for both teams), and the field visits. */}
        <Route path="b2c" element={<LeadSheetsPage market="b2c" />} />
        <Route path="b2c/visits" element={<VisitsPage />} />
        <Route path="b2c/performance" element={<B2cPerformancePage />} />
        <Route path="commissions" element={<CommissionsPage />} />
        <Route path="price-list" element={<PriceListPage />} />
        <Route path="sales-performance" element={<SalesPerformancePage />} />
        <Route path="clients" element={<ClientsPage />} />
        <Route path="clients/:code" element={<ClientPage />} />
        <Route path="team" element={<TeamPage />} />
        <Route path="announce" element={<SupportAnnouncePage />} />
        <Route path="chats" element={<ChatsPage />} />
        <Route path="chats/:code" element={<ChatsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
