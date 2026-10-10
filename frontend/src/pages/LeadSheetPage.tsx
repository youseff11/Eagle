import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Navigate, useNavigate, useParams } from "react-router";
import {
  parsePasted,
  refusalText,
  useAddRows,
  useB2bLead,
  useB2bSheet,
  useDeleteLead,
  useDeleteSheet,
  useLeadCall,
  useLeadEmail,
  useLeadWhatsapp,
  useSaveLead,
  useSaveSheet,
  type B2bChoice,
  type B2bColumn,
  type B2bLead,
  type B2bSheetResponse,
  type LeadValues,
} from "../api/b2b";
import { useMe } from "../api/queries";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { Modal } from "../components/Modal";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

type Columns = B2bSheetResponse["columns"];

/** The Arabic words for the pipeline and the call outcomes (the server's labels are the English ones). */
const STATUS_AR: Record<string, string> = {
  new: "جديد",
  email_sent: "اتبعت إيميل",
  follow_up_1: "متابعة 1",
  follow_up_2: "متابعة 2",
  meeting: "اجتماع متحدد",
  proposal: "اتبعت عرض / Rate sheet",
  negotiation: "تفاوض",
  won: "اتقفلت (Won)",
  lost: "خسرناها (Lost)",
};
const OUTCOME_AR: Record<string, string> = {
  interested: "مهتم",
  follow_up: "نتابع معاه",
  quotation: "طلب عرض سعر",
  no_answer: "مردّش",
  not_interested: "مش مهتم",
};

function useChoiceLabel() {
  const { lang } = usePreferences();
  return (choice: B2bChoice, words: Record<string, string>) => (lang === "ar" ? (words[choice.value] ?? choice.label) : choice.label);
}

function Problem({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="note note--danger" role="alert" style={{ margin: "10px 0" }}>
      <Icon name="alert" />
      <div>{text}</div>
    </div>
  );
}

/** The time a channel first reached the company, under its number or address. */
function Reached({ at, label }: { at: string; label: string }) {
  if (!at) return null;
  return (
    <div className="chip chip--sm chip--replied" title={at} style={{ marginTop: 4 }}>
      <Icon name="check" size="sm" />
      {label} <span className="mono">{at}</span>
    </div>
  );
}

const EMPTY_ROW: LeadValues = {
  company_name: "",
  country: "",
  website: "",
  industry: "",
  contact_person: "",
  position: "",
  email: "",
  phone: "",
  whatsapp: "",
  linkedin: "",
  languages: "",
  services: "",
  source: "",
  status: "new",
  next_follow_up: "",
  notes: "",
};

/** A row typed in, or one corrected: every column, the status, the next follow-up and the notes. */
function LeadForm({
  data,
  lead,
  onClose,
}: {
  data: B2bSheetResponse;
  lead: B2bLead | null;
  onClose: () => void;
}) {
  const { t, lang } = usePreferences();
  const label = useChoiceLabel();
  const add = useAddRows(data.sheet.id);
  const save = useSaveLead();
  const remove = useDeleteLead();
  const [values, setValues] = useState<LeadValues>(() => {
    if (!lead) return { ...EMPTY_ROW };
    const { id: _id, client_code: _c, whatsapp_at: _w, email_at: _e, call_at: _k, last_contact_at: _l, overdue: _o, ...rest } = lead;
    return rest;
  });
  const [problem, setProblem] = useState("");
  const busy = add.isPending || save.isPending || remove.isPending;
  const fallback = t("مقدرتش أحفظ. جرّب تاني.", "Could not save. Try again.");
  const set = (name: keyof LeadValues, value: string) => setValues((before) => ({ ...before, [name]: value }));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setProblem("");
    if (!values.company_name.trim()) {
      setProblem(t("اكتب اسم الشركة.", "Write the company name."));
      return;
    }
    const onError = (failure: unknown) => setProblem(refusalText(failure, lang, fallback));
    if (lead) {
      save.mutate({ id: lead.id, values }, { onSuccess: onClose, onError });
    } else {
      const { status: _s, next_follow_up: _n, notes: _x, ...row } = values;
      add.mutate([row], { onSuccess: onClose, onError });
    }
  };

  const drop = () => {
    if (!lead || busy) return;
    setProblem("");
    remove.mutate(lead.id, { onSuccess: onClose, onError: (failure) => setProblem(refusalText(failure, lang, fallback)) });
  };

  return (
    <Modal title={lead ? lead.company_name : t("شركة جديدة", "New company")} icon="building" busy={busy} wide onClose={onClose}>
      <form onSubmit={submit}>
        <div className="grid grid--main">
          {data.columns.map((column) => (
            <div className="field" key={column.name}>
              <label htmlFor={`lead-${column.name}`}>{lang === "ar" ? column.ar : column.en}</label>
              <input
                className="input"
                id={`lead-${column.name}`}
                maxLength={column.max}
                dir={["email", "phone", "whatsapp", "website", "linkedin"].includes(column.name) ? "ltr" : undefined}
                value={values[column.name]}
                onChange={(event) => set(column.name, event.target.value)}
              />
            </div>
          ))}
          {lead && (
            <>
              <div className="field">
                <label htmlFor="lead-status">{t("الحالة", "Status")}</label>
                <select className="input" id="lead-status" value={values.status} onChange={(event) => set("status", event.target.value)}>
                  {data.statuses.map((choice) => (
                    <option key={choice.value} value={choice.value}>
                      {label(choice, STATUS_AR)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="lead-follow">{t("المتابعة الجاية", "Next follow-up")}</label>
                <input className="input" id="lead-follow" type="date" value={values.next_follow_up} onChange={(event) => set("next_follow_up", event.target.value)} />
              </div>
            </>
          )}
        </div>
        {lead && (
          <div className="field">
            <label htmlFor="lead-notes">{t("ملاحظات", "Notes")}</label>
            <textarea className="input" id="lead-notes" rows={3} maxLength={4000} value={values.notes} onChange={(event) => set("notes", event.target.value)} />
          </div>
        )}
        <small className="muted">
          {t("رقم الواتساب بكود الدولة (+44…): ده اللي الزرار بيبعت عليه.", "Write the WhatsApp number with its country code (+44…): the button sends to it.")}
        </small>
        <Problem text={problem} />
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn btn--primary" type="submit" disabled={busy}>
            <Icon name="check" />
            {lead ? t("احفظ", "Save") : t("ضيف الشركة", "Add the company")}
          </button>
          <div className="grow" />
          {lead && !lead.whatsapp_at && !lead.email_at && !lead.call_at && (
            <button className="btn btn--danger" type="button" onClick={drop} disabled={busy}>
              <Icon name="trash" />
              {t("امسح الصف", "Delete the row")}
            </button>
          )}
        </div>
      </form>
    </Modal>
  );
}

/** Rows copied from Google Sheets or Excel, pasted in one go: the columns in the sheet's order. */
function PasteRows({ sheetId, columns, onClose }: { sheetId: number; columns: Columns; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const toasts = useToasts();
  const add = useAddRows(sheetId);
  const [text, setText] = useState("");
  const [problem, setProblem] = useState("");
  const rows = useMemo(() => parsePasted(text, columns).filter((row) => (row.company_name ?? "") !== ""), [text, columns]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (add.isPending || rows.length === 0) return;
    setProblem("");
    add.mutate(rows, {
      onSuccess: (answer) => {
        toasts.push({ level: "success", title: t(`اتضاف ${answer.added} شركة`, `${answer.added} companies added`) });
        onClose();
      },
      onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أضيفهم. جرّب تاني.", "Could not add them. Try again."))),
    });
  };

  return (
    <Modal title={t("لزق من شيت", "Paste from a spreadsheet")} icon="upload" busy={add.isPending} wide onClose={onClose}>
      <form onSubmit={submit}>
        <p className="muted">
          {t(
            "انسخ الصفوف من Google Sheets أو Excel ولزّقها هنا. الأعمدة لازم تبقى بالترتيب ده (صف العناوين لو موجود بيتشال لوحده):",
            "Copy the rows from Google Sheets or Excel and paste them here. The columns must be in this order (a header row is left out by itself):",
          )}
        </p>
        <div className="mono muted" style={{ fontSize: ".78rem", marginBottom: 8 }}>
          {columns.map((column) => (lang === "ar" ? column.ar : column.en)).join(" · ")}
        </div>
        <textarea
          className="input mono"
          rows={8}
          dir="ltr"
          value={text}
          aria-label={t("الصفوف", "Rows")}
          onChange={(event) => setText(event.target.value)}
        />
        <div className="muted" style={{ marginTop: 6 }}>
          {t(`${rows.length} شركة جاهزة تتضاف`, `${rows.length} companies ready to add`)}
        </div>
        <Problem text={problem} />
        <button className="btn btn--primary" type="submit" disabled={add.isPending || rows.length === 0} style={{ marginTop: 10 }}>
          <Icon name="plus" />
          {t("ضيفهم", "Add them")}
        </button>
      </form>
    </Modal>
  );
}

/** The manager's box: rename the sheet, rewrite its note, hand it to another Sales person, or delete it. */
function SheetSettings({ data, onClose }: { data: B2bSheetResponse; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const navigate = useNavigate();
  const save = useSaveSheet(data.sheet.id);
  const remove = useDeleteSheet(data.sheet.id);
  const [title, setTitle] = useState(data.sheet.title);
  const [note, setNote] = useState(data.sheet.note);
  const [person, setPerson] = useState(String(data.sheet.assigned_to?.id ?? ""));
  const [problem, setProblem] = useState("");
  const busy = save.isPending || remove.isPending;
  const fallback = t("مقدرتش أحفظ. جرّب تاني.", "Could not save. Try again.");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setProblem("");
    save.mutate(
      { title: title.trim(), note: note.trim(), assigned_to: Number(person) },
      { onSuccess: onClose, onError: (failure) => setProblem(refusalText(failure, lang, fallback)) },
    );
  };

  return (
    <Modal title={t("الشيت", "The sheet")} icon="sliders" busy={busy} onClose={onClose}>
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="setTitle">{t("اسم الشيت", "Sheet name")}</label>
          <input className="input" id="setTitle" maxLength={160} value={title} onChange={(event) => setTitle(event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="setSales">{t("الـSales", "Sales person")}</label>
          <select className="input" id="setSales" value={person} onChange={(event) => setPerson(event.target.value)}>
            {data.sales.map((one) => (
              <option key={one.id} value={one.id}>
                {one.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="setNote">{t("المطلوب منه", "What you want from it")}</label>
          <textarea className="input" id="setNote" rows={2} maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} />
        </div>
        <Problem text={problem} />
        <div className="row">
          <button className="btn btn--primary" type="submit" disabled={busy}>
            <Icon name="check" />
            {t("احفظ", "Save")}
          </button>
          <div className="grow" />
          <button
            className="btn btn--danger"
            type="button"
            disabled={busy}
            onClick={() => remove.mutate(undefined, { onSuccess: () => navigate("/leads"), onError: (failure) => setProblem(refusalText(failure, lang, fallback)) })}
          >
            <Icon name="trash" />
            {t("امسح الشيت", "Delete the sheet")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** The WhatsApp button's question: the opening message goes from the person's own number, then the chat opens. */
function StartWhatsapp({ lead, onClose }: { lead: B2bLead; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const navigate = useNavigate();
  const toasts = useToasts();
  const start = useLeadWhatsapp();
  const [problem, setProblem] = useState("");

  const go = () => {
    if (start.isPending) return;
    setProblem("");
    start.mutate(lead.id, {
      onSuccess: (answer) => {
        if (answer.sent) toasts.push({ level: "success", title: t("الرسالة الافتتاحية اتبعتت", "The opening message was sent") });
        navigate(`/chats/${encodeURIComponent(answer.chat)}`);
      },
      onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أبعت. جرّب تاني.", "Could not send. Try again."))),
    });
  };

  return (
    <Modal title={t("واتساب", "WhatsApp")} icon="message" busy={start.isPending} onClose={onClose}>
      <p>
        {t(
          `الشركة دي عمرها ما كلمتنا، فواتساب مش هيوصّلها غير الرسالة الافتتاحية المتوافق عليها (بالإنجليزي، من رقمك). هتتبعت لـ${lead.contact_person || lead.company_name} وبعدين الشات هيتفتح. أول ما يردّوا تكلمهم عادي.`,
          `This company has never written to us, so WhatsApp carries only the approved opening message (in English, from your number). It goes to ${lead.contact_person || lead.company_name}, then the chat opens. Once they answer you write to them as usual.`,
        )}
      </p>
      <p className="muted">
        {t(
          "لو كلّموك في آخر 24 ساعة، أو الرسالة الافتتاحية اتبعتت النهارده ومردّوش، مفيش حاجة هتتبعت: الشات هيتفتح بس.",
          "If they wrote to you in the last 24 hours, or the opening message already went today without an answer, nothing is sent: the chat just opens.",
        )}
      </p>
      <Problem text={problem} />
      <div className="row">
        <button className="btn btn--primary" type="button" onClick={go} disabled={start.isPending}>
          <Icon name="send" />
          {t("ابعت وافتح الشات", "Send and open the chat")}
        </button>
        <button className="btn btn--ghost" type="button" onClick={onClose} disabled={start.isPending}>
          {t("لأ", "Cancel")}
        </button>
      </div>
    </Modal>
  );
}

function letterFor(lead: B2bLead, sender: string): string {
  const name = lead.contact_person.trim().split(" ")[0] || "there";
  const pairs = lead.languages.trim();
  return [
    `Dear ${name},`,
    "",
    `I am ${sender} from EagleLingua, a translation company based in Egypt. We work with translation agencies worldwide${pairs ? ` on ${pairs}` : ""} and would be glad to support ${lead.company_name}.`,
    "",
    "Would you be open to a short call this week? I can also send our rate sheet.",
    "",
    "Best regards,",
    sender,
  ].join("\n");
}

/** The e-mail button: a letter written here, from the person's own address. */
function SendEmail({ lead, sender, onClose }: { lead: B2bLead; sender: string; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const toasts = useToasts();
  const send = useLeadEmail();
  const [subject, setSubject] = useState("Translation partnership with EagleLingua");
  const [body, setBody] = useState(() => letterFor(lead, sender));
  const [problem, setProblem] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (send.isPending) return;
    setProblem("");
    send.mutate(
      { id: lead.id, subject: subject.trim(), body: body.trim() },
      {
        onSuccess: () => {
          toasts.push({ level: "success", title: t("الإيميل اتبعت", "The e-mail was sent") });
          onClose();
        },
        onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أبعت. جرّب تاني.", "Could not send. Try again."))),
      },
    );
  };

  return (
    <Modal title={t("إيميل", "E-mail")} icon="mail" busy={send.isPending} wide onClose={onClose}>
      <form onSubmit={submit}>
        <div className="muted mono" dir="ltr" style={{ marginBottom: 8 }}>
          {lead.email}
        </div>
        <div className="field">
          <label htmlFor="mailSubject">{t("العنوان", "Subject")}</label>
          <input className="input" id="mailSubject" dir="ltr" maxLength={250} value={subject} onChange={(event) => setSubject(event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="mailBody">{t("الرسالة", "Message")}</label>
          <textarea className="input" id="mailBody" dir="ltr" rows={10} maxLength={20000} value={body} onChange={(event) => setBody(event.target.value)} />
        </div>
        <small className="muted">{t("بتطلع من إيميلك، وردّهم بيوصل لـ«ميلاتي».", "It leaves from your address; their answer arrives in «My mail».")}</small>
        <Problem text={problem} />
        <button className="btn btn--primary" type="submit" disabled={send.isPending} style={{ marginTop: 10 }}>
          <Icon name="send" />
          {t("ابعت", "Send")}
        </button>
      </form>
    </Modal>
  );
}

function nowLocal(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

/** A phone call, written by hand: the outcome, the notes, and when to follow up. */
function LogCall({ lead, outcomes, onClose }: { lead: B2bLead; outcomes: B2bChoice[]; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const label = useChoiceLabel();
  const call = useLeadCall();
  const [outcome, setOutcome] = useState("");
  const [at, setAt] = useState(nowLocal);
  const [minutes, setMinutes] = useState("");
  const [notes, setNotes] = useState("");
  const [followUp, setFollowUp] = useState(lead.next_follow_up);
  const [problem, setProblem] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (call.isPending) return;
    setProblem("");
    if (!outcome) {
      setProblem(t("اختار نتيجة المكالمة.", "Choose the outcome of the call."));
      return;
    }
    call.mutate(
      {
        id: lead.id,
        values: { outcome, at, notes: notes.trim(), next_follow_up: followUp, duration_minutes: minutes === "" ? null : Number(minutes) },
      },
      { onSuccess: onClose, onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أسجّل. جرّب تاني.", "Could not log it. Try again."))) },
    );
  };

  return (
    <Modal title={t("سجّل مكالمة", "Log a call")} icon="phone" busy={call.isPending} onClose={onClose}>
      <form onSubmit={submit}>
        <div className="muted" style={{ marginBottom: 8 }}>
          {lead.company_name}
          {lead.contact_person && ` · ${lead.contact_person}`}
        </div>
        <div className="field">
          <label htmlFor="callOutcome">{t("النتيجة", "Outcome")}</label>
          <select className="input" id="callOutcome" value={outcome} onChange={(event) => setOutcome(event.target.value)}>
            <option value="">{t("— اختار —", "— choose —")}</option>
            {outcomes.map((choice) => (
              <option key={choice.value} value={choice.value}>
                {label(choice, OUTCOME_AR)}
              </option>
            ))}
          </select>
        </div>
        <div className="grid grid--main">
          <div className="field">
            <label htmlFor="callAt">{t("إمتى", "When")}</label>
            <input className="input" id="callAt" type="datetime-local" value={at} onChange={(event) => setAt(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="callMinutes">{t("المدة بالدقايق (اختياري)", "Minutes (optional)")}</label>
            <input
              className="input"
              id="callMinutes"
              type="number"
              min={0}
              max={600}
              value={minutes}
              onChange={(event) => setMinutes(event.target.value)}
            />
          </div>
        </div>
        <div className="field">
          <label htmlFor="callNotes">{t("ملاحظات", "Notes")}</label>
          <textarea className="input" id="callNotes" rows={3} maxLength={4000} value={notes} onChange={(event) => setNotes(event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="callFollow">{t("المتابعة الجاية", "Next follow-up")}</label>
          <input className="input" id="callFollow" type="date" value={followUp} onChange={(event) => setFollowUp(event.target.value)} />
        </div>
        <Problem text={problem} />
        <button className="btn btn--primary" type="submit" disabled={call.isPending}>
          <Icon name="check" />
          {t("سجّل", "Log it")}
        </button>
      </form>
    </Modal>
  );
}

/** A row's timeline: every message that reached the company, every call. */
function Timeline({ leadId, outcomes, onClose }: { leadId: number; outcomes: B2bChoice[]; onClose: () => void }) {
  const { t } = usePreferences();
  const label = useChoiceLabel();
  const detail = useB2bLead(leadId);
  const kinds: Record<string, [string, string, string]> = {
    whatsapp: ["message", "واتساب", "WhatsApp"],
    email: ["mail", "إيميل", "E-mail"],
    call: ["phone", "مكالمة", "Call"],
  };
  const data = detail.data;

  return (
    <Modal title={data?.lead.company_name ?? t("السجل", "Timeline")} icon="history" onClose={onClose}>
      {data ? (
        data.activities.length ? (
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {data.activities.map((row) => {
              const [icon, ar, en] = kinds[row.kind] ?? ["info", row.kind, row.kind];
              const outcome = outcomes.find((choice) => choice.value === row.outcome);
              return (
                <li key={row.id} data-activity={row.id} style={{ padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
                  <div className="row row--tight">
                    <Icon name={icon} size="sm" />
                    <strong>{t(ar, en)}</strong>
                    {outcome && <span className="chip chip--sm">{label(outcome, OUTCOME_AR)}</span>}
                    <span className="muted">{row.automatic ? t("اتسجّل لوحده", "recorded by itself") : row.by?.name}</span>
                    <div className="grow" />
                    <span className="mono muted">{row.at}</span>
                  </div>
                  {row.duration_minutes != null && <div className="muted">{t(`${row.duration_minutes} دقيقة`, `${row.duration_minutes} minutes`)}</div>}
                  {row.notes && <div>{row.notes}</div>}
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="empty">
            <Icon name="history" size="xl" />
            <span>{t("لسه محدش تواصل معاهم.", "Nobody has contacted them yet.")}</span>
          </div>
        )
      ) : detail.isError ? (
        <Problem text={t("حصلت مشكلة في التحميل.", "Could not load.")} />
      ) : (
        <Loading className="empty" />
      )}
    </Modal>
  );
}

type Open =
  | { kind: "new" }
  | { kind: "paste" }
  | { kind: "settings" }
  | { kind: "edit" | "whatsapp" | "email" | "call"; lead: B2bLead }
  | { kind: "timeline"; id: number };

function ContactCell({ value, children, at, reached }: { value: string; children?: ReactNode; at: string; reached: string }) {
  return (
    <td>
      <div className="row row--tight" style={{ flexWrap: "nowrap" }}>
        <span className="mono" dir="ltr">
          {value || "—"}
        </span>
        {children}
      </div>
      <Reached at={at} label={reached} />
    </td>
  );
}

/** One sheet: its companies, the three ways to reach each one, and (for the manager) the sheet's own settings. */
export function LeadSheetPage() {
  const { t } = usePreferences();
  const label = useChoiceLabel();
  const me = useMe();
  const { id } = useParams();
  const sheetId = /^\d{1,9}$/.test(id ?? "") ? Number(id) : 0;
  const allowed = me.data !== undefined && (me.data.user.role === "sales" || me.data.user.is_admin);
  const sheet = useB2bSheet(allowed ? sheetId : 0);
  const [open, setOpen] = useState<Open | null>(null);
  const [search, setSearch] = useState("");

  const data = sheet.data;
  const leads = useMemo(() => {
    const words = search.trim().toLowerCase();
    if (!data) return [];
    if (!words) return data.leads;
    return data.leads.filter((lead) =>
      (["company_name", "country", "contact_person", "email", "whatsapp", "phone"] as B2bColumn[]).some((name) => lead[name].toLowerCase().includes(words)),
    );
  }, [data, search]);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!sheetId) return <Navigate to="/leads" replace />;
  if (sheet.isError) {
    return (
      <div className="card empty" role="alert">
        <Icon name="alert" size="xl" />
        <span>{t("الشيت ده مش موجود أو مش بتاعك.", "This sheet does not exist or is not yours.")}</span>
      </div>
    );
  }
  if (!data) return <Loading />;

  const contact = data.sheet.can_contact;
  const sender = me.data ? `${me.data.user.name}` : "";
  const close = () => setOpen(null);
  const status = (value: string) => {
    const choice = data.statuses.find((one) => one.value === value);
    return choice ? label(choice, STATUS_AR) : value;
  };

  return (
    <>
      <div className="page-head">
        <h1>{data.sheet.title}</h1>
        <span className="page-head__sub">
          {t("مع", "With")} {data.sheet.assigned_to?.name ?? "—"} · {t(`${data.sheet.contacted} من ${data.sheet.rows} اتواصلنا معاهم`, `${data.sheet.contacted} of ${data.sheet.rows} contacted`)}
        </span>
      </div>

      {data.sheet.note && (
        <div className="note note--info" style={{ marginBottom: 14 }}>
          <Icon name="info" />
          <div>{data.sheet.note}</div>
        </div>
      )}
      {!contact && (
        <div className="note note--info" style={{ marginBottom: 14 }}>
          <Icon name="eye" />
          <div>{t("التواصل من الشيت ده لصاحبه بس (من رقمه وإيميله). تقدر تعدّل الصفوف وتتابع.", "Only the sheet's own Sales person contacts from it (from their number and address). You can edit the rows and follow along.")}</div>
        </div>
      )}

      <div className="card">
        <div className="row" style={{ marginBottom: 12 }}>
          <button className="btn btn--primary" type="button" onClick={() => setOpen({ kind: "new" })}>
            <Icon name="plus" />
            {t("شركة جديدة", "New company")}
          </button>
          <button className="btn" type="button" onClick={() => setOpen({ kind: "paste" })}>
            <Icon name="upload" />
            {t("لزق من شيت", "Paste from a spreadsheet")}
          </button>
          {data.sheet.can_manage && (
            <button className="btn" type="button" onClick={() => setOpen({ kind: "settings" })}>
              <Icon name="sliders" />
              {t("إعدادات الشيت", "Sheet settings")}
            </button>
          )}
          <div className="grow" />
          <div className="field-icon" style={{ margin: 0 }}>
            <Icon name="search" className="ic--lead" />
            <input className="input" value={search} maxLength={100} placeholder={t("ابحث…", "Search…")} aria-label={t("بحث", "Search")} onChange={(event) => setSearch(event.target.value)} />
          </div>
        </div>

        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t("الشركة", "Company")}</th>
                <th>{t("الشخص", "Contact")}</th>
                <th>{t("واتساب", "WhatsApp")}</th>
                <th>{t("الإيميل", "Email")}</th>
                <th>{t("التليفون", "Phone")}</th>
                <th>{t("الحالة", "Status")}</th>
                <th>{t("المتابعة الجاية", "Next follow-up")}</th>
                <th>{t("آخر تواصل", "Last contact")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {leads.map((lead) => (
                <tr key={lead.id} data-lead={lead.id}>
                  <td>
                    <strong>{lead.company_name}</strong>
                    <div className="muted">{[lead.country, lead.industry].filter(Boolean).join(" · ")}</div>
                    {lead.languages && <div className="muted">{lead.languages}</div>}
                  </td>
                  <td>
                    {lead.contact_person || "—"}
                    {lead.position && <div className="muted">{lead.position}</div>}
                  </td>
                  <ContactCell value={lead.whatsapp} at={lead.whatsapp_at} reached={t("اتبعت", "sent")}>
                    {contact && (lead.whatsapp || lead.phone) && (
                      <button className="icon-btn" type="button" title={t("ابعت واتساب", "Send WhatsApp")} aria-label={t("ابعت واتساب", "Send WhatsApp")} onClick={() => setOpen({ kind: "whatsapp", lead })}>
                        <Icon name="message" />
                      </button>
                    )}
                  </ContactCell>
                  <ContactCell value={lead.email} at={lead.email_at} reached={t("اتبعت", "sent")}>
                    {contact && lead.email && (
                      <button className="icon-btn" type="button" title={t("ابعت إيميل", "Send e-mail")} aria-label={t("ابعت إيميل", "Send e-mail")} onClick={() => setOpen({ kind: "email", lead })}>
                        <Icon name="mail" />
                      </button>
                    )}
                  </ContactCell>
                  <ContactCell value={lead.phone} at={lead.call_at} reached={t("مكالمة", "call")}>
                    {contact && (
                      <button className="icon-btn" type="button" title={t("سجّل مكالمة", "Log a call")} aria-label={t("سجّل مكالمة", "Log a call")} onClick={() => setOpen({ kind: "call", lead })}>
                        <Icon name="phone" />
                      </button>
                    )}
                  </ContactCell>
                  <td>
                    <span className="chip chip--sm">{status(lead.status)}</span>
                  </td>
                  <td className={lead.overdue ? "mono deadline--late" : "mono"}>{lead.next_follow_up || "—"}</td>
                  <td className="mono">{lead.last_contact_at || "—"}</td>
                  <td>
                    <div className="row row--tight" style={{ flexWrap: "nowrap" }}>
                      <button className="icon-btn" type="button" title={t("السجل", "Timeline")} aria-label={t("السجل", "Timeline")} onClick={() => setOpen({ kind: "timeline", id: lead.id })}>
                        <Icon name="history" />
                      </button>
                      <button className="icon-btn" type="button" title={t("تعديل", "Edit")} aria-label={t("تعديل", "Edit")} onClick={() => setOpen({ kind: "edit", lead })}>
                        <Icon name="pen" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {leads.length === 0 && (
                <tr>
                  <td colSpan={9} className="empty">
                    <Icon name="building" size="xl" />
                    <span>
                      {data.leads.length
                        ? t("مفيش شركة بالبحث ده.", "No company matches.")
                        : t("الشيت فاضي. ضيف شركة أو لزّق صفوف من Google Sheets.", "The sheet is empty. Add a company or paste rows from Google Sheets.")}
                    </span>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {open?.kind === "new" && <LeadForm data={data} lead={null} onClose={close} />}
      {open?.kind === "edit" && <LeadForm data={data} lead={open.lead} onClose={close} />}
      {open?.kind === "paste" && <PasteRows sheetId={data.sheet.id} columns={data.columns} onClose={close} />}
      {open?.kind === "settings" && <SheetSettings data={data} onClose={close} />}
      {open?.kind === "whatsapp" && <StartWhatsapp lead={open.lead} onClose={close} />}
      {open?.kind === "email" && <SendEmail lead={open.lead} sender={sender} onClose={close} />}
      {open?.kind === "call" && <LogCall lead={open.lead} outcomes={data.outcomes} onClose={close} />}
      {open?.kind === "timeline" && <Timeline leadId={open.id} outcomes={data.outcomes} onClose={close} />}
    </>
  );
}
