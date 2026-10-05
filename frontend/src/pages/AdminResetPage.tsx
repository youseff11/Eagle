import { useState, type FormEvent, type ReactNode } from "react";
import { Navigate, useNavigate } from "react-router";
import { useRunReset } from "../api/adminActions";
import { ApiError } from "../api/client";
import { useMe, useResetCounts } from "../api/queries";
import type { MailResetCounts, StaffResetCounts, TaskResetCounts } from "../api/types";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

type Kind = "tasks" | "mail" | "staff";

function Count({ n, children, extra }: { n: number; children: ReactNode; extra?: ReactNode }) {
  return (
    <div>
      <b className="mono">{n}</b>
      <span>{children}</span>
      {extra}
    </div>
  );
}

/**
 * One of the three clear-outs, which delete real data for good: every task (and the numbering starts again), the mail no task
 * stands on, or every employee who is not an admin (to start again with real people). All ask for the admin's own password
 * and an explicit tick, count what would go before anything is asked, and hand back a backup file that is saved before the
 * page moves on. Nothing here is quicker than the classic page was.
 */
export function AdminResetPage({ kind }: { kind: Kind }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const navigate = useNavigate();
  const me = useMe();
  const allowed = me.data !== undefined && me.data.user.is_admin;
  const counts = useResetCounts<TaskResetCounts & MailResetCounts & StaffResetCounts>(kind, allowed);
  const run = useRunReset(kind);
  const [password, setPassword] = useState("");
  const [understood, setUnderstood] = useState(false);
  const [problem, setProblem] = useState("");

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = counts.data?.counts;
  const tasks = kind === "tasks";
  const mail = kind === "mail";
  const staff = kind === "staff";
  // People with a task standing on their private line or on a file they shared cannot be cleared until the tasks are: the server
  // refuses, and the page says so first.
  const blocked = staff && data !== undefined && data.line_blocked + data.task_files_blocked > 0;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setProblem("");
    run.mutate(password, {
      onSuccess: (done) => {
        setPassword("");
        // The password the request carried is not kept in its state once it is over.
        run.reset();
        push({
          level: "success",
          sticky: true,
          title: tasks
            ? t(`اتمسح ${done.deleted} تاسك. الترقيم هيبدأ من TSK-00001.`, `Deleted ${done.deleted} task(s). Numbering restarts at TSK-00001.`)
            : staff
              ? t(`اتمسح ${done.deleted} موظف و${done.files} ملف متخزّن.`, `Deleted ${done.deleted} staff member(s) and ${done.files} stored file(s).`)
              : t(`اتمسح ${done.deleted} ميل و${done.files} ملف متخزّن.`, `Deleted ${done.deleted} mail(s) and ${done.files} stored file(s).`),
        });
        navigate(tasks ? "/tasks" : staff ? "/hr/employees" : "/inbox");
      },
      onError: (error) => {
        setPassword("");
        const detail = error instanceof ApiError ? error.detail : "";
        // A "no" from the server (4xx) came before it did anything. Anything else - a server error, a dropped connection - may
        // have come after: the data can be gone with the backup lost on the way, so the page says it does not know.
        const refused = error instanceof ApiError && error.status >= 400 && error.status < 500;
        setProblem(
          detail ||
            (refused
              ? t("حصلت مشكلة. محدش اتمسح.", "Something went wrong. Nothing was deleted.")
              : t(
                  "حصلت مشكلة وماعرفناش النتيجة. ممكن يكون اتمسح: حدّث الصفحة وراجع الأرقام قبل ما تحاول تاني.",
                  "Something went wrong and the result is not known. It may have been deleted: reload the page and check the numbers before trying again.",
                )),
        );
        run.reset();
      },
    });
  };

  return (
    <>
      <div className="page-head">
        <h1>
          {tasks ? t("ريستارت التاسكات", "Reset all tasks") : staff ? t("ريستارت الموظفين", "Reset all staff") : t("مسح الميلات", "Delete all mail")}
        </h1>
        <span className="page-head__sub">
          {tasks
            ? t("بيمسح كل التاسكات والترقيم بيرجع يبدأ من TSK-00001. مفيش رجوع.", "Deletes every task and numbering starts again at TSK-00001. There is no undo.")
            : staff
              ? t(
                  "بيمسح كل الموظفين ما عدا الأدمن، مع بياناتهم، عشان تبدأ بموظفينك الحقيقيين. مفيش رجوع.",
                  "Deletes every employee except the admins, with their data, so you can start with your real people. There is no undo.",
                )
              : t("بيمسح كل الميلات الواردة والصادرة وملفاتها. مفيش رجوع.", "Deletes every received and sent e-mail and its files. There is no undo.")}
        </span>
      </div>

      <div className="card reset-card" style={{ maxWidth: 720 }}>
        <div className="card__head">
          <Icon name="alert" />
          <h3>{t("اللي هيتمسح", "What goes")}</h3>
        </div>
        {data ? (
          <div className="reset-counts" data-counts={kind}>
            {tasks ? (
              <>
                <Count
                  n={data.tasks}
                  extra={data.open > 0 && <span className="chip chip--sm">{data.open} {t("شغالة دلوقتي", "still running")}</span>}
                >
                  {t("تاسك", "tasks")}
                </Count>
                <Count n={data.assignments}>{t("تسليم لتيم ليدر/مترجم", "hand-offs")}</Count>
                <Count n={data.deliveries}>{t("تسليم للعميل", "client deliveries")}</Count>
                <Count n={data.ai_checks}>{t("مراجعة AI", "AI checks")}</Count>
                <Count n={data.rooms}>{t("غرفة تاسك قديمة برسايلها", "old task rooms, with their messages")}</Count>
              </>
            ) : staff ? (
              <>
                <Count
                  n={data.people}
                  extra={data.kept > 0 && <span className="chip chip--sm">{data.kept} {t("أدمن هيفضلوا", "admin(s) stay")}</span>}
                >
                  {t("موظف", "employees")}
                </Count>
                <Count n={data.shifts}>{t("شيفت في الجداول", "roster rows")}</Count>
                <Count n={data.work_days}>{t("يوم حضور", "attendance days")}</Count>
                <Count n={data.leave}>{t("طلب إجازة", "leave requests")}</Count>
                <Count n={data.salary_records}>{t("سجل راتب", "salary records")}</Count>
                <Count n={data.payroll_lines}>{t("سطر في كشوف المرتبات", "payroll lines")}</Count>
                <Count n={data.violations}>{t("مخالفة", "violations")}</Count>
                <Count n={data.rooms}>{t("شات داخلي أو جروب شغل ليهم", "internal chats and work groups")}</Count>
                <Count n={data.line_letters + data.line_sent}>{t("رسالة على خط Sales خاص", "messages on a private Sales line")}</Count>
              </>
            ) : (
              <>
                <Count n={data.letters}>{t("ميل وارد", "received letters")}</Count>
                <Count n={data.sent}>{t("ميل صادر (ردود)", "sent replies")}</Count>
                <Count n={data.files}>{t("ملف مرفق", "attached files")}</Count>
              </>
            )}
          </div>
        ) : counts.isError ? (
          <div className="empty" role="alert">
            <Icon name="alert" size="xl" />
            <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
          </div>
        ) : (
          <div className="empty">
            <Icon name="refresh" size="xl" />
            <span>{t("بيحمّل...", "Loading...")}</span>
          </div>
        )}

        {mail && (
          <p className="muted mt" style={{ fontSize: ".85rem" }}>
            {t("ده كل البريد: بريد الشركة وبريد كل Sales على عنوانه. الواتساب مابيتلمسش.", "Every mailbox: the company's and each Sales person's own address. WhatsApp is not touched.")}
          </p>
        )}
        {mail && data && (data.kept_letters > 0 || data.kept_sent > 0) && (
          <div className="note note--warn mt" data-kept>
            <Icon name="shield" />
            <div>
              <strong>{t("اللي هيفضل لأن فيه تاسكات مبنية عليه", "What stays, because tasks stand on it")}</strong>
              <div>
                <b className="mono">{data.kept_letters}</b> {t("ميل وارد", "received")} · <b className="mono">{data.kept_sent}</b> {t("ميل صادر", "sent")}
              </div>
              <div className="muted">
                {t(
                  "ملفات التاسك الأصلية بتتقرا من الميلات دي، فمسحها هيشيل الملفات من تاسكات شغالة. بتتمسح مع التاسكات لما تعمل «ريستارت التاسكات».",
                  "A task reads its original files off these letters, so deleting them would take the files out from under live work. They go with the tasks, through Reset all tasks.",
                )}
              </div>
            </div>
          </div>
        )}
        {mail && (
          <div className="note note--warn mt">
            <Icon name="alert" />
            <div>
              {t(
                "المسح من الداشبورد بس، مش من صندوق البريد الحقيقي. أي ميل لسه «غير مقروء» هناك هيترجع في الجلب الجاي.",
                "This clears the dashboard only, not the real mailbox. Any letter still unread there comes back on the next fetch.",
              )}
            </div>
          </div>
        )}
        <div className="note note--warn mt">
          <Icon name="shield" />
          <div>
            <strong>{t("اللي بيفضل", "What stays")}</strong>
            <div>
              {tasks
                ? t(
                    "رسايل العملاء وميلاتهم (وتقدر تحوّلها لتاسك تاني) · شاتات الموظفين وجروبات الشغل · التقييمات والمخالفات · العملاء والموظفين.",
                    "Client messages and mail (they can be turned into tasks again) · staff chats and work groups · ratings and violations · clients and staff.",
                  )
                : staff
                  ? t(
                      "كل حسابات الأدمن · العملاء وغرفهم ورسايلهم · التاسكات (من غير أسماء الموظفين) · المرشحين والوظايف · الأقسام وخطط الرواتب والشيفتات والإعدادات.",
                      "Every admin account · clients, their rooms and messages · tasks (without the staff named on them) · candidates and vacancies · departments, pay plans, shifts and settings.",
                    )
                  : t(
                    "رسايل الواتساب · التاسكات وملفاتها · شاتات الموظفين · العملاء اللي اتعملوا من الميلات دي (بيفضلوا كعملاء).",
                    "WhatsApp messages · tasks and their files · staff chats · clients created from these letters (they stay as clients).",
                  )}
            </div>
          </div>
        </div>
        {tasks && (
          <div className="note note--warn mt">
            <Icon name="alert" />
            <div>{t("الحسابات بتحسب إنتاج المترجمين من التاسكات — إنتاج الشهر ده هيتمسح معاها.", "Payroll reads translator production from tasks - this month's production goes with them.")}</div>
          </div>
        )}
        {staff && (
          <div className="note note--warn mt">
            <Icon name="alert" />
            <div>
              {t(
                "حضورهم ورواتبهم وكشوف المرتبات والإجازات والمخالفات وصورهم الشخصية بتتمسح معاهم. الرسايل اللي موظفين Sales بعتوها على خطهم الخاص بتتمسح كمان، عشان ماتبقاش على خط الشركة.",
                "Their attendance, pay, payroll lines, leave, violations and pictures go with them. What Sales people wrote on their private lines goes too, so it does not turn into the company's line.",
              )}
            </div>
          </div>
        )}
        {staff && data && data.lines_released > 0 && (
          <div className="note note--warn mt" data-note="lines-released">
            <Icon name="alert" />
            <div>
              <b className="mono">{data.lines_released}</b>{" "}
              {t(
                "منهم عنده رقم واتساب أو عنوان ميل خاص. افصله من Meta ومن Google قبل المسح، وإلا أي رسالة جديدة عليه هتنزل على خط الشركة ويشوفها الأوبريشن.",
                "of them have their own WhatsApp number or mail address. Detach it at Meta and Google first, or any new message to it lands on the company line, where Operation reads it.",
              )}
            </div>
          </div>
        )}
        {staff && data && data.tasks_touched > 0 && (
          <div className="note note--warn mt" data-note="tasks-touched">
            <Icon name="alert" />
            <div>
              <b className="mono">{data.tasks_touched}</b>{" "}
              {t("تاسك هتفضل بس هتفقد أسماء الموظفين اللي عليها.", "task(s) stay but lose the names of the staff on them.")}
            </div>
          </div>
        )}
        {blocked && (
          <div className="reset-error mt" role="alert" data-note="blocked">
            {t(
              "فيه تاسكات مبنية على رسايل أو ملفات تخص موظف هيتمسح (خط خاص أو ملف ترجمة). اعمل «ريستارت التاسكات» الأول وبعدين ارجع.",
              "Tasks stand on messages or files of somebody who would be deleted (a private line or a translation file). Reset all tasks first, then come back.",
            )}
          </div>
        )}

        <form className="mt" autoComplete="off" onSubmit={submit}>
          <div className="field">
            <label htmlFor="reset-password">{t("باسورد الأدمن بتاعك", "Your admin password")}</label>
            <input
              id="reset-password"
              className="input"
              type="password"
              autoComplete="current-password"
              style={{ maxWidth: 320 }}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
          <label className="switch">
            <input type="checkbox" checked={understood} onChange={(event) => setUnderstood(event.target.checked)} />
            <span>
              {tasks
                ? t("فاهم إن ده مسح نهائي لكل التاسكات، وهاخد نسخة احتياطية.", "I understand every task is deleted for good, and I will keep the backup.")
                : staff
                  ? t(
                      "فاهم إن ده مسح نهائي لكل الموظفين (ما عدا الأدمن) وبياناتهم، وهاخد نسخة احتياطية.",
                      "I understand every employee except the admins is deleted for good with their data, and I will keep the backup.",
                    )
                  : t("فاهم إن ده مسح نهائي لكل الميلات، وهاخد نسخة احتياطية.", "I understand all mail is deleted for good, and I will keep the backup.")}
            </span>
          </label>
          {problem && (
            <div className="reset-error" role="alert">
              {problem}
            </div>
          )}
          <div className="row mt">
            <button className="btn btn--danger" type="submit" disabled={!understood || password === "" || run.isPending || blocked}>
              <Icon name={tasks ? "refresh" : "trash"} size="sm" />
              <span>
                {tasks
                  ? t("امسح كل التاسكات وابدأ من الأول", "Delete every task and start over")
                  : staff
                    ? t("امسح كل الموظفين", "Delete all staff")
                    : t("امسح كل الميلات", "Delete all mail")}
              </span>
            </button>
          </div>
          <p className="muted" style={{ fontSize: ".8rem" }}>
            {tasks
              ? t("مع المسح بينزل لك ملف JSON فيه كل اللي اتمسح. مابيتحفظش على السيرفر.", "A JSON file of everything deleted downloads to you as it goes. It is not kept on the server.")
              : staff
                ? t(
                    "مع المسح بينزل لك ملف JSON فيه الموظفين وبياناتهم (من غير الباسوردات ومن غير كلام الشاتات الخاصة بين اتنين موظفين، ومن غير مواقع الحضور). مابيتحفظش على السيرفر.",
                    "A JSON file of the staff and their data downloads to you as it goes: without the passwords, the words of one-to-one staff chats, or where people clocked in from. It is not kept on the server.",
                  )
                : t(
                  "مع المسح بينزل لك ملف JSON فيه نص كل ميل اتمسح وبيانات مرفقاته (من غير الملفات نفسها). مابيتحفظش على السيرفر.",
                  "A JSON file of every letter deleted and its attachment details (not the files themselves) downloads to you as it goes. It is not kept on the server.",
                )}
          </p>
        </form>
      </div>
    </>
  );
}
