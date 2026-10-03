import { useEffect, useRef, useState, type FormEvent } from "react";
import { Navigate, useSearchParams } from "react-router";
import { useRefreshWords, useSaveDay } from "../api/accountsActions";
import { formErrors } from "../api/adminActions";
import { useAccountsSheet } from "../api/queries";
import type { FormErrors } from "../api/types";
import { MonthPicker } from "../components/accounts/MonthPicker";
import { Waiting, useMayRunTheMonth } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { periodText } from "../lib/payroll";

const DAY_TONES = new Set(["ok", "info", "wait", "dead"]);

/**
 * One translator's month, day by day, and the box that records a day. The words are never typed in as production: the sheet
 * re-derives them from the jobs the translator delivered each day as it opens, and the box is only for a month recorded
 * before the job log carried them.
 */
export function AccountsAttendancePage() {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const { me, allowed } = useMayRunTheMonth();
  const [params, setParams] = useSearchParams();
  const period = params.get("period") ?? "";
  const user = params.get("user") ?? "";
  const query = useAccountsSheet(period, user, allowed);
  const refresh = useRefreshWords();
  const save = useSaveDay();
  const data = query.data;
  const edits = useFormEdits(data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [failed, setFailed] = useState(false);
  const refreshed = useRef(new Set<string>());

  // The words come from the job log: re-derived once for each person and month as the sheet opens, then read again.
  const person = data?.person?.id;
  const month = data ? periodText(data.year, data.month) : "";
  const { mutate: refreshWords } = refresh;
  useEffect(() => {
    if (!person || !month) return;
    const key = `${person}:${month}`;
    if (refreshed.current.has(key)) return;
    refreshed.current.add(key);
    refreshWords({ user: person, period: month });
  }, [person, month, refreshWords]);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;
  const when = (stamp: { ar: string; en: string } | null) => (stamp ? (lang === "ar" ? stamp.ar : stamp.en) : "—");

  const go = (next: { period?: string; user?: string }) => {
    const merged = new URLSearchParams();
    const nextPeriod = next.period ?? period;
    const nextUser = next.user ?? user;
    if (nextPeriod) merged.set("period", nextPeriod);
    if (nextUser) merged.set("user", nextUser);
    setParams(merged);
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!data.person) return;
    setErrors({});
    setFailed(false);
    save.mutate(
      { user: data.person.id, values: edits.edited },
      {
        onSuccess: () => {
          edits.reset();
          push({ level: "success", title: t("اتسجل", "Recorded") });
        },
        onError: (error) => {
          const found = formErrors(error);
          if (found) setErrors(found);
          else setFailed(true);
        },
      },
    );
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("الحضور والإنتاج", "Attendance and production")}</h1>
        <div className="grow" />
        <select
          className="input"
          aria-label={t("المترجم", "Translator")}
          value={data.person?.id ?? ""}
          onChange={(event) => go({ user: event.target.value })}
        >
          {data.people.map((one) => (
            <option key={one.id} value={one.id}>
              {one.name}
            </option>
          ))}
        </select>
        <MonthPicker periods={data.periods} year={data.year} month={data.month} onChange={(next) => go({ period: next })} />
      </div>

      {data.person && (
        <div className="grid grid--4">
          <div className="kpi">
            <div className="kpi__label">{t("كلمات الشهر", "Words this month")}</div>
            <div className="kpi__value mono">{data.words}</div>
          </div>
          <div className={`kpi${data.leave_used > data.conf.monthly_leave_allowance ? " kpi--danger" : ""}`}>
            <div className="kpi__label">{t("إجازات مستخدمة", "Leave used")}</div>
            <div className="kpi__value mono">
              {data.leave_used} / {data.conf.monthly_leave_allowance}
            </div>
          </div>
          <div className="kpi">
            <div className="kpi__label">{t("التارجت الشهري", "Monthly target")}</div>
            <div className="kpi__value mono">{data.conf.monthly_target_words}</div>
          </div>
          <div className="kpi">
            <div className="kpi__label">{t("الحد اليومي", "Daily floor")}</div>
            <div className="kpi__value mono">{data.conf.daily_target_words}</div>
          </div>
        </div>
      )}

      <div className="grid grid--main">
        <div className="card">
          <div className="card__head">
            <Icon name="timer" />
            <h3>{t("أيام الشهر", "The month")}</h3>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("اليوم", "Date")}</th>
                  <th>{t("الحالة", "Status")}</th>
                  <th>{t("حضور", "In")}</th>
                  <th>{t("انصراف", "Out")}</th>
                  <th>{t("تأخير", "Late")}</th>
                  <th>{t("الكلمات", "Words")}</th>
                  <th>{t("ملاحظة", "Note")}</th>
                </tr>
              </thead>
              <tbody>
                {data.days.map((day) => (
                  <tr key={day.id} data-day={day.date}>
                    <td className="mono">{day.date}</td>
                    <td>
                      <span className={`badge${DAY_TONES.has(day.status.tone) ? ` badge--${day.status.tone}` : ""}`}>
                        {lang === "ar" ? day.status.ar : day.status.en}
                      </span>
                    </td>
                    <td className="mono">{when(day.check_in)}</td>
                    <td className="mono">{when(day.check_out)}</td>
                    <td className="mono">{day.late_minutes}</td>
                    <td className={`mono${day.under_floor ? " deadline--late" : ""}`}>{day.words}</td>
                    <td className="muted">
                      {day.absence_reason}
                      {day.note}
                    </td>
                  </tr>
                ))}
                {data.days.length === 0 && (
                  <tr>
                    <td colSpan={7} className="empty">
                      {t("مفيش أيام مسجلة في الشهر ده.", "No days recorded this month.")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="sticky-side">
          <div className="card">
            <div className="card__head">
              <Icon name="plus" />
              <h3>{t("سجل يوم", "Record a day")}</h3>
            </div>
            <form onSubmit={submit}>
              <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="day" />
              {failed && (
                <div className="note note--high" role="alert">
                  <Icon name="alert" />
                  <div>{t("حصلت مشكلة، ماتسجلش.", "Something went wrong, nothing was recorded.")}</div>
                </div>
              )}
              <button className="btn btn--primary btn--block" type="submit" disabled={!data.person || save.isPending || !edits.dirty}>
                <Icon name="check" size="sm" />
                <span>{t("احفظ", "Save")}</span>
              </button>
            </form>
          </div>
          <div className="note note--info">
            <Icon name="info" />
            <div>
              {t(
                "عدد الكلمات مش بيتكتب هنا — النظام بيجمعه من التاسكات اللي المترجم سلّمها في اليوم ده.",
                "Word counts are not typed here. The system sums them from the jobs the translator delivered that day.",
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
