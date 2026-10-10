import { Loading } from "../components/Loading";
import { useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";
import { ApiError } from "../api/client";
import { useCreateTask } from "../api/opsActions";
import { useMe, useTaskStart } from "../api/queries";
import type { TaskStartResponse } from "../api/types";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { safeInternalPath } from "../lib/safeUrl";

const REQUIREMENT_ICON: Record<string, string> = { like: "thumbs-up", dislike: "thumbs-down", rule: "pin" };

/** What the address may pass on to the server: the ids of messages and files, and the code of the task it repeats. */
function startQuery(params: URLSearchParams): string {
  const out = new URLSearchParams();
  for (const name of ["message", "messages", "files", "texts"]) {
    for (const value of params.getAll(name)) {
      if (/^[0-9, ]{1,400}$/.test(value)) out.append(name, value.replace(/ /g, ""));
    }
  }
  const from = params.get("from") ?? "";
  if (/^[A-Za-z0-9-]{1,40}$/.test(from)) out.set("from", from);
  const quote = params.get("quote") ?? "";
  if (/^QT-[0-9]{1,9}$/.test(quote)) out.set("quote", quote);
  const text = out.toString();
  return text ? `?${text}` : "";
}

function Errors({ list }: { list?: string[] }) {
  if (!list || list.length === 0) return null;
  return (
    <ul className="errorlist" role="alert">
      {list.map((text) => (
        <li key={text}>{text}</li>
      ))}
    </ul>
  );
}

function Form({ start }: { start: TaskStartResponse }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const navigate = useNavigate();
  const create = useCreateTask();
  const [values, setValues] = useState({
    client: start.initial.client !== null ? String(start.initial.client) : "",
    title: start.initial.title,
    description: start.initial.description,
    source_lang: start.initial.source_lang,
    target_lang: start.initial.target_lang ?? "",
    priority: "normal",
    days: start.initial.deadline_days != null ? String(start.initial.deadline_days) : "",
    hours: "",
    minutes: "",
    words: start.initial.word_count != null ? String(start.initial.word_count) : "",
    difficult: false,
    secondary: false,
  });
  const [fields, setFields] = useState<Record<string, string[]>>({});
  const [problem, setProblem] = useState("");
  const set = <K extends keyof typeof values>(name: K, value: (typeof values)[K]) => setValues((current) => ({ ...current, [name]: value }));

  const submit = () => {
    setFields({});
    setProblem("");
    const words = values.words.trim();
    create.mutate(
      {
        client: Number(values.client),
        title: values.title,
        description: values.description,
        source_lang: values.source_lang,
        target_lang: values.target_lang,
        priority: values.priority,
        deadline: { days: values.days, hours: values.hours, minutes: values.minutes },
        word_count: /^\d{1,8}$/.test(words) ? Number(words) : null,
        is_difficult: values.difficult,
        is_secondary_language: values.secondary,
        messages: start.messages.map((message) => message.id),
        files: start.picked.map((file) => file.id),
        from: start.from_task?.code ?? "",
        quote: start.quote?.code ?? "",
      },
      {
        onSuccess: (answer) => {
          push({ level: "success", title: answer.code });
          navigate(`/tasks/${encodeURIComponent(answer.code)}`);
        },
        onError: (error) => {
          const payload = error instanceof ApiError && error.payload && typeof error.payload === "object" ? (error.payload as { fields?: Record<string, string[]> }) : {};
          if (payload.fields) setFields(payload.fields);
          else if (error instanceof ApiError && error.code === "client_mismatch")
            setProblem(t("الرسايل دي لعميل تاني: اختار كود العميل بتاعها.", "These messages belong to another client: choose their client code."));
          else if (error instanceof ApiError && error.status < 500) setProblem(t("مقدرتش أعمل التاسك.", "The task could not be made."));
          else setProblem(t("مش متأكدين إن التاسك اتعملت. بص على قايمة التاسكات قبل ما تجرّب تاني.", "We are not sure the task was made. Look at the task list before trying again."));
        },
      },
    );
  };

  const lines = ["source_lang", "target_lang"] as const;

  return (
    <div className="grid grid--main">
      <div className="card">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!create.isPending) submit();
          }}
        >
          {start.quote && (
            <div className="note mt" style={{ marginBottom: 12 }} data-quote={start.quote.code}>
              <Icon name="file" />
              <div>
                <span>{t("التاسك دي من عرض السعر اللي اتقبل", "This task comes from the accepted quotation")}</span>{" "}
                <span className="mono">{start.quote.code}</span>
                {" — "}
                <span>{t("راجع الديدلاين وارفع الملفات لما العميل يبعتها.", "Check the deadline, and attach the files when the client sends them.")}</span>
              </div>
            </div>
          )}

          {start.from_task && (
            <div className="note mt" style={{ marginBottom: 12 }}>
              <Icon name="layers" />
              <div>
                <span>{t("طلب جديد على نفس ملفات", "A new request on the files of")}</span>{" "}
                <Link className="mono" to={`/tasks/${encodeURIComponent(start.from_task.code)}`}>
                  {start.from_task.code}
                </Link>{" "}
                — <span>{t("التاسك القديمة مش بتتلمس.", "The old task is left as it is.")}</span>
              </div>
            </div>
          )}

          <div className="field">
            <label htmlFor="task-client">{t("كود العميل", "Client code")}</label>
            <select id="task-client" className="input" value={values.client} onChange={(event) => set("client", event.target.value)}>
              <option value="" disabled>
                —
              </option>
              {start.clients.map((client) => (
                <option key={client.id} value={client.id}>
                  {client.label}
                </option>
              ))}
            </select>
            <Errors list={fields.client} />
          </div>

          <div className="field">
            <label htmlFor="task-title">{t("عنوان التاسك", "Task title")}</label>
            <input id="task-title" className="input" maxLength={200} value={values.title} onChange={(event) => set("title", event.target.value)} />
            <Errors list={fields.title} />
          </div>

          <div className="field">
            <label htmlFor="task-description">{t("التفاصيل", "Details")}</label>
            <textarea id="task-description" className="input" rows={3} value={values.description} onChange={(event) => set("description", event.target.value)} />
            <Errors list={fields.description} />
          </div>

          <div className="form-grid">
            <datalist id="langOptions">
              {start.languages.map((language) => (
                <option key={language.code} value={language.code}>
                  {language.ar !== language.code ? `${language.ar} · ${language.en}` : ""}
                </option>
              ))}
            </datalist>
            {lines.map((name) => (
              <div className="field" key={name}>
                <label htmlFor={`task-${name}`}>{name === "source_lang" ? t("من لغة", "Source language") : t("للغة", "Target language")}</label>
                <input
                  id={`task-${name}`}
                  className="input"
                  list="langOptions"
                  dir="ltr"
                  autoComplete="off"
                  aria-required="true"
                  placeholder={name === "source_lang" ? "EN" : "AR"}
                  value={values[name]}
                  onChange={(event) => set(name, event.target.value)}
                />
                <div className="lang-picks">
                  {start.quick_languages.map((code) => (
                    <button className="chip chip--sm lang-pick" type="button" key={code} onClick={() => set(name, code)}>
                      {code}
                    </button>
                  ))}
                </div>
                <Errors list={fields[name]} />
              </div>
            ))}
            <div className="field">
              <label htmlFor="task-priority">{t("الأولوية", "Priority")}</label>
              <select id="task-priority" className="input" value={values.priority} onChange={(event) => set("priority", event.target.value)}>
                {start.priorities.map((priority) => (
                  <option key={priority.value} value={priority.value}>
                    {lang === "ar" ? priority.ar : priority.en}
                  </option>
                ))}
              </select>
              <Errors list={fields.priority} />
            </div>
            <div className="field">
              <label>{t("الديدلاين (بتاخده من العميل)", "Deadline (agreed with the client)")}</label>
              <div className="dur">
                {(
                  [
                    ["days", t("يوم", "Days")],
                    ["hours", t("ساعة", "Hours")],
                    ["minutes", t("دقيقة", "Minutes")],
                  ] as const
                ).map(([name, unit]) => (
                  <label className="dur__part" key={name}>
                    <input
                      className="input dur__num"
                      type="number"
                      min={0}
                      step={1}
                      inputMode="numeric"
                      aria-label={unit}
                      value={values[name]}
                      onChange={(event) => set(name, event.target.value)}
                    />
                    <span className="dur__unit">{unit}</span>
                  </label>
                ))}
              </div>
              <Errors list={fields.deadline} />
              <small className="muted">
                {t(
                  "اكتبه زي ما العميل قاله: بعد كام يوم وكام ساعة. سيبها فاضية يعني من غير ديدلاين.",
                  "Enter it the way the client said it - in how many days and hours. Leave it empty for no deadline.",
                )}
              </small>
            </div>
            <div className="field">
              <label htmlFor="task-words">{t("عدد الكلمات", "Word count")}</label>
              <input
                id="task-words"
                className="input"
                type="number"
                min={0}
                dir="ltr"
                inputMode="numeric"
                placeholder="3000"
                value={values.words}
                onChange={(event) => set("words", event.target.value)}
              />
              <Errors list={fields.word_count} />
              <small className="muted">
                {t(
                  "ده اللي الحسابات بتقرا منه إنتاج المترجم — مش بيتكتب من المترجم نفسه. تقدر تسيبه وتكتبه بعدين.",
                  "Accounts reads the translator's production from this, never from the translator. You can leave it and set it later.",
                )}
              </small>
            </div>
          </div>

          <div className="row row--tight mt">
            <label className="switch">
              <input type="checkbox" checked={values.difficult} onChange={(event) => set("difficult", event.target.checked)} />
              <span>{t("ملف صعب (استثناء من الحد الأدنى اليومي)", "Difficult file (exempt from the daily floor)")}</span>
            </label>
            <label className="switch">
              <input type="checkbox" checked={values.secondary} onChange={(event) => set("secondary", event.target.checked)} />
              <span>{t("لغة غير أساسية للمترجم", "Outside the translator's main language")}</span>
            </label>
          </div>

          {problem && (
            <div className="note note--high mt" role="alert">
              <Icon name="alert" />
              <div>{problem}</div>
            </div>
          )}
          <button className="btn btn--primary mt" type="submit" disabled={create.isPending || values.client === ""}>
            <Icon name="check" size="sm" />
            <span>{create.isPending ? t("بيتعمل...", "Making...") : t("اعمل التاسك", "Create task")}</span>
          </button>
        </form>
      </div>

      <div className="sticky-side">
        {start.messages.length > 0 ? (
          <>
            <div className="card">
              <div className="card__head">
                <Icon name="message" />
                <h3>{start.messages.length > 1 ? t("رسايل العميل", "Client messages") : t("الرسالة الأصلية", "Source message")}</h3>
                {start.messages.length > 1 && <span className="chip chip--sm">{start.messages.length}</span>}
              </div>
              <div className="row row--tight" style={{ marginBottom: 8 }}>
                <strong className="mono">{start.client_code}</strong>
                <span className="chip">{start.messages[0]!.channel === "whatsapp" ? "WhatsApp" : "Email"}</span>
              </div>
              {start.messages.map((message) => (
                <div className="src-msg" key={message.id}>
                  {start.messages.length > 1 && message.at && <div className="muted mono src-msg__at">{lang === "ar" ? message.at.ar : message.at.en}</div>}
                  {message.body && (
                    <div className="msg-item__text" style={{ whiteSpace: "pre-wrap" }}>
                      {message.body}
                    </div>
                  )}
                  {message.files.length > 0 && (
                    <div className="files">
                      {message.files.map((file) => {
                        const href = safeInternalPath(file.url);
                        return href ? (
                          <a className="file-pill" key={file.id} href={href} target="_blank" rel="noopener noreferrer">
                            <Icon name="paperclip" size="sm" />
                            {file.name}
                          </a>
                        ) : (
                          <span className="file-pill" key={file.id}>
                            {file.name}
                          </span>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* Which files the translator will get. Said before the task exists. */}
            <div className="card">
              <div className="card__head">
                <Icon name="paperclip" />
                <h3>{t("الملفات اللي هتروح للمترجم", "Files the translator gets")}</h3>
              </div>
              {start.picked.length > 0 ? (
                <div className="files">
                  {start.picked.map((file) => (
                    <span className="file-pill" key={file.id}>
                      <Icon name="paperclip" size="sm" />
                      {file.name}
                    </span>
                  ))}
                </div>
              ) : start.messages.some((message) => message.files.length > 0) || start.messages.length > 1 ? (
                <div className="muted">{t("كل ملفات الرسايل — مااختارتش ملفات معينة.", "Every file on the messages — nothing specific was picked.")}</div>
              ) : (
                <div className="muted">{t("الرسالة دي مفيهاش ملفات.", "This message has no files.")}</div>
              )}
            </div>
          </>
        ) : (
          <div className="note note--info">
            <Icon name="info" />
            <div>
              {t(
                "تقدر تعمل التاسك من ميل في «ميلات واردة» أو من رسالة في شات العملاء، وساعتها تختار الملفات اللي تروح للمترجم.",
                "You can also start a task from a letter in Incoming mail or a message in the client chat, and pick which files reach the translator.",
              )}
            </div>
          </div>
        )}

        {(start.messages.length > 0 || start.from_task) && (
          <div className="card">
            <div className="card__head">
              <Icon name="list-checks" />
              <h3>{t("متطلبات العميل", "Client requirements")}</h3>
            </div>
            {start.requirements.map((requirement) => (
              <div className="note" key={requirement.id}>
                <Icon name={REQUIREMENT_ICON[requirement.kind.value] ?? "pin"} />
                <div>
                  <div className="note__where">
                    {requirement.kind.ar} / {requirement.kind.en}
                  </div>
                  <div>{requirement.text}</div>
                </div>
              </div>
            ))}
            {start.requirements.length === 0 && <div className="muted">{t("مفيش متطلبات مسجلة.", "No requirements recorded.")}</div>}
          </div>
        )}
      </div>
    </div>
  );
}

/** A new task: the form, filled from the client's messages (and the files ticked) when it was opened from one. */
export function NewTaskPage() {
  const { t } = usePreferences();
  const me = useMe();
  const [params] = useSearchParams();
  const search = startQuery(params);
  // The same people the server lets in (`api_role_required`: the operation, and the admin).
  const allowed = me.data !== undefined && (me.data.user.role === "operation" || me.data.user.is_admin);
  const query = useTaskStart(search, allowed);

  if (me.data && !allowed) return <Navigate to="/" replace />;

  return (
    <>
      <div className="page-head">
        <h1>{t("تاسك جديدة", "New task")}</h1>
      </div>
      {query.data ? (
        // Keyed by what it starts from: another message is another form, not the old one with new words poured in.
        <Form key={search} start={query.data} />
      ) : (
        <div className="card">
          {query.isError ? (
            <div className="empty" role="alert">
              <Icon name="alert" size="xl" />
              <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
            </div>
          ) : (
            <Loading className="empty" />
          )}
        </div>
      )}
    </>
  );
}
