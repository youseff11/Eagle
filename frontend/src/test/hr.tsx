import { Route, Routes, useLocation } from "react-router";
import { vi } from "vitest";
import type { FormField, Role } from "../api/types";
import { HrAttendancePage } from "../pages/HrAttendancePage";
import { HrDayPage } from "../pages/HrDayPage";
import { HrDevicesPage } from "../pages/HrDevicesPage";
import { HrLeavePage } from "../pages/HrLeavePage";
import { HrOfficesPage } from "../pages/HrOfficesPage";
import { HrOvertimePage } from "../pages/HrOvertimePage";
import { HrReportPage } from "../pages/HrReportPage";
import { HrSchedulesPage } from "../pages/HrSchedulesPage";
import { HrShiftsPage } from "../pages/HrShiftsPage";
import { HrComplaintsPage } from "../pages/HrComplaintsPage";
import { HrEmployeeNewPage } from "../pages/HrEmployeeNewPage";
import { HrEmployeePage } from "../pages/HrEmployeePage";
import { HrEmployeesPage } from "../pages/HrEmployeesPage";
import { HrPerformancePage } from "../pages/HrPerformancePage";
import { HrProbationPage } from "../pages/HrProbationPage";
import { HrApprovalsPage } from "../pages/HrApprovalsPage";
import { HrCandidatePage } from "../pages/HrCandidatePage";
import { HrCandidatesPage } from "../pages/HrCandidatesPage";
import { HrHirePage } from "../pages/HrHirePage";
import { HrInterviewPage } from "../pages/HrInterviewPage";
import { HrQuestionsPage } from "../pages/HrQuestionsPage";
import { ReviewerTestPage } from "../pages/ReviewerTestPage";
import { ReviewerTestsPage } from "../pages/ReviewerTestsPage";
import { HrRecruitmentPage } from "../pages/HrRecruitmentPage";
import { HrRecruitmentSettingsPage } from "../pages/HrRecruitmentSettingsPage";
import { HrSalaryPlansPage } from "../pages/HrSalaryPlansPage";
import { HrSalaryRequestsPage } from "../pages/HrSalaryRequestsPage";
import { HrVacanciesPage } from "../pages/HrVacanciesPage";
import { HrVacancyPage } from "../pages/HrVacancyPage";
import { MyLeavePage } from "../pages/MyLeavePage";
import { ToastProvider } from "../components/Toasts";
import { jsonResponse, me, mockFetch, renderWithProviders } from "./helpers";

/** Shared by the tests of the HR pages: a fake server that answers by the longest address first, and every HR route. */
export type Handler = (url: URL, init: RequestInit | undefined) => Response | Promise<Response>;

export const stampOf = (ar: string, en: string) => ({ ar, en });

export function field(name: string, label: string, over: Partial<FormField> = {}): FormField {
  return { name, label, kind: "text", required: false, help: "", disabled: false, ltr: false, value: "", ...over };
}

/**
 * Stub `fetch` with `routes`. `mockFetch` answers with the first address that is a prefix of the request, so the most specific
 * address has to come first: they are sorted by length here, and a test never has to think about the order it wrote them in.
 */
export function serveHr(who: Role, routes: Record<string, Handler>) {
  const sent: { url: string; body: unknown }[] = [];
  const record = (url: URL, init: RequestInit | undefined, answer: unknown, status = 200) => {
    sent.push({ url: url.pathname, body: init?.body ? JSON.parse(String(init.body)) : null });
    return jsonResponse(answer, status);
  };
  const merged: Record<string, Handler> = { "/api/v1/me/": () => jsonResponse(me({ role: who, is_admin: who === "admin" })), ...routes };
  const sorted = Object.fromEntries(Object.entries(merged).sort(([a], [b]) => b.length - a.length));
  const mocked = mockFetch(sorted);
  vi.stubGlobal("fetch", mocked.fn);
  return { ...mocked, sent, record };
}

export type Served = ReturnType<typeof serveHr>;

export function Where() {
  const where = useLocation();
  return <div data-testid="where">{where.pathname + where.search}</div>;
}

export function openHr(route: string, lang: "ar" | "en" = "ar") {
  return renderWithProviders(
    <ToastProvider>
      <Routes>
        <Route path="/hr/attendance" element={<HrAttendancePage />} />
        <Route path="/hr/attendance/:id" element={<HrDayPage />} />
        <Route path="/hr/report" element={<HrReportPage />} />
        <Route path="/hr/schedules" element={<HrSchedulesPage />} />
        <Route path="/hr/shifts" element={<HrShiftsPage />} />
        <Route path="/hr/overtime" element={<HrOvertimePage />} />
        <Route path="/hr/offices" element={<HrOfficesPage />} />
        <Route path="/hr/devices" element={<HrDevicesPage />} />
        <Route path="/hr/complaints" element={<HrComplaintsPage />} />
        <Route path="/hr/employees/new" element={<HrEmployeeNewPage />} />
        <Route path="/hr/employees/:id" element={<HrEmployeePage />} />
        <Route path="/hr/employees" element={<HrEmployeesPage />} />
        <Route path="/hr/performance" element={<HrPerformancePage />} />
        <Route path="/hr/probation" element={<HrProbationPage />} />
        <Route path="/hr/salary-plans" element={<HrSalaryPlansPage />} />
        <Route path="/hr/salary-requests" element={<HrSalaryRequestsPage />} />
        <Route path="/hr/leave" element={<HrLeavePage />} />
        <Route path="/hr/recruitment" element={<HrRecruitmentPage />} />
        <Route path="/hr/recruitment/settings" element={<HrRecruitmentSettingsPage />} />
        <Route path="/hr/vacancies" element={<HrVacanciesPage />} />
        <Route path="/hr/vacancies/:code" element={<HrVacancyPage />} />
        <Route path="/hr/questions" element={<HrQuestionsPage />} />
        <Route path="/hr/candidates/:code/hire" element={<HrHirePage />} />
        <Route path="/hr/candidates/:code" element={<HrCandidatePage />} />
        <Route path="/hr/candidates" element={<HrCandidatesPage />} />
        <Route path="/hr/interviews/:id" element={<HrInterviewPage />} />
        <Route path="/hr/approvals" element={<HrApprovalsPage />} />
        <Route path="/reviewer/tests/:id" element={<ReviewerTestPage />} />
        <Route path="/reviewer/tests" element={<ReviewerTestsPage />} />
        <Route path="/leave" element={<MyLeavePage />} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
      <Where />
    </ToastProvider>,
    { route, lang },
  );
}

/** The addresses a page read (not wrote) under `prefix`, in order. */
export const reads = (served: Served, prefix: string) =>
  served.calls.filter((call) => call.url.startsWith(prefix) && call.init?.method !== "POST").map((call) => call.url);

/** A date or time box takes its whole value at once (typing it a key at a time is not how a browser fills one). */
export function fireValue(input: HTMLElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}
