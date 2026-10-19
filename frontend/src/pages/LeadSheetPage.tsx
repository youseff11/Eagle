import { useDeferredValue, useEffect, useMemo, useRef, useState, type ClipboardEvent, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import {
  refusalCode,
  refusalText,
  useAddNote,
  useAddRows,
  useB2bLead,
  useB2bSheet,
  useDeleteLead,
  useDeleteSheet,
  useLeadCall,
  useLeadWhatsapp,
  useMoveLead,
  useReadRows,
  useSaveCell,
  useSaveLead,
  useSaveSheet,
  useSendMessage,
  type B2bChoice,
  type B2bColumn,
  type B2bLead,
  type B2bSheetResponse,
  type LeadValues,
  type ReadRowsResponse,
} from "../api/b2b";
import { usePlanVisit } from "../api/b2c";
import { useMe } from "../api/queries";
import { Duplicates } from "../components/b2b/Duplicates";
import { FollowUpBadge } from "../components/b2b/FollowUpBadge";
import { ImportRows } from "../components/b2b/ImportRows";
import { PAGE_ROWS, Pages, pageWithin } from "../components/b2b/Pages";
import { keepPlace, readPlace } from "../lib/sheetPlace";
import { filledValues, isCopiedRow } from "../components/b2b/pastedRow";
import { QuoteStatus, QuotesModal } from "../components/b2b/QuotesModal";
import { B2C_GRID_COLUMNS, B2C_STATUS_AR, ChoiceCell, GRID_COLUMNS, LOST_AR, NotesCell, PRIORITY_AR, STATUS_AR, TextCell } from "../components/b2b/SheetGrid";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { Modal } from "../components/Modal";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";


/** The Arabic words for the call outcomes (the server's labels are the English ones); the status list is the sheet's own. */
const OUTCOME_AR: Record<string, string> = {
  interested: "مهتم",
  follow_up: "نتابع معاه",
  quotation: "طلب عرض سعر",
  contracted: "تم التعاقد",
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

/** How big the sheet is drawn (19/10/2026: «زوم إن / زوم آوت»), kept in this browser for every sheet. */
const ZOOM_KEY = "eagle.sheetZoom";
const ZOOM_STEPS = [0.5, 0.6, 0.7, 0.8, 0.9, 1, 1.1, 1.25, 1.5];
function readZoom(): number {
  try {
    const saved = Number(localStorage.getItem(ZOOM_KEY));
    return ZOOM_STEPS.includes(saved) ? saved : 1;
  } catch {
    return 1;
  }
}
function keepZoom(value: number) {
  try {
    localStorage.setItem(ZOOM_KEY, String(value));
  } catch {
    // A browser that keeps nothing draws the sheet at 100% next time.
  }
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
  governorate: "",
  address: "",
  location: "",
  status: "new",
  priority: "",
  deal_value: "",
  next_follow_up: "",
  customer_type: "",
  lost_reason: "",
};

/** The stage words of the sheet's own team. */
const stageWords = (data: B2bSheetResponse) => (data.sheet.market === "b2c" ? B2C_STATUS_AR : STATUS_AR);
/** The Arabic words for company / individual. */
const CUSTOMER_AR: Record<string, string> = { company: "شركة", individual: "فرد" };

/** A row typed in, or one corrected: every column, the status, the priority, the deal value and the next follow-up. A new
 * company may come with its first note; the notes of a company on the sheet are added in their cell. */
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
  const readRows = useReadRows(data.sheet.id);
  const [values, setValues] = useState<LeadValues>(() => {
    if (!lead) return { ...EMPTY_ROW };
    const {
      id: _id, client_code: _c, whatsapp_at: _w, email_at: _e, call_at: _k, last_contact_at: _l, overdue: _o,
      replied_at: _r, last_outreach_at: _lo, follow_up: _f, quote: _q, phones: _p, notes: _n, map_link: _m, ...rest
    } = lead;
    return rest;
  });
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");
  const busy = add.isPending || save.isPending || remove.isPending;
  const fallback = t("مقدرتش أحفظ. جرّب تاني.", "Could not save. Try again.");
  const set = (name: keyof LeadValues, value: string) => setValues((before) => ({ ...before, [name]: value }));
  const b2c = data.sheet.market === "b2c";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setProblem("");
    if (!values.company_name.trim()) {
      setProblem(t("اكتب اسم الشركة.", "Write the company name."));
      return;
    }
    if (b2c && values.status === "lost" && !values.lost_reason) {
      setProblem(t("اختار سبب الخسارة.", "Choose why the company was lost."));
      return;
    }
    const onError = (failure: unknown) => setProblem(refusalText(failure, lang, fallback));
    if (lead) {
      save.mutate({ id: lead.id, values }, { onSuccess: onClose, onError });
    } else {
      add.mutate([{ ...values, notes: note.trim() }], { onSuccess: onClose, onError });
    }
  };

  // A row copied from the team's Google Sheet pasted into any box (13/10/2026: it all went into the company name): read on
  // the server the way an upload is, and each cell put in its own box, to check before saving.
  const pasteRow = (event: ClipboardEvent<HTMLFormElement>) => {
    const text = event.clipboardData.getData("text/plain");
    if (!isCopiedRow(text)) return;
    event.preventDefault();
    setProblem("");
    readRows.mutate(
      { text },
      {
        onSuccess: (answer) => {
          const [row, ...more] = answer.rows;
          if (!row) return;
          const { values: filled, note: words } = filledValues(row);
          setValues((before) => ({ ...before, ...filled }));
          if (words && !lead) setNote((before) => (before ? `${before}
${words}` : words));
          if (more.length > 0) {
            setProblem(
              t(
                "لزقت أكتر من صف: اتاخد أول واحد بس. للباقي استخدم «ارفع Excel أو Google Sheet».",
                "More than one row was pasted: only the first was taken. For the rest use «Upload Excel or Google Sheets».",
              ),
            );
          }
        },
        onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أقرا الصف.", "Could not read the row."))),
      },
    );
  };

  const drop = () => {
    if (!lead || busy) return;
    setProblem("");
    remove.mutate(lead.id, { onSuccess: onClose, onError: (failure) => setProblem(refusalText(failure, lang, fallback)) });
  };

  return (
    <Modal title={lead ? lead.company_name : t("شركة جديدة", "New company")} icon="building" busy={busy} wide onClose={onClose}>
      <form onSubmit={submit} onPaste={pasteRow}>
        <div className="grid grid--main">
          {data.columns.map((column) => (
            <div className="field" key={column.name}>
              <label htmlFor={`lead-${column.name}`}>{lang === "ar" ? column.ar : column.en}</label>
              {column.name === "phone" || column.name === "whatsapp" ? (
                // A company has more than one number: one a line.
                <textarea
                  className="input"
                  id={`lead-${column.name}`}
                  rows={2}
                  dir="ltr"
                  maxLength={column.max}
                  placeholder={t("كل رقم في سطر", "One number a line")}
                  value={values[column.name]}
                  onChange={(event) => set(column.name, event.target.value)}
                />
              ) : (
                <input
                  className="input"
                  id={`lead-${column.name}`}
                  maxLength={column.max}
                  placeholder={column.name === "location" ? t("لينك Google Maps أو 30.0444, 31.2357", "A Google Maps link or 30.0444, 31.2357") : undefined}
                  dir={["email", "website", "linkedin", "location"].includes(column.name) ? "ltr" : undefined}
                  value={values[column.name]}
                  onChange={(event) => set(column.name, event.target.value)}
                />
              )}
            </div>
          ))}
          <div className="field">
            <label htmlFor="lead-status">{t("الحالة", "Status")}</label>
            <select className="input" id="lead-status" value={values.status} onChange={(event) => set("status", event.target.value)}>
              {data.statuses.map((choice) => (
                <option key={choice.value} value={choice.value}>
                  {label(choice, stageWords(data))}
                </option>
              ))}
            </select>
          </div>
          {b2c && values.status === "lost" && (
            <div className="field">
              <label htmlFor="lead-lost">{t("سبب الخسارة", "Why it was lost")}</label>
              <select className="input" id="lead-lost" value={values.lost_reason ?? ""} onChange={(event) => set("lost_reason", event.target.value)}>
                <option value="">{t("— اختار —", "— choose —")}</option>
                {data.lost_reasons.map((choice) => (
                  <option key={choice.value} value={choice.value}>
                    {label(choice, LOST_AR)}
                  </option>
                ))}
              </select>
            </div>
          )}
          {b2c && (
            <div className="field">
              <label htmlFor="lead-kind">{t("نوع العميل", "Customer type")}</label>
              <select className="input" id="lead-kind" value={values.customer_type ?? ""} onChange={(event) => set("customer_type", event.target.value)}>
                <option value="">—</option>
                {data.customer_types.map((choice) => (
                  <option key={choice.value} value={choice.value}>
                    {label(choice, CUSTOMER_AR)}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="field">
            <label htmlFor="lead-priority">{b2c ? t("الاهتمام", "Interest") : t("الأولوية", "Priority")}</label>
            <select className="input" id="lead-priority" value={values.priority} onChange={(event) => set("priority", event.target.value)}>
              <option value="">—</option>
              {data.priorities.map((choice) => (
                <option key={choice.value} value={choice.value}>
                  {label(choice, PRIORITY_AR)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="lead-deal">{t("قيمة الصفقة", "Deal value")}</label>
            <input className="input" id="lead-deal" dir="ltr" inputMode="decimal" maxLength={20} value={values.deal_value} onChange={(event) => set("deal_value", event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="lead-follow">{t("المتابعة الجاية", "Next follow-up")}</label>
            <input className="input" id="lead-follow" type="date" value={values.next_follow_up} onChange={(event) => set("next_follow_up", event.target.value)} />
          </div>
        </div>
        {!lead && (
          <div className="field">
            <label htmlFor="lead-notes">{t("ملاحظة", "Note")}</label>
            <textarea className="input" id="lead-notes" rows={2} maxLength={4000} value={note} onChange={(event) => setNote(event.target.value)} />
          </div>
        )}
        <small className="muted">
          {b2c
            ? t("كل رقم في سطر. اللوكيشن: افتح الشركة في Google Maps وانسخ اللينك الطويل أو الإحداثيات: الزيارة بتتقاس عليه.", "One number a line. Location: open the company in Google Maps and copy the long link or the coordinates: visits are measured against it.")
            : t("أرقام الواتساب بكود الدولة (+44…)، كل رقم في سطر: دي اللي الرسايل بتروح عليها.", "Write the WhatsApp numbers with their country code (+44…), one a line: messages go to them.")}
        </small>
        <Problem text={problem} />
        {lead && data.sheets.length > 0 && <MoveLead lead={lead} sheets={data.sheets} onMoved={onClose} />}
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

/** The manager hands one company to another Sales person: to another sheet, and so to whoever holds it. */
function MoveLead({ lead, sheets, onMoved }: { lead: B2bLead; sheets: B2bSheetResponse["sheets"]; onMoved: () => void }) {
  const { t, lang } = usePreferences();
  const toasts = useToasts();
  const move = useMoveLead();
  const [target, setTarget] = useState("");
  const [problem, setProblem] = useState("");

  const go = () => {
    if (!target || move.isPending) return;
    setProblem("");
    move.mutate(
      { id: lead.id, sheet: Number(target) },
      {
        onSuccess: () => {
          toasts.push({ level: "success", title: t("الشركة اتنقلت", "The company was moved") });
          onMoved();
        },
        onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أنقلها. جرّب تاني.", "Could not move it. Try again."))),
      },
    );
  };

  return (
    <div className="field" style={{ marginTop: 12 }}>
      <label htmlFor="moveTo">{t("انقلها لشيت تاني", "Move it to another sheet")}</label>
      <div className="row row--tight">
        <select className="input grow" id="moveTo" value={target} onChange={(event) => setTarget(event.target.value)}>
          <option value="">{t("— اختار الشيت —", "— choose the sheet —")}</option>
          {sheets.map((sheet) => (
            <option key={sheet.id} value={sheet.id}>
              {sheet.title} · {sheet.assigned_to?.name ?? "—"}
            </option>
          ))}
        </select>
        <button className="btn" type="button" onClick={go} disabled={!target || move.isPending}>
          <Icon name="forward" />
          {t("انقل", "Move")}
        </button>
      </div>
      <Problem text={problem} />
    </div>
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
            onClick={() => remove.mutate(undefined, { onSuccess: () => navigate(data.sheet.market === "b2c" ? "/b2c" : "/leads"), onError: (failure) => setProblem(refusalText(failure, lang, fallback)) })}
          >
            <Icon name="trash" />
            {t("امسح الشيت", "Delete the sheet")}
          </button>
        </div>
      </form>
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

/**
 * The send button: a message to one of the company's WhatsApp numbers or to its address, from the person's own line, and
 * the row marked by itself once it has left. WhatsApp carries a written message only to a number that wrote to this
 * person in the last 24 hours (the server checks it): otherwise the approved opening message goes instead, and the chat
 * opens.
 */
function SendMessage({ lead, sender, onClose }: { lead: B2bLead; sender: string; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const navigate = useNavigate();
  const toasts = useToasts();
  const send = useSendMessage();
  const intro = useLeadWhatsapp();
  const targets = [
    ...lead.phones.map((number) => ({ key: `wa:${number}`, channel: "whatsapp" as const, to: number })),
    ...(lead.email ? [{ key: "mail", channel: "email" as const, to: lead.email }] : []),
  ];
  const [key, setKey] = useState(targets[0]?.key ?? "");
  const target = targets.find((one) => one.key === key) ?? targets[0];
  const [words, setWords] = useState("");
  const [subject, setSubject] = useState("Translation partnership with EagleLingua");
  const [letter, setLetter] = useState(() => letterFor(lead, sender));
  const [closed, setClosed] = useState(false);
  const [problem, setProblem] = useState("");
  const busy = send.isPending || intro.isPending;
  const fallback = t("مقدرتش أبعت. جرّب تاني.", "Could not send. Try again.");

  const pick = (next: string) => {
    setKey(next);
    setClosed(false);
    setProblem("");
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy || !target) return;
    setProblem("");
    const mail = target.channel === "email";
    send.mutate(
      { id: lead.id, channel: target.channel, to: target.to, subject: mail ? subject.trim() : "", body: (mail ? letter : words).trim() },
      {
        onSuccess: () => {
          toasts.push({ level: "success", title: t("الرسالة اتبعتت واتسجلت في الصف", "The message was sent and marked on the row") });
          onClose();
        },
        onError: (failure) => {
          if (refusalCode(failure) === "window_closed") setClosed(true);
          else setProblem(refusalText(failure, lang, fallback));
        },
      },
    );
  };

  const opening = () => {
    if (busy || !target) return;
    setProblem("");
    intro.mutate(
      { id: lead.id, number: target.to },
      {
        onSuccess: (answer) => {
          if (answer.sent) toasts.push({ level: "success", title: t("الرسالة الافتتاحية اتبعتت", "The opening message was sent") });
          navigate(`/chats/${encodeURIComponent(answer.chat)}`);
        },
        onError: (failure) => setProblem(refusalText(failure, lang, fallback)),
      },
    );
  };

  if (!target) {
    return (
      <Modal title={t("ابعت رسالة", "Send a message")} icon="send" onClose={onClose}>
        <p>{t("مفيش رقم ولا إيميل للشركة دي. ضيفهم في الصف الأول.", "This company has no number and no address. Add them on the row first.")}</p>
      </Modal>
    );
  }

  return (
    <Modal title={t("ابعت رسالة", "Send a message")} icon="send" busy={busy} wide onClose={onClose}>
      <form onSubmit={submit}>
        <fieldset className="field" style={{ border: 0, padding: 0, margin: "0 0 12px" }}>
          <legend>{t("ابعت على", "Send to")}</legend>
          {targets.map((one) => (
            <label key={one.key} className="row row--tight" style={{ cursor: "pointer" }}>
              <input type="radio" name="send-to" value={one.key} checked={target.key === one.key} onChange={() => pick(one.key)} />
              <Icon name={one.channel === "email" ? "mail" : "message"} size="sm" />
              <span className="mono" dir="ltr">
                {one.to}
              </span>
            </label>
          ))}
        </fieldset>
        {target.channel === "whatsapp" ? (
          <>
            <div className="field">
              <label htmlFor="sendWords">{t("الرسالة", "Message")}</label>
              <textarea className="input" id="sendWords" dir="auto" rows={5} maxLength={20000} value={words} onChange={(event) => setWords(event.target.value)} />
            </div>
            {closed ? (
              <div className="note note--info" role="status" style={{ marginBottom: 10 }}>
                <Icon name="info" />
                <div>
                  {t(
                    "الرقم ده ماكلّمكش في آخر 24 ساعة، فواتساب مش هيوصّل الرسالة دي. ابعت الرسالة الافتتاحية المتوافق عليها (بالإنجليزي، من رقمك)، وأول ما يردّوا تكلمهم عادي.",
                    "This number has not written to you in the last 24 hours, so WhatsApp will not carry this message. Send the approved opening message (in English, from your number); once they answer you write to them as usual.",
                  )}
                </div>
              </div>
            ) : (
              <small className="muted">
                {t(
                  "واتساب بيوصّل رسالتك بس لو الرقم ده كلّمك في آخر 24 ساعة. شركة لسه ماكلّمتناش: ابعتلها الرسالة الافتتاحية.",
                  "WhatsApp carries your message only if this number wrote to you in the last 24 hours. A company that has not written yet: send it the opening message.",
                )}
              </small>
            )}
          </>
        ) : (
          <>
            <div className="field">
              <label htmlFor="mailSubject">{t("العنوان", "Subject")}</label>
              <input className="input" id="mailSubject" dir="ltr" maxLength={250} value={subject} onChange={(event) => setSubject(event.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="mailBody">{t("الرسالة", "Message")}</label>
              <textarea className="input" id="mailBody" dir="ltr" rows={10} maxLength={20000} value={letter} onChange={(event) => setLetter(event.target.value)} />
            </div>
            <small className="muted">{t("بتطلع من إيميلك، وردّهم بيوصل لـ«ميلاتي».", "It leaves from your address; their answer arrives in «My mail».")}</small>
          </>
        )}
        <Problem text={problem} />
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn btn--primary" type="submit" disabled={busy}>
            <Icon name="send" />
            {t("ابعت", "Send")}
          </button>
          {target.channel === "whatsapp" && (
            <button className={closed ? "btn btn--primary" : "btn"} type="button" onClick={opening} disabled={busy}>
              <Icon name="message" />
              {t("ابعت الرسالة الافتتاحية", "Send the opening message")}
            </button>
          )}
          <button className="btn btn--ghost" type="button" onClick={onClose} disabled={busy}>
            {t("لأ", "Cancel")}
          </button>
        </div>
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
function Timeline({ leadId, outcomes, words, onClose }: { leadId: number; outcomes: B2bChoice[]; words: Record<string, string>; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const statusWord = (value: string) => (lang === "ar" ? (words[value] ?? value) : value);
  const label = useChoiceLabel();
  const detail = useB2bLead(leadId);
  const kinds: Record<string, [string, string, string]> = {
    whatsapp: ["message", "واتساب", "WhatsApp"],
    email: ["mail", "إيميل", "E-mail"],
    call: ["phone", "مكالمة", "Call"],
    status: ["target", "الحالة اتغيّرت", "Stage changed"],
    quotation: ["file", "عرض سعر", "Quotation"],
    visit: ["map-pin", "زيارة", "Field visit"],
  };
  const quoteWord: Record<string, [string, string]> = {
    created: ["اتعمل", "made"],
    sent: ["اتبعت", "sent"],
    accepted: ["اتقبل", "accepted"],
    rejected: ["اترفض", "turned down"],
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
                    {row.incoming && <span className="chip chip--sm chip--replied">{t("ردّوا", "They answered")}</span>}
                    {row.kind === "status" && <span className="chip chip--sm">{statusWord(row.status)}</span>}
                    {row.kind === "quotation" && (
                      <span className="chip chip--sm">
                        <span className="mono">{row.quotation}</span> {t(...(quoteWord[row.notes] ?? [row.notes, row.notes]))}
                      </span>
                    )}
                    <span className="muted">{row.automatic ? t("اتسجّل لوحده", "recorded by itself") : row.by?.name}</span>
                    <div className="grow" />
                    <span className="mono muted">{row.at}</span>
                  </div>
                  {row.duration_minutes != null && <div className="muted">{t(`${row.duration_minutes} دقيقة`, `${row.duration_minutes} minutes`)}</div>}
                  {row.notes && row.kind !== "quotation" && row.kind !== "status" && <div>{row.notes}</div>}
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

/**
 * A B2C stage that needs more than the cell (15/10/2026): «خسرناه» asks why, «مستنيين رده» and «متابعة بعدين» ask the day of
 * the next follow-up. The server holds the same rule (`b2c.check_stage`); this only asks before it refuses.
 */
function StageWindow({ data, lead, status, onClose }: { data: B2bSheetResponse; lead: B2bLead; status: string; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const label = useChoiceLabel();
  const save = useSaveCell();
  const lost = status === "lost";
  const [reason, setReason] = useState(lead.lost_reason);
  const [day, setDay] = useState(lead.next_follow_up);
  const [problem, setProblem] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (save.isPending) return;
    if (lost ? !reason : !day) {
      setProblem(lost ? t("اختار سبب الخسارة.", "Choose why the company was lost.") : t("حدد ميعاد المتابعة الجاية.", "Set the day of the next follow-up."));
      return;
    }
    save.mutate(
      { id: lead.id, values: lost ? { status, lost_reason: reason } : { status, next_follow_up: day } },
      { onSuccess: onClose, onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أحفظ. جرّب تاني.", "Could not save. Try again."))) },
    );
  };

  return (
    <Modal title={`${lead.company_name} · ${lang === "ar" ? (B2C_STATUS_AR[status] ?? status) : status}`} icon="target" busy={save.isPending} onClose={onClose}>
      <form onSubmit={submit}>
        {lost ? (
          <div className="field">
            <label htmlFor="stageReason">{t("سبب الخسارة", "Why it was lost")}</label>
            <select className="input" id="stageReason" value={reason} onChange={(event) => setReason(event.target.value)}>
              <option value="">{t("— اختار —", "— choose —")}</option>
              {data.lost_reasons.map((choice) => (
                <option key={choice.value} value={choice.value}>
                  {label(choice, LOST_AR)}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div className="field">
            <label htmlFor="stageDay">{t("المتابعة الجاية", "Next follow-up")}</label>
            <input className="input" id="stageDay" type="date" value={day} onChange={(event) => setDay(event.target.value)} />
          </div>
        )}
        <Problem text={problem} />
        <button className="btn btn--primary" type="submit" disabled={save.isPending}>
          <Icon name="check" />
          {t("احفظ", "Save")}
        </button>
      </form>
    </Modal>
  );
}

/** A visit planned from the company's row: the purpose and, if known, when. «وصلت» is pressed on the visits page, at the company. */
function PlanVisit({ lead, onClose }: { lead: B2bLead; onClose: () => void }) {
  const { t, lang } = usePreferences();
  const toasts = useToasts();
  const navigate = useNavigate();
  const plan = usePlanVisit();
  const [purpose, setPurpose] = useState("");
  const [when, setWhen] = useState("");
  const [problem, setProblem] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (plan.isPending) return;
    setProblem("");
    plan.mutate(
      { lead: lead.id, purpose: purpose.trim(), planned_at: when },
      {
        onSuccess: (answer) => {
          toasts.push({ level: "success", title: t(`الزيارة ${answer.visit.code} اتعملت`, `Visit ${answer.visit.code} planned`) });
          onClose();
          navigate("/b2c/visits");
        },
        onError: (failure) => setProblem(refusalText(failure, lang, t("مقدرتش أعمل الزيارة. جرّب تاني.", "Could not plan the visit. Try again."))),
      },
    );
  };

  return (
    <Modal title={`${t("زيارة", "Visit")} · ${lead.company_name}`} icon="map-pin" busy={plan.isPending} onClose={onClose}>
      <form onSubmit={submit}>
        {!lead.map_link && (
          <div className="note note--info" style={{ marginBottom: 10 }}>
            <Icon name="info" />
            <div>
              {t(
                "الشركة دي مالهاش لوكيشن، فالزيارة هتروح للمانجر يراجعها. حط لينك Google Maps بتاعها في خانة «اللوكيشن» لو تعرفه.",
                "This company has no location, so the visit goes to the manager to review. Put its Google Maps link in «Location» if you know it.",
              )}
            </div>
          </div>
        )}
        <div className="field">
          <label htmlFor="visitPurpose">{t("الغرض من الزيارة", "Purpose of the visit")}</label>
          <input className="input" id="visitPurpose" maxLength={250} value={purpose} onChange={(event) => setPurpose(event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="visitWhen">{t("الميعاد (اختياري)", "When (optional)")}</label>
          <input className="input" id="visitWhen" type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} />
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

/** Which rows the sheet shows: all of them, or the ones that need something. */
type Only = "all" | "due" | "replied" | "untouched" | "interested";
const ONLY: Record<Only, (lead: B2bLead) => boolean> = {
  all: () => true,
  due: (lead) => lead.follow_up === "today" || lead.follow_up === "overdue",
  replied: (lead) => lead.replied_at !== "",
  // A stage set by hand («call», «whatsapp»...) is a company we talked to, from the Sales person's own phone (19/10/2026).
  untouched: (lead) => !lead.reached,
  // The companies whose last call ended «مهتم» (20/10/2026: the ones worth a follow-up first).
  interested: (lead) => lead.call_outcome === "interested",
};

type Open =
  | { kind: "new" }
  | { kind: "paste"; pasted?: { text: string; answer: ReadRowsResponse } }
  | { kind: "settings" }
  | { kind: "duplicates" }
  | { kind: "edit" | "send" | "call" | "visit"; lead: B2bLead }
  | { kind: "stage"; lead: B2bLead; status: string }
  | { kind: "timeline"; id: number }
  | { kind: "quotes"; id: number };

/** One sheet: its companies, the three ways to reach each one, and (for the manager) the sheet's own settings. */
export function LeadSheetPage() {
  const { t, lang } = usePreferences();
  const me = useMe();
  const { id } = useParams();
  const sheetId = /^\d{1,9}$/.test(id ?? "") ? Number(id) : 0;
  const allowed = me.data !== undefined && (me.data.user.role === "sales" || me.data.user.is_admin);
  const sheet = useB2bSheet(allowed ? sheetId : 0);
  const [open, setOpen] = useState<Open | null>(null);
  const [search, setSearch] = useState("");
  // A sheet holds 5000 companies: one page of them is drawn at a time, and the search runs behind the typing. The page
  // and the view are kept for the sheet, so coming back from a chat opens where the person was (`lib/sheetPlace`).
  const [place] = useState(() => readPlace(sheetId, Object.keys(ONLY)));
  const [only, setOnly] = useState<Only>(place.only as Only);
  const [page, setPage] = useState(place.page);
  const typed = useDeferredValue(search);
  const top = useRef<HTMLDivElement>(null);
  const toasts = useToasts();
  const readRows = useReadRows(sheetId);
  const [zoom, setZoom] = useState(readZoom);
  const zoomTo = (step: number) => {
    const at = ZOOM_STEPS.indexOf(zoom);
    const next = step === 0 ? 1 : ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, Math.max(0, (at < 0 ? ZOOM_STEPS.indexOf(1) : at) + step))];
    setZoom(next);
    keepZoom(next);
  };
  const saveCell = useSaveCell();
  const addNote = useAddNote();

  const data = sheet.data;
  const leads = useMemo(() => {
    const words = typed.trim().toLowerCase();
    if (!data) return [];
    return data.leads.filter(
      (lead) =>
        ONLY[only](lead) &&
        (!words ||
          (["company_name", "country", "contact_person", "email", "whatsapp", "phone"] as B2bColumn[]).some((name) => lead[name].toLowerCase().includes(words))),
    );
  }, [data, typed, only]);
  const shown = pageWithin(page, leads.length);

  // The last row a message left from with its send button is marked (15/10/2026): the sheet opens on its page and shows
  // it, so the Sales person writes to the one after it; «آخر صف بعتله» walks back to it from anywhere.
  const lastSent = data?.leads.find((lead) => lead.id === data.sheet.last_sent) ?? null;
  const [seek, setSeek] = useState(0);
  const opened = useRef(false);
  useEffect(() => {
    if (!data || opened.current) return;
    opened.current = true;
    const at = leads.findIndex((lead) => lead.id === data.sheet.last_sent);
    if (at < 0) return;
    setPage(Math.floor(at / PAGE_ROWS));
    setSeek(leads[at].id);
  }, [data, leads]);
  useEffect(() => {
    if (!seek) return;
    document.querySelector(`tr[data-lead="${seek}"]`)?.scrollIntoView?.({ block: "center" });
    setSeek(0);
  }, [seek, shown]);

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
  // The company's chat is on the sheet's own Sales person's line: theirs to open, and the owner's (`lines.sees`).
  const opensChats = contact || Boolean(me.data?.user.is_admin);
  // The B2C team's sheet has its own columns and stages (15/10/2026).
  const columns = data.sheet.market === "b2c" ? B2C_GRID_COLUMNS : GRID_COLUMNS;
  const words = stageWords(data);
  const b2c = data.sheet.market === "b2c";
  const toLastSent = () => {
    if (!lastSent) return;
    const at = data.leads.findIndex((lead) => lead.id === lastSent.id);
    const next = Math.floor(at / PAGE_ROWS);
    setSearch("");
    setOnly("all");
    setPage(next);
    keepPlace(sheetId, { page: next, only: "all" });
    setSeek(lastSent.id);
  };
  const sender = me.data ? `${me.data.user.name}` : "";
  const close = () => setOpen(null);

  // A row copied from the team's Google Sheet and pasted into one cell (13/10/2026: the whole row landed in the company
  // name): the server reads it the way it reads an upload, each cell by what it holds, and each one goes to its own column
  // of that row. Several rows pasted are new companies: they open the upload with the rows in it.
  const pasteRow = (event: ClipboardEvent<HTMLTableSectionElement>) => {
    const text = event.clipboardData.getData("text/plain");
    const id = Number((event.target as HTMLElement).closest<HTMLElement>("tr[data-lead]")?.dataset.lead);
    if (!isCopiedRow(text) || !id) return;
    event.preventDefault();
    // The cell typed in lets go first, so its blur does not write what it held back over what the row brings.
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    const failed = (failure: unknown) =>
      toasts.push({ level: "danger", title: refusalText(failure, lang, t("الصف ماتحفظش. جرّب تاني.", "The row was not saved. Try again.")) });
    readRows.mutate(
      { text },
      {
        onSuccess: (answer) => {
          if (answer.rows.length > 1) {
            setOpen({ kind: "paste", pasted: { text, answer } });
            return;
          }
          if (answer.rows.length === 0) return;
          const { values, note } = filledValues(answer.rows[0]);
          saveCell.mutate(
            { id, values },
            { onSuccess: () => void (note && addNote.mutate({ id, text: note }, { onError: failed })), onError: failed },
          );
        },
        onError: failed,
      },
    );
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

      <div className="card" ref={top}>
        <div className="row" style={{ marginBottom: 12 }}>
          <button className="btn btn--primary" type="button" onClick={() => setOpen({ kind: "new" })}>
            <Icon name="plus" />
            {t("شركة جديدة", "New company")}
          </button>
          <button className="btn" type="button" onClick={() => setOpen({ kind: "paste" })}>
            <Icon name="upload" />
            {t("ارفع Excel أو Google Sheet", "Upload Excel or Google Sheets")}
          </button>
          <button className="btn" type="button" onClick={() => setOpen({ kind: "duplicates" })}>
            <Icon name="layers" />
            {t("الصفوف المكررة", "Duplicate rows")}
          </button>
          {data.sheet.can_manage && (
            <button className="btn" type="button" onClick={() => setOpen({ kind: "settings" })}>
              <Icon name="sliders" />
              {t("إعدادات الشيت", "Sheet settings")}
            </button>
          )}
          {lastSent && (
            <button className="btn" type="button" title={lastSent.company_name} onClick={toLastSent}>
              <Icon name="map-pin" />
              {t("آخر صف بعتله", "Last row I wrote to")}
            </button>
          )}
          <div className="grow" />
          <div className="row row--tight sheet-zoom" role="group" aria-label={t("حجم الشيت", "Sheet size")}>
            <button className="btn" type="button" title={t("صغّر", "Zoom out")} aria-label={t("صغّر", "Zoom out")} disabled={zoom <= ZOOM_STEPS[0]} onClick={() => zoomTo(-1)}>
              −
            </button>
            <button className="btn mono" type="button" title={t("رجّعه 100%", "Back to 100%")} aria-label={t("رجّعه 100%", "Back to 100%")} onClick={() => zoomTo(0)}>
              {Math.round(zoom * 100)}%
            </button>
            <button className="btn" type="button" title={t("كبّر", "Zoom in")} aria-label={t("كبّر", "Zoom in")} disabled={zoom >= ZOOM_STEPS[ZOOM_STEPS.length - 1]} onClick={() => zoomTo(1)}>
              +
            </button>
          </div>
          <select className="input" style={{ width: "auto" }} value={only} aria-label={t("اعرض", "Show")} onChange={(event) => {
              const next = event.target.value as Only;
              setOnly(next);
              setPage(0);
              if (!search.trim()) keepPlace(sheetId, { page: 0, only: next });
            }}>
            <option value="all">{t("كل الشركات", "All companies")}</option>
            <option value="due">{t("متابعة النهارده أو متأخرة", "Follow-up due or overdue")}</option>
            <option value="replied">{t("ردّوا علينا", "They answered")}</option>
            <option value="untouched">{t("لسه ماتواصلناش", "Not contacted yet")}</option>
            <option value="interested">{t("المهتمين", "Interested")}</option>
          </select>
          <div className="field-icon" style={{ margin: 0 }}>
            <Icon name="search" className="ic--lead" />
            <input className="input" value={search} maxLength={100} placeholder={t("ابحث…", "Search…")} aria-label={t("بحث", "Search")} onChange={(event) => {
              setSearch(event.target.value);
              // A search starts on its first page; wiping it goes back to the page the person was on before it.
              setPage(event.target.value.trim() ? 0 : readPlace(sheetId, Object.keys(ONLY)).page);
            }} />
          </div>
        </div>

        <div className="sheet-wrap">
          <table className="sheet" style={zoom === 1 ? undefined : { zoom }} data-zoom={zoom}>
            <colgroup>
              {columns.map((column) => (
                <col key={column.name} style={{ width: column.width }} />
              ))}
              <col style={{ width: 250 }} />
            </colgroup>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column.name} data-column={column.name}>
                    {lang === "ar" ? column.ar : column.en}
                  </th>
                ))}
                <th>{t("التواصل", "Reach")}</th>
              </tr>
              <tr className="sheet__band" aria-hidden="true">
                <td colSpan={columns.length + 1} />
              </tr>
            </thead>
            <tbody onPaste={pasteRow}>
              {leads.slice(shown * PAGE_ROWS, (shown + 1) * PAGE_ROWS).map((lead) => (
                <tr key={lead.id} data-lead={lead.id} className={lead.id === lastSent?.id ? "sheet__row--last" : undefined}>
                  {columns.map((column) => {
                    const name = lang === "ar" ? column.ar : column.en;
                    return (
                      <td key={column.name} className={`sheet__td sheet__td--${column.name}`}>
                        {column.name === "status" ? (
                          <ChoiceCell
                            lead={lead}
                            name="status"
                            label={name}
                            choices={data.statuses}
                            words={words}
                            intercept={(next) => {
                              if (!b2c || !["lost", "waiting", "later"].includes(next)) return false;
                              setOpen({ kind: "stage", lead, status: next });
                              return true;
                            }}
                          >
                            {lead.quote && (
                              <div className="sheet__under" data-lead-quote={lead.quote.code}>
                                <span className="mono">{lead.quote.code}</span> <QuoteStatus status={lead.quote.status} />
                              </div>
                            )}
                          </ChoiceCell>
                        ) : column.name === "priority" ? (
                          <ChoiceCell lead={lead} name="priority" label={name} choices={data.priorities} words={PRIORITY_AR} empty />
                        ) : column.name === "notes" ? (
                          <NotesCell lead={lead} label={name} meId={me.data?.user.id ?? 0} manages={data.sheet.can_manage} />
                        ) : (
                          <TextCell lead={lead} name={column.name} label={name} max={column.max} ltr={column.ltr} multiline={column.multiline} />
                        )}
                      </td>
                    );
                  })}
                  <td className="sheet__tools">
                    <div className="row row--tight" style={{ flexWrap: "nowrap" }}>
                      {contact && (lead.phones.length > 0 || lead.email) && (
                        <button
                          className={`icon-btn${lead.whatsapp_at || lead.email_at ? " is-done" : ""}`}
                          type="button"
                          title={t("ابعت رسالة", "Send a message")}
                          aria-label={t("ابعت رسالة", "Send a message")}
                          onClick={() => setOpen({ kind: "send", lead })}
                        >
                          <Icon name="send" />
                        </button>
                      )}
                      {opensChats && lead.client_code && (
                        <Link
                          className="icon-btn is-done"
                          to={`/chats/${encodeURIComponent(lead.client_code)}`}
                          title={t("افتح الشات", "Open the chat")}
                          aria-label={`${t("افتح الشات", "Open the chat")} · ${lead.company_name}`}
                        >
                          <Icon name="message" />
                        </Link>
                      )}
                      {contact && (
                        <button
                          className={`icon-btn${lead.call_at ? " is-done" : ""}`}
                          type="button"
                          title={t("سجّل مكالمة", "Log a call")}
                          aria-label={t("سجّل مكالمة", "Log a call")}
                          onClick={() => setOpen({ kind: "call", lead })}
                        >
                          <Icon name="phone" />
                        </button>
                      )}
                      {data.sheet.can_visit && (
                        <button
                          className={`icon-btn${lead.last_outreach_at ? " is-done" : ""}`}
                          type="button"
                          title={t("زيارة", "Visit")}
                          aria-label={`${t("زيارة", "Visit")} · ${lead.company_name}`}
                          onClick={() => setOpen({ kind: "visit", lead })}
                        >
                          <Icon name="map-pin" />
                        </button>
                      )}
                      {lead.map_link && (
                        <a className="icon-btn" href={lead.map_link} target="_blank" rel="noreferrer noopener" title={t("على الخريطة", "On the map")} aria-label={`${t("على الخريطة", "On the map")} · ${lead.company_name}`}>
                          <Icon name="globe" />
                        </a>
                      )}
                      <button className="icon-btn" type="button" title={t("عروض الأسعار", "Quotations")} aria-label={t("عروض الأسعار", "Quotations")} onClick={() => setOpen({ kind: "quotes", id: lead.id })}>
                        <Icon name="file" />
                      </button>
                      <button className="icon-btn" type="button" title={t("السجل", "Timeline")} aria-label={t("السجل", "Timeline")} onClick={() => setOpen({ kind: "timeline", id: lead.id })}>
                        <Icon name="history" />
                      </button>
                      <button className="icon-btn" type="button" title={t("تعديل", "Edit")} aria-label={t("تعديل", "Edit")} onClick={() => setOpen({ kind: "edit", lead })}>
                        <Icon name="pen" />
                      </button>
                    </div>
                    {lead.id === lastSent?.id && (
                      <div className="chip chip--sm chip--last" style={{ marginTop: 4 }}>
                        <Icon name="map-pin" size="sm" />
                        {t("آخر واحد بعتله", "The last one I wrote to")}
                      </div>
                    )}
                    <Reached at={lead.whatsapp_at} label={t("واتساب", "WhatsApp")} />
                    <Reached at={lead.email_at} label={t("إيميل", "E-mail")} />
                    <Reached at={lead.call_at} label={t("مكالمة", "Call")} />
                    {lead.call_outcome && (
                      <div className="chip chip--sm chip--outcome" data-call-outcome={lead.call_outcome} style={{ marginTop: 4 }}>
                        <Icon name="phone" size="sm" />
                        {t("آخر مكالمة:", "Last call:")} <strong>{lang === "ar" ? (OUTCOME_AR[lead.call_outcome] ?? lead.call_outcome) : (data.outcomes.find((choice) => choice.value === lead.call_outcome)?.label ?? lead.call_outcome)}</strong>
                      </div>
                    )}
                    {lead.replied_at && (
                      <div className="chip chip--sm chip--replied" title={lead.replied_at} style={{ marginTop: 4 }}>
                        <Icon name="reply" size="sm" />
                        {t("ردّوا", "They answered")} <span className="mono">{lead.replied_at}</span>
                      </div>
                    )}
                    {lead.next_follow_up && (
                      <div className="sheet__under">
                        <span className="muted">{t("المتابعة الجاية", "Next follow-up")}</span> <FollowUpBadge date={lead.next_follow_up} state={lead.follow_up} />
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {leads.length === 0 && (
                <tr>
                  <td colSpan={columns.length + 1} className="empty">
                    <Icon name="building" size="xl" />
                    <span>
                      {data.leads.length
                        ? t("مفيش شركة بالبحث أو الاختيار ده.", "No company matches.")
                        : t("الشيت فاضي. ضيف شركة أو ارفع ملف Excel أو Google Sheet.", "The sheet is empty. Add a company or upload a file from Excel or Google Sheets.")}
                    </span>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <Pages
          page={shown}
          count={leads.length}
          onPage={(next) => {
            setPage(next);
            if (!search.trim()) keepPlace(sheetId, { page: next, only });
            top.current?.scrollIntoView?.({ block: "start" });
          }}
        />
      </div>

      {open?.kind === "new" && <LeadForm data={data} lead={null} onClose={close} />}
      {open?.kind === "edit" && <LeadForm data={data} lead={open.lead} onClose={close} />}
      {open?.kind === "paste" && <ImportRows sheetId={data.sheet.id} columns={data.columns} pasted={open.pasted} onClose={close} />}
      {open?.kind === "settings" && <SheetSettings data={data} onClose={close} />}
      {open?.kind === "duplicates" && <Duplicates sheetId={data.sheet.id} leads={data.leads} onClose={close} />}
      {open?.kind === "send" && <SendMessage lead={open.lead} sender={sender} onClose={close} />}
      {open?.kind === "call" && <LogCall lead={open.lead} outcomes={data.outcomes} onClose={close} />}
      {open?.kind === "timeline" && <Timeline leadId={open.id} outcomes={data.outcomes} words={words} onClose={close} />}
      {open?.kind === "stage" && <StageWindow data={data} lead={open.lead} status={open.status} onClose={close} />}
      {open?.kind === "visit" && <PlanVisit lead={open.lead} onClose={close} />}
      {open?.kind === "quotes" && <QuotesModal leadId={open.id} onClose={close} />}
    </>
  );
}
