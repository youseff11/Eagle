import { Loading } from "../components/Loading";
import { useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router";
import { useSyncAliases } from "../api/adminActions";
import { ApiError } from "../api/client";
import { useAssignPlan, usePickHrShift } from "../api/hrActions";
import { useAdminUser, useHrEmployee } from "../api/queries";
import { Waiting, refusal } from "../components/accounts/shared";
import { AccountCard, PenaltiesCard } from "../components/hr/AccountCard";
import { RosterCard } from "../components/hr/RosterCard";
import { useHrAllowed } from "../components/hr/shared";
import { WorkModeCard } from "../components/hr/WorkModeCard";
import { Avatar } from "../components/Avatar";
import { Icon } from "../components/Icon";
import { LeaveStatusBadge, useLeaveWords } from "../components/leave/shared";
import { ShiftPicker } from "../components/ShiftPicker";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { minutesHm } from "../lib/payroll";

/**
 * One person's file, the only one: who they are, this month's attendance, the roster and the cards HR keeps up (the shift, home or
 * office), probation, recent leave, the pay plan and the salary history. What only the admin does is on the same page: the account
 * form (the button in the head), the roster rows typed by hand, the rating penalties, assigning a pay plan.
 */
export function HrEmployeePage() {
  const { t } = usePreferences();
  const words = useLeaveWords();
  const { push } = useToasts();
  const { me, allowed } = useHrAllowed();
  const params = useParams();
  const id = Number(params.id);
  const query = useHrEmployee(id, allowed);
  const pickShift = usePickHrShift(id);
  const assign = useAssignPlan(id);
  const [plan, setPlan] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const data = query.data;
  const canEdit = data?.can.edit === true;
  // The admin's half of the file is asked for with HR's, at the same time, by whoever is the admin (`/me/` says so): not after
  // HR's answer has come, which would be a second wait before the page is whole.
  const isAdmin = me.data?.user.is_admin === true;
  const admin = useAdminUser(id, isAdmin);
  // The address list is Google's: refreshed as the file opens (at most once a minute, the server decides), then read again.
  const asked = useSyncAliases(id).mutate;
  useEffect(() => {
    if (isAdmin) asked();
  }, [isAdmin, id, asked]);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!Number.isInteger(id) || id <= 0 || (query.error instanceof ApiError && query.error.status === 404)) {
    return (
      <div className="card empty" role="alert">
        <span>{t("الصفحة دي مش موجودة.", "That page does not exist.")}</span>
      </div>
    );
  }
  if (!data) return <Waiting failed={query.isError} />;
  const { person, summary } = data;
  const exempt = person.exempt;
  const kv = (ar: string, en: string, value: string | number | null | undefined, mono = false) => (
    <div className="kv" key={en}>
      <span>{t(ar, en)}</span>
      <b className={mono ? "mono" : undefined}>{value === null || value === undefined || value === "" ? "—" : value}</b>
    </div>
  );
  const chosenPlan = plan ?? String(data.plan.current?.id ?? "");
  const savePlan = () =>
    assign.mutate(chosenPlan ? Number(chosenPlan) : null, {
      onSuccess: () => {
        setPlan(null);
        push({ level: "success", title: t("اتسجل", "Recorded") });
      },
      onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) }),
    });

  return (
    <>
      <div className="page-head">
        <Avatar src={person.avatar} initials={person.initials} tone="" className="avatar--lg" />
        <h1>{person.name}</h1>
        {admin.data && <small className="muted mono">{admin.data.user.username}</small>}
        <span className="chip">{words(person.role)}</span>
        <LeaveStatusBadge status={person.status} />
        <div className="grow" />
        <Link className="btn btn--sm" to="/hr/employees">
          {t("كل الموظفين", "All staff")}
        </Link>
        {data.can.edit && (
          <button className="btn btn--sm btn--ghost" type="button" aria-pressed={editing} onClick={() => setEditing(!editing)}>
            <Icon name="pen" size="sm" />
            <span>{t("عدّل", "Edit")}</span>
          </button>
        )}
      </div>

      <div className="grid grid--main">
        <div className="stack">
          {editing &&
            (admin.data ? (
              <AccountCard id={id} data={admin.data} onClose={() => setEditing(false)} />
            ) : (
              admin.isError ? (
                <div className="card empty" role="alert">
                  <Icon name="alert" size="xl" />
                  <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
                </div>
              ) : (
                <Loading className="card empty" />
              )
            ))}
          <div className="card">
            <div className="card__head">
              <Icon name="contact" />
              <h3>{t("البيانات", "Details")}</h3>
            </div>
            <div className="grid grid--2">
              <div>
                {kv("كود الموظف", "Employee ID", person.code, true)}
                {kv("المسمى", "Position", person.job_title)}
                {kv("القسم", "Department", person.department)}
                {kv("المدير المباشر", "Manager", person.manager)}
                {kv("اللغات", "Languages", person.languages)}
              </div>
              <div>
                {kv("تاريخ الانضمام", "Joining date", person.joining_date, true)}
                {kv("نوع التوظيف", "Employment type", words(person.employment))}
                {kv("نظام العمل", "Work mode", person.work_mode ? words(person.work_mode) : null)}
                {kv("فترة الاختبار", "Probation", `${person.probation_start ?? "—"} → ${person.probation_end ?? "—"}`, true)}
                {kv("الموبايل", "Phone", person.phone, true)}
              </div>
            </div>
          </div>

          {exempt ? (
            <div className="note note--info" data-note="exempt">
              <Icon name="info" />
              <div>{t("الأدمن صاحب الشركة: مالوش حضور ولا جدول ولا إجازات ولا راتب.", "The owner has no attendance, roster, leave or pay: the company's rules are for the people who work for it.")}</div>
            </div>
          ) : summary ? (
            <div className="card" data-card="attendance">
              <div className="card__head">
                <Icon name="timer" />
                <h3>{t("حضور الشهر ده", "Attendance this month")}</h3>
                <div className="grow" />
                <Link className="btn btn--sm btn--ghost" to={`/hr/report?user=${person.id}`}>
                  {t("التقرير الكامل", "Full report")}
                </Link>
              </div>
              <div className="grid grid--4">
                <div className="kpi">
                  <div className="kpi__label">{t("أيام حضور", "Present")}</div>
                  <div className="kpi__value mono">
                    {summary.present_days} / {summary.scheduled_days}
                  </div>
                </div>
                <div className={`kpi${summary.late_days ? " kpi--warn" : ""}`}>
                  <div className="kpi__label">{t("تأخير", "Late")}</div>
                  <div className="kpi__value mono">{summary.late_days}</div>
                </div>
                <div className="kpi">
                  <div className="kpi__label">{t("ساعات", "Hours")}</div>
                  <div className="kpi__value mono">{minutesHm(summary.work_minutes)}</div>
                </div>
                <div className="kpi">
                  <div className="kpi__label">{t("أوفرتايم", "Overtime")}</div>
                  <div className="kpi__value mono">{minutesHm(summary.overtime_minutes)}</div>
                </div>
              </div>
              <div className="row row--tight mt">
                <span className="chip">
                  Office <b className="mono">{summary.office_days}</b>
                </span>
                <span className="chip">
                  Remote <b className="mono">{summary.remote_days}</b>
                </span>
                <span className="chip">
                  {t("إجازات", "Leave")} <b className="mono">{summary.leave_days}</b>
                </span>
                <span className="chip">
                  {t("غياب", "Absent")} <b className="mono">{summary.absent_days}</b>
                </span>
              </div>
            </div>
          ) : (
            <div className="note note--info" data-note="attendance-off">
              <Icon name="info" />
              <div>{t("الحضور مقفول للحساب ده.", "Attendance is off for this account.")}</div>
            </div>
          )}
        </div>

        <div className="sticky-side">
          {data.picker && <ShiftPicker picker={data.picker} save={(choice, options) => pickShift.mutate(choice, options)} pending={pickShift.isPending} />}
          {data.work_mode_card && <WorkModeCard id={person.id} card={data.work_mode_card} />}

          {!exempt && <RosterCard id={person.id} rows={data.shifts} days={data.picker?.days ?? null} editable={canEdit} />}
          {!exempt && admin.data && <PenaltiesCard events={admin.data.events} />}

          {data.probation.length > 0 && (
            <div className="card" data-card="probation">
              <div className="card__head">
                <Icon name="hand" />
                <h3>{t("فترة الاختبار", "Probation")}</h3>
              </div>
              {data.probation.map((row) => (
                <div className="kv" key={row.stage.value}>
                  <span>
                    {words(row.stage)} <span className="muted mono">{row.due_date}</span>
                  </span>
                  <LeaveStatusBadge status={row.outcome} />
                </div>
              ))}
              <Link className="btn btn--sm btn--block mt" to="/hr/probation">
                <Icon name="arrow-right" size="sm" />
                <span>{t("لوحة فترة الاختبار", "Probation board")}</span>
              </Link>
            </div>
          )}

          {data.leave.length > 0 && (
            <div className="card card--flat" data-card="leave">
              <div className="card__head">
                <Icon name="calendar" />
                <h3>{t("آخر الإجازات", "Recent leave")}</h3>
              </div>
              {data.leave.map((row) => (
                <div className="kv" key={row.id}>
                  <span>
                    {words(row.kind)} <span className="muted mono">{row.start_date}</span>
                  </span>
                  <LeaveStatusBadge status={row.status} />
                </div>
              ))}
            </div>
          )}

          {!exempt && (
            <div className="card card--flat" data-card="plan">
              <div className="card__head">
                <Icon name="sliders" />
                <h3>{t("خطة الراتب", "Salary plan")}</h3>
              </div>
              {data.plan.current ? (
                <div className="kv">
                  <span>{data.plan.current.name}</span>
                  <span className="muted mono">{data.plan.current.overrides.join(" · ")}</span>
                </div>
              ) : (
                <div className="muted">{t("على قواعد الشركة.", "On the company rules.")}</div>
              )}
              {data.can.plan && (
                <div className="mt">
                  <select className="input" aria-label={t("خطة الراتب", "Salary plan")} value={chosenPlan} onChange={(event) => setPlan(event.target.value)}>
                    <option value="">{t("قواعد الشركة", "Company rules")}</option>
                    {data.plan.options.map((one) => (
                      <option key={one.id} value={one.id}>
                        {one.name}
                      </option>
                    ))}
                  </select>
                  <button className="btn btn--sm btn--block mt" type="button" disabled={assign.isPending} onClick={savePlan}>
                    <Icon name="check" size="sm" />
                    <span>{t("اربطه", "Assign")}</span>
                  </button>
                </div>
              )}
            </div>
          )}

          {data.application && (
            <div className="card card--flat" data-card="application">
              <div className="card__head">
                <Icon name="archive" />
                <h3>{t("طلب التوظيف", "The application")}</h3>
              </div>
              <div className="kv">
                <Link to={`/hr/candidates/${data.application.code}`}>{data.application.code}</Link>
                <span className="muted">{data.application.applied_on}</span>
              </div>
              <small className="muted">{t("الطلب اللي الموظف ده اتعيّن منه — محفوظ كامل بإجاباته.", "The application this employee came from, kept whole.")}</small>
            </div>
          )}

          {data.salary.length > 0 && (
            <div className="card card--flat" data-card="salary">
              <div className="card__head">
                <Icon name="archive" />
                <h3>{t("سجل الراتب", "Salary history")}</h3>
              </div>
              {data.salary.map((row) => (
                <div className="kv" key={row.effective_from}>
                  <span className="mono muted">{row.effective_from}</span>
                  <b className="mono">{row.amount}</b>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
