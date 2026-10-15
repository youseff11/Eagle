import { useDeferredValue, useState, type FormEvent } from "react";
import { Navigate } from "react-router";
import { refusalText } from "../api/b2b";
import {
  useCancelVisit,
  useCheckIn,
  useCheckOut,
  useDecideVisit,
  useEscalateVisit,
  usePlanVisit,
  useVerifyClean,
  useVisitLeads,
  useVisits,
  type Press,
  type Visit,
  type VisitReport,
  type VisitsResponse,
} from "../api/b2c";
import { useMe } from "../api/queries";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { Modal } from "../components/Modal";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { position } from "../lib/attendance";

/**
 * The B2C field visits (15/10/2026). A field Sales person plans a visit to a company on their sheet, presses «وصلت» at the
 * company and «خلصت» on leaving. Each press reads the phone's place ONCE, at the press (`lib/attendance.position`): nothing
 * follows the person in between, and nothing is read on any other page. The Sales manager verifies or turns down what was
 * sent, and hands a doubtful one to the owner. Every rule is the server's (`b2c.py`); each visit says what may be done.
 */

const STATUS_WORDS: Record<string, [string, string]> = {
  planned: ["متخطط لها", "Planned"],
  checked_in: ["وصل ولسه ماخلصش", "Arrived, not done yet"],
  pending: ["مستنية الاعتماد", "Waiting for approval"],
  verified: ["اتعتمدت", "Verified"],
  rejected: ["اترفضت", "Turned down"],
};
const OUTCOME_AR: Record<string, string> = {
  interested: "مهتم",
  follow_up: "نتابع معاه",
  quotation: "طلب عرض سعر",
  not_interested: "مش مهتم",
  nobody: "مالقيتش حد أقابله",
};
const INTEREST_AR: Record<string, string> = { high: "عالي", medium: "متوسط", low: "قليل" };

function Problem({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="note note--danger" role="alert" style={{ margin: "10px 0" }}>
      <Icon name="alert" />
      <div>{text}</div>
    </div>
  );
}

function StatusChip({ status }: { status: string }) {
  const { t } = usePreferences();
  const tone = status === "verified" ? " chip--replied" : status === "pending" || status === "checked_in" ? " chip--open" : status === "rejected" ? " deadline--late" : "";
  const [ar, en] = STATUS_WORDS[status] ?? [status, status];
  return (
    <span className={`chip chip--sm${tone}`} data-visit-status={status}>
      {t(ar, en)}
    </span>
  );
}

/** A rate with what it is made of beside it (the requirements' section 9), or «مش متقاس» when there is nothing to divide. */
function Rate({ value, part, whole }: { value: number | null; part: number; whole: number }) {
  const { t } = usePreferences();
  if (value === null) return <span className="muted">{t("مش متقاس", "Not measured")}</span>;
  return (
    <span className="mono">
      {value}% <span className="muted">({part}/{whole})</span>
    </span>
  );
}

/**
 * Read the phone's place at a press, or ask the person why there is none (the server refuses a press with neither). `null`
 * when the person closed the question: nothing is sent.
 */
function usePress() {
  const [asking, setAsking] = useState<((reason: string | null) => void) | null>(null);
  const read = async (): Promise<Press | null> => {
    const place = await position();
    if (place) return place;
    const reason = await new Promise<string | null>((resolve) => setAsking(() => resolve));
    setAsking(null);
    return reason ? { reason } : null;
  };
  return { read, asking, answer: (reason: string | null) => asking?.(reason) };
}

function NoPlace({ onAnswer }: { onAnswer: (reason: string | null) => void }) {
  const { t } = usePreferences();
  const [reason, setReason] = useState("");
  return (
    <Modal title={t("الموبايل ماادّاش لوكيشن", "The phone gave no location")} icon="map-pin" onClose={() => onAnswer(null)}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (reason.trim()) onAnswer(reason.trim());
        }}
      >
        <p className="muted">
          {t(
            "اتأكد إن اللوكيشن مفتوح وإنك سامح للموقع ياخده، وجرّب تاني. لو مش نافع اكتب السبب: الزيارة هتروح للمانجر يراجعها.",
            "Check that location is on and allowed for this site, and try again. If it still fails, write why: the visit goes to the manager to review.",
          )}
        </p>
        <div className="field">
          <label htmlFor="noPlaceReason">{t("السبب", "The reason")}</label>
          <input className="input" id="noPlaceReason" maxLength={250} value={reason} onChange={(event) => setReason(event.target.value)} />
        </div>
        <button className="btn btn--primary" type="submit" disabled={!reason.trim()}>
          <Icon name="send" />
          {t("ابعت من غير لوكيشن", "Send without a location")}
        </button>
      </form>
    </Modal>
  );
}

/** «خلصت»: the report, then the second reading of the place. */
function CheckOut({ visit, data, onClose }: { visit: Visit; data: VisitsResponse; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const toasts = useToasts();
  const out = useCheckOut();
  const press = usePress();
  const [report, setReport] = useState<VisitReport>({ outcome: "", met: "", interest: "", summary: "", next_step: "", next_step_on: "" });
  const [reading, setReading] = useState(false);
  const [problem, setProblem] = useState("");
  const set = (name: keyof VisitReport, value: string) => setReport((before) => ({ ...before, [name]: value }));
  const busy = out.isPending || reading;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    if (!report.outcome || !report.summary.trim()) {
      setProblem(t("اختار النتيجة واكتب ملخص المقابلة.", "Choose the outcome and write what was said."));
      return;
    }
    setProblem("");
    setReading(true);
    const place = await press.read();
    setReading(false);
    if (!place) return;
    out.mutate(
      { id: visit.id, press: place, report },
      {
        onSuccess: () => {
          toasts.push({ level: "success", title: t("الزيارة اتبعتت للمانجر", "The visit went to the manager") });
          onClose();
        },
        onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أقفل الزيارة. جرّب تاني.", "Could not close the visit. Try again."))),
      },
    );
  };

  return (
    <Modal title={`${t("خلصت", "I am done")} · ${visit.lead.company_name}`} icon="check" busy={busy} onClose={onClose}>
      <form onSubmit={(event) => void submit(event)}>
        <div className="field">
          <label htmlFor="outOutcome">{t("نتيجة الزيارة", "How it went")}</label>
          <select className="input" id="outOutcome" value={report.outcome} onChange={(event) => set("outcome", event.target.value)}>
            <option value="">{t("— اختار —", "— choose —")}</option>
            {data.outcomes.map((choice) => (
              <option key={choice.value} value={choice.value}>
                {lang === "ar" ? (OUTCOME_AR[choice.value] ?? choice.label) : choice.label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="outMet">{t("قابلت مين (الاسم والوظيفة)", "Who you met (name and position)")}</label>
          <input className="input" id="outMet" maxLength={160} value={report.met} onChange={(event) => set("met", event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="outInterest">{t("مستوى الاهتمام", "Interest")}</label>
          <select className="input" id="outInterest" value={report.interest} onChange={(event) => set("interest", event.target.value)}>
            <option value="">—</option>
            {data.interests.map((choice) => (
              <option key={choice.value} value={choice.value}>
                {lang === "ar" ? (INTEREST_AR[choice.value] ?? choice.label) : choice.label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="outSummary">{t("ملخص المقابلة", "What was said")}</label>
          <textarea className="input" id="outSummary" rows={3} maxLength={4000} value={report.summary} onChange={(event) => set("summary", event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="outNext">{t("الخطوة الجاية", "Next step")}</label>
          <input className="input" id="outNext" maxLength={250} value={report.next_step} onChange={(event) => set("next_step", event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="outNextOn">{t("ميعادها", "When")}</label>
          <input className="input" id="outNextOn" type="date" value={report.next_step_on} onChange={(event) => set("next_step_on", event.target.value)} />
        </div>
        <Problem text={problem} />
        <button className="btn btn--primary" type="submit" disabled={busy}>
          <Icon name="map-pin" />
          {reading ? t("باخد مكانك…", "Reading your place…") : t("خلصت، ابعتها", "Done, send it")}
        </button>
      </form>
      {press.asking && <NoPlace onAnswer={press.answer} />}
    </Modal>
  );
}

type DecideMode = "verify" | "reject" | "escalate";

/** The manager's decision: verify (with why, when the visit is flagged) or turn down (always with why), or hand to the owner. */
function Decide({ visit, mode, onClose }: { visit: Visit; mode: DecideMode; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const decide = useDecideVisit();
  const escalate = useEscalateVisit();
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");
  const busy = decide.isPending || escalate.isPending;
  const needed = mode !== "verify" || visit.flags.length > 0;
  const titles: Record<DecideMode, string> = {
    verify: t("اعتمد الزيارة", "Verify the visit"),
    reject: t("ارفض الزيارة", "Turn the visit down"),
    escalate: t("حوّلها للمالك", "Hand it to the owner"),
  };
  const icon = mode === "reject" ? "x" : mode === "escalate" ? "forward" : "check";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    if (needed && !note.trim()) {
      setProblem(t("اكتب السبب.", "Write the reason."));
      return;
    }
    const failed = (failure: unknown) => setProblem(refusalText(failure, lang, t("مقدرتش أحفظ. جرّب تاني.", "Could not save. Try again.")));
    if (mode === "escalate") escalate.mutate({ id: visit.id, note: note.trim() }, { onSuccess: onClose, onError: failed });
    else decide.mutate({ id: visit.id, verified: mode === "verify", note: note.trim() }, { onSuccess: onClose, onError: failed });
  };

  return (
    <Modal title={`${titles[mode]} · ${visit.code}`} icon={icon} busy={busy} onClose={onClose}>
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="decideNote">
            {mode === "verify"
              ? t("ليه هتعتمدها رغم الملاحظات", "Why it is fine despite the flags")
              : mode === "reject"
                ? t("سبب الرفض", "Why it is turned down")
                : t("ليه محتاجة المالك", "Why the owner should decide")}
            {!needed && ` ${t("(اختياري)", "(optional)")}`}
          </label>
          <textarea className="input" id="decideNote" rows={2} maxLength={500} value={note} onChange={(event) => setNote(event.target.value)} />
        </div>
        <Problem text={problem} />
        <button className={`btn ${mode === "reject" ? "btn--danger" : "btn--primary"}`} type="submit" disabled={busy}>
          <Icon name={icon} />
          {titles[mode]}
        </button>
      </form>
    </Modal>
  );
}

/** A new visit from the visits page: the company is picked from the person's own (the manager's: any field person's). */
function NewVisit({ onClose }: { onClose: () => void }) {
  const { t, lang } = usePreferences();
  const toasts = useToasts();
  const plan = usePlanVisit();
  const [words, setWords] = useState("");
  const typed = useDeferredValue(words.trim());
  const found = useVisitLeads(typed, true);
  const [lead, setLead] = useState(0);
  const [purpose, setPurpose] = useState("");
  const [when, setWhen] = useState("");
  const [problem, setProblem] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (plan.isPending) return;
    if (!lead) {
      setProblem(t("اختار الشركة.", "Choose the company."));
      return;
    }
    plan.mutate(
      { lead, purpose: purpose.trim(), planned_at: when },
      {
        onSuccess: (answer) => {
          toasts.push({ level: "success", title: t(`الزيارة ${answer.visit.code} اتعملت`, `Visit ${answer.visit.code} planned`) });
          onClose();
        },
        onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أعمل الزيارة. جرّب تاني.", "Could not plan the visit. Try again."))),
      },
    );
  };

  return (
    <Modal title={t("زيارة جديدة", "New visit")} icon="map-pin" busy={plan.isPending} onClose={onClose}>
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="visitSearch">{t("الشركة", "Company")}</label>
          <input
            className="input"
            id="visitSearch"
            maxLength={100}
            value={words}
            placeholder={t("ابحث بالاسم أو المنطقة…", "Search by name or area…")}
            onChange={(event) => setWords(event.target.value)}
          />
        </div>
        <div className="stack" style={{ maxHeight: 220, overflowY: "auto", marginBottom: 10 }} aria-label={t("الشركات", "Companies")}>
          {(found.data?.items ?? []).map((item) => (
            <label key={item.id} className="row row--tight" data-pick={item.id}>
              <input type="radio" name="visitLead" checked={lead === item.id} onChange={() => setLead(item.id)} />
              <strong>{item.company_name}</strong>
              <span className="muted">{[item.governorate, item.address].filter(Boolean).join(" · ")}</span>
              {!item.has_place && <span className="chip chip--sm chip--open">{t("مالهاش لوكيشن", "No location")}</span>}
            </label>
          ))}
          {found.data && found.data.items.length === 0 && <span className="muted">{t("مفيش شركات بالبحث ده في شيتاتك.", "No company on your sheets matches.")}</span>}
        </div>
        <div className="field">
          <label htmlFor="newPurpose">{t("الغرض من الزيارة", "Purpose of the visit")}</label>
          <input className="input" id="newPurpose" maxLength={250} value={purpose} onChange={(event) => setPurpose(event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="newWhen">{t("الميعاد (اختياري)", "When (optional)")}</label>
          <input className="input" id="newWhen" type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} />
        </div>
        <Problem text={problem} />
        <button className="btn btn--primary" type="submit" disabled={plan.isPending}>
          <Icon name="map-pin" />
          {t("اعمل الزيارة", "Plan the visit")}
        </button>
      </form>
    </Modal>
  );
}

function Flags({ visit, data }: { visit: Visit; data: VisitsResponse }) {
  const { lang } = usePreferences();
  if (!visit.flags.length) return null;
  return (
    <>
      {visit.flags.map((flag) => {
        const word = data.flags.find((one) => one.value === flag);
        return (
          <span key={flag} className="chip chip--sm chip--open" data-flag={flag}>
            <Icon name="alert" size="sm" />
            {word ? (lang === "ar" ? word.ar : word.en) : flag}
          </span>
        );
      })}
    </>
  );
}

/** One press, said plainly: when, how far from the company, how sure the phone was, and the place on the map. */
function PressLine({ label, at, distance, accuracy, map }: { label: string; at: string; distance: number | null; accuracy: number | null; map: string }) {
  const { t } = usePreferences();
  if (!at) return null;
  return (
    <div className="row row--tight muted">
      <span>{label}</span>
      <span className="mono">{at}</span>
      {distance !== null && <span>{t(`على بُعد ${distance} متر`, `${distance} m away`)}</span>}
      {accuracy !== null && <span>{t(`دقة ${accuracy} متر`, `±${accuracy} m`)}</span>}
      {map && (
        <a href={map} target="_blank" rel="noreferrer noopener">
          {t("على الخريطة", "On the map")}
        </a>
      )}
    </div>
  );
}

type Open = { kind: "out"; visit: Visit } | { kind: "decide"; visit: Visit; mode: DecideMode } | { kind: "new" };
type Show = "all" | "open" | "pending" | "decided";

const SHOWS: Record<Show, (visit: Visit) => boolean> = {
  all: () => true,
  open: (visit) => visit.status === "planned" || visit.status === "checked_in",
  pending: (visit) => visit.status === "pending",
  decided: (visit) => visit.status === "verified" || visit.status === "rejected",
};

export function VisitsPage() {
  const { t, lang } = usePreferences();
  const me = useMe();
  const toasts = useToasts();
  const user = me.data?.user;
  // The field Sales people, the B2C manager and the owner (the server holds the same rule, `b2c.has_visit_door`).
  const allowed = Boolean(
    user && (user.is_admin || (user.role === "sales" && (user.sales_track === "b2c_field" || (user.sales_manager && user.sales_track !== "b2b")))),
  );
  const [month, setMonth] = useState("");
  const visits = useVisits(month, allowed);
  const checkIn = useCheckIn();
  const cancel = useCancelVisit();
  const verifyClean = useVerifyClean();
  const press = usePress();
  const [open, setOpen] = useState<Open | null>(null);
  const [show, setShow] = useState<Show>("all");
  const [arriving, setArriving] = useState(0);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = visits.data;
  if (visits.isError) {
    return (
      <div className="card empty" role="alert">
        <Icon name="alert" size="xl" />
        <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
      </div>
    );
  }
  if (!data) return <Loading />;

  const failed = (failure: unknown) => toasts.push({ level: "danger", title: refusalText(failure, lang, t("مقدرتش. جرّب تاني.", "Could not do it. Try again.")) });
  const arrive = async (visit: Visit) => {
    if (arriving) return;
    setArriving(visit.id);
    const place = await press.read();
    if (!place) {
      setArriving(0);
      return;
    }
    checkIn.mutate(
      { id: visit.id, press: place },
      {
        onSuccess: (answer) => {
          const far = answer.visit.check_in_distance;
          toasts.push({
            level: answer.visit.flags.length ? "warning" : "success",
            title: far !== null ? t(`اتسجّل وصولك: على بُعد ${far} متر من الشركة`, `Arrival recorded: ${far} m from the company`) : t("اتسجّل وصولك", "Arrival recorded"),
          });
        },
        onError: failed,
        onSettled: () => setArriving(0),
      },
    );
  };
  const clean = data.visits.filter((visit) => visit.can_decide && visit.flags.length === 0 && !visit.escalated);
  const shown = data.visits.filter(SHOWS[show]);
  const current = data.visits.find((visit) => visit.mine && visit.status === "checked_in");

  return (
    <>
      <div className="page-head">
        <h1>{t("الزيارات", "Visits")}</h1>
        <span className="page-head__sub">
          {t(
            `اضغط «وصلت» وانت عند الشركة و«خلصت» وانت ماشي: الموبايل بيدّي مكانك مرة واحدة مع كل ضغطة بس. لازم تبقى في حدود ${data.rules.radius_m} متر من الشركة، والمانجر هو اللي بيعتمد.`,
            `Press «I arrived» at the company and «I am done» on leaving: the phone gives your place once at each press, and only then. You must be within ${data.rules.radius_m} m of the company; the manager verifies.`,
          )}
        </span>
      </div>

      {current && (
        <div className="note note--warn" style={{ marginBottom: 14 }} data-current={current.id}>
          <Icon name="map-pin" />
          <div className="grow">
            {t(`انت دلوقتي في زيارة ${current.lead.company_name}. اضغط «خلصت» وانت ماشي.`, `You are on a visit to ${current.lead.company_name}. Press «I am done» on leaving.`)}
          </div>
          <button className="btn btn--primary" type="button" onClick={() => setOpen({ kind: "out", visit: current })}>
            <Icon name="check" />
            {t("خلصت", "I am done")}
          </button>
        </div>
      )}

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="card__head">
          <Icon name="target" />
          <h3>{t("التارجت", "The target")}</h3>
          <span className="muted">
            {t(
              `${data.rules.target} زيارة معتمدة في الشهر على ${data.rules.work_days} يوم شغل، وبيقل بالإجازات المعتمدة.`,
              `${data.rules.target} verified visits a month over ${data.rules.work_days} working days, less approved leave.`,
            )}
          </span>
          <div className="grow" />
          <input className="input" type="month" style={{ width: "auto" }} value={month || data.month} aria-label={t("الشهر", "Month")} onChange={(event) => setMonth(event.target.value)} />
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t("الـSales", "Sales person")}</th>
                <th>{t("التارجت", "Target")}</th>
                <th>{t("اتعتمدت", "Verified")}</th>
                <th>{t("مستنية", "Waiting")}</th>
                <th>{t("اترفضت", "Turned down")}</th>
                <th>{t("فاضل", "Left")}</th>
                <th>{t("تحقيق التارجت", "Achievement")}</th>
                <th>{t("نسبة الاعتماد", "Verification rate")}</th>
              </tr>
            </thead>
            <tbody>
              {data.board.map((row) => (
                <tr key={row.person.id} data-board={row.person.id}>
                  <td>{row.person.name}</td>
                  <td className="mono">
                    {row.target}
                    {row.leave_days > 0 && <span className="muted"> {t(`(${row.leave_days} يوم إجازة)`, `(${row.leave_days} days off)`)}</span>}
                  </td>
                  <td className="mono">{row.verified}</td>
                  <td className="mono">{row.pending}</td>
                  <td className="mono">{row.rejected}</td>
                  <td className="mono">{row.remaining}</td>
                  <td>
                    <Rate value={row.achievement} part={row.verified} whole={row.target} />
                  </td>
                  <td>
                    <Rate value={row.verification_rate} part={row.verified} whole={row.submitted} />
                  </td>
                </tr>
              ))}
              {data.board.length === 0 && (
                <tr>
                  <td colSpan={8} className="empty">
                    {t("مفيش Sales ميداني لسه. اختار «B2C ميداني» من ملف الموظف.", "No field Sales person yet. Choose «B2C field» on the employee's file.")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="row" style={{ marginBottom: 12 }}>
          {data.field && (
            <button className="btn btn--primary" type="button" onClick={() => setOpen({ kind: "new" })}>
              <Icon name="plus" />
              {t("زيارة جديدة", "New visit")}
            </button>
          )}
          {data.can_manage && clean.length > 0 && (
            <button
              className="btn"
              type="button"
              disabled={verifyClean.isPending}
              onClick={() =>
                verifyClean.mutate(
                  clean.map((visit) => visit.id),
                  { onSuccess: (answer) => toasts.push({ level: "success", title: t(`اتعتمد ${answer.verified} زيارة`, `${answer.verified} visits verified`) }), onError: failed },
                )
              }
            >
              <Icon name="check-double" />
              {t(`اعتمد السليمة (${clean.length})`, `Verify the clean ones (${clean.length})`)}
            </button>
          )}
          <div className="grow" />
          <select className="input" style={{ width: "auto" }} value={show} aria-label={t("اعرض", "Show")} onChange={(event) => setShow(event.target.value as Show)}>
            <option value="all">{t("كل الزيارات", "All visits")}</option>
            <option value="open">{t("لسه ماتعملتش", "Not done yet")}</option>
            <option value="pending">{t("مستنية الاعتماد", "Waiting for approval")}</option>
            <option value="decided">{t("اتقرر فيها", "Decided")}</option>
          </select>
        </div>

        <div className="stack">
          {shown.map((visit) => (
            <div key={visit.id} className="card" data-visit={visit.id} style={{ margin: 0 }}>
              <div className="row row--tight">
                <span className="mono">{visit.code}</span>
                <strong>{visit.lead.company_name}</strong>
                <StatusChip status={visit.status} />
                {visit.escalated && <span className="chip chip--sm chip--open">{t("عند المالك", "With the owner")}</span>}
                <Flags visit={visit} data={data} />
                <div className="grow" />
                {data.can_manage && visit.person && <span className="muted">{visit.person.name}</span>}
              </div>
              <div className="muted">
                {[visit.lead.governorate, visit.lead.address].filter(Boolean).join(" · ")}
                {visit.lead.map_link && (
                  <>
                    {" · "}
                    <a href={visit.lead.map_link} target="_blank" rel="noreferrer noopener">
                      {t("مكان الشركة", "The company's place")}
                    </a>
                  </>
                )}
              </div>
              {(visit.planned_at || visit.purpose) && (
                <div className="muted">
                  {visit.planned_at && <span className="mono">{visit.planned_at}</span>} {visit.purpose}
                </div>
              )}
              <PressLine label={t("وصل", "Arrived")} at={visit.check_in_at} distance={visit.check_in_distance} accuracy={visit.check_in_accuracy} map={visit.check_in_map} />
              <PressLine label={t("مشي", "Left")} at={visit.check_out_at} distance={visit.check_out_distance} accuracy={visit.check_out_accuracy} map={visit.check_out_map} />
              {visit.minutes !== null && <div className="muted">{t(`المدة ${visit.minutes} دقيقة`, `${visit.minutes} minutes`)}</div>}
              {visit.no_location_reason && (
                <div className="muted">
                  {t("من غير لوكيشن:", "No location:")} {visit.no_location_reason}
                </div>
              )}
              {visit.summary && (
                <div style={{ marginTop: 6 }}>
                  {visit.outcome && <span className="chip chip--sm">{lang === "ar" ? (OUTCOME_AR[visit.outcome] ?? visit.outcome) : visit.outcome}</span>}{" "}
                  {visit.met && <span className="muted">{visit.met} · </span>}
                  {visit.summary}
                  {visit.next_step && (
                    <div className="muted">
                      {t("الخطوة الجاية:", "Next step:")} {visit.next_step} {visit.next_step_on && <span className="mono">{visit.next_step_on}</span>}
                    </div>
                  )}
                </div>
              )}
              {visit.escalation_note && (
                <div className="muted">
                  {t("اتحوّلت للمالك:", "Handed to the owner:")} {visit.escalation_note}
                </div>
              )}
              {visit.decided_at && (
                <div className="muted">
                  {visit.status === "verified" ? t("اعتمدها", "Verified by") : t("رفضها", "Turned down by")} {visit.decided_by?.name} <span className="mono">{visit.decided_at}</span>
                  {visit.decision_note && ` · ${visit.decision_note}`}
                </div>
              )}
              <div className="row row--tight" style={{ marginTop: 8 }}>
                {visit.mine && visit.status === "planned" && (
                  <>
                    <button className="btn btn--primary btn--sm" type="button" disabled={arriving !== 0 || Boolean(current)} onClick={() => void arrive(visit)}>
                      <Icon name="map-pin" size="sm" />
                      {arriving === visit.id ? t("باخد مكانك…", "Reading your place…") : t("وصلت", "I arrived")}
                    </button>
                    <button className="btn btn--sm btn--ghost" type="button" disabled={cancel.isPending} onClick={() => cancel.mutate(visit.id, { onError: failed })}>
                      <Icon name="trash" size="sm" />
                      {t("الغي الزيارة", "Cancel the visit")}
                    </button>
                  </>
                )}
                {visit.mine && visit.status === "checked_in" && (
                  <button className="btn btn--primary btn--sm" type="button" onClick={() => setOpen({ kind: "out", visit })}>
                    <Icon name="check" size="sm" />
                    {t("خلصت", "I am done")}
                  </button>
                )}
                {visit.can_decide && (
                  <>
                    <button className="btn btn--sm" type="button" onClick={() => setOpen({ kind: "decide", visit, mode: "verify" })}>
                      <Icon name="check" size="sm" />
                      {t("اعتمد", "Verify")}
                    </button>
                    <button className="btn btn--sm btn--danger" type="button" onClick={() => setOpen({ kind: "decide", visit, mode: "reject" })}>
                      <Icon name="x" size="sm" />
                      {t("ارفض", "Turn down")}
                    </button>
                  </>
                )}
                {visit.can_escalate && (
                  <button className="btn btn--sm btn--ghost" type="button" onClick={() => setOpen({ kind: "decide", visit, mode: "escalate" })}>
                    <Icon name="forward" size="sm" />
                    {t("حوّلها للمالك", "Hand it to the owner")}
                  </button>
                )}
              </div>
            </div>
          ))}
          {shown.length === 0 && (
            <div className="empty">
              <Icon name="map-pin" size="xl" />
              <span>
                {data.field
                  ? t("مفيش زيارات. اعمل زيارة من «زيارة جديدة» أو من صف الشركة في الشيت.", "No visits. Plan one with «New visit» or from the company's row on the sheet.")
                  : t("مفيش زيارات هنا.", "No visits here.")}
              </span>
            </div>
          )}
        </div>
      </div>

      {open?.kind === "out" && <CheckOut visit={open.visit} data={data} onClose={() => setOpen(null)} />}
      {open?.kind === "decide" && <Decide visit={open.visit} mode={open.mode} onClose={() => setOpen(null)} />}
      {open?.kind === "new" && <NewVisit onClose={() => setOpen(null)} />}
      {press.asking && <NoPlace onAnswer={press.answer} />}
    </>
  );
}
