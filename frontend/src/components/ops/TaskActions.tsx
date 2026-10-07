import { useState } from "react";
import {
  useAddMember,
  useAssignDirect,
  useAssignLead,
  useCancelTask,
  useDeliver,
  useSaveDeadline,
  useTakeOver,
} from "../../api/opsActions";
import type { OpsTask } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { taskProblem } from "../../lib/taskProblem";
import { Confirm } from "../Confirm";
import { Icon } from "../Icon";
import { useToasts } from "../Toasts";

/** A refusal, in words, under the control that was refused. */
function Problem({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="note note--high mt" role="alert">
      <Icon name="alert" />
      <div>{text}</div>
    </div>
  );
}

/**
 * While no team leader has the site open, the task can go straight to a translator (who has a minute to say yes). That
 * translator's own leader keeps the review and is told. The server offers the list only while nobody is online, and
 * refuses the send as well, so this box is gone the moment a leader opens the site.
 */
function DirectBox({ task }: { task: OpsTask }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const assign = useAssignDirect(task.code);
  const [picked, setPicked] = useState<number | null>(null);
  const [problem, setProblem] = useState("");
  if (!task.direct) return null;
  const word = { free: t("فاضي", "free"), busy: t("مشغول", "busy"), off: t("أوفلاين", "offline") };

  if (task.direct.translators.length === 0) {
    return (
      <div className="note note--warn mt">
        <Icon name="alert" />
        <div>{t("مفيش مترجم تحت تيم ليدر تبعتله التاسك.", "There is no translator under a team leader to send it to.")}</div>
      </div>
    );
  }
  const translator = picked ?? task.direct.translators[0]!.id;

  return (
    <div className="mt" id="directBox">
      <div className="note note--warn">
        <Icon name="alert" />
        <div>
          {t(
            "مفيش تيم ليدر فاتح دلوقتي. تقدر تبعتها للمترجم دايركت — التيم ليدر بتاعه هيتبلّغ وهو اللي هيراجع الشغل.",
            "No team leader is online. You can send it straight to a translator: their team leader is told and still reviews the work.",
          )}
        </div>
      </div>
      <div className="field mt">
        <label htmlFor="direct-select">{t("ابعتها لمترجم دايركت", "Send straight to a translator")}</label>
        <select id="direct-select" className="input" value={translator} onChange={(event) => setPicked(Number(event.target.value))}>
          {task.direct.translators.map((person) => (
            <option key={person.id} value={person.id}>
              {person.name} — {word[person.state]} · {person.rating.toFixed(2)} · {person.lead}
            </option>
          ))}
        </select>
      </div>
      <button
        className="btn btn--block"
        type="button"
        disabled={assign.isPending}
        onClick={() => {
          setProblem("");
          assign.mutate(translator, {
            onSuccess: () => push({ level: "success", title: t("اتبعتت للمترجم", "Sent to the translator") }),
            onError: (error) => setProblem(taskProblem(error, t)),
          });
        }}
      >
        <Icon name="send" size="sm" />
        <span>{assign.isPending ? t("بيتبعت...", "Sending...") : t("ابعتها للمترجم دايركت", "Send to the translator")}</span>
      </button>
      <Problem text={problem} />
    </div>
  );
}

/** A new task goes to one team leader, who has a minute to say yes. Who is here and how loaded each is, beside the name. */
export function AssignLeadBox({ task }: { task: OpsTask }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const assign = useAssignLead(task.code);
  const [leader, setLeader] = useState<number | null>(null);
  const [problem, setProblem] = useState("");
  // The first one is chosen until somebody chooses another: that is what the classic box does.
  const chosen = leader ?? task.leads[0]?.id ?? null;

  if (task.leads.length === 0) {
    return (
      <>
        <div className="note note--warn">
          <Icon name="alert" />
          <div>{t("مفيش تيم ليدرز مسجلين تبعتلهم التاسك.", "There are no team leaders to send it to.")}</div>
        </div>
        <DirectBox task={task} />
      </>
    );
  }

  return (
    <>
      <div className="field">
        <label htmlFor="lead-select">{t("اعمل assign لتيم ليدر", "Assign a team leader")}</label>
        <select
          id="lead-select"
          className="input"
          value={chosen ?? ""}
          onChange={(event) => setLeader(Number(event.target.value))}
        >
          {task.leads.map((lead) => (
            <option key={lead.id} value={lead.id}>
              {lead.name} — {lead.online ? "online" : "offline"} · {lead.tasks} tasks
            </option>
          ))}
        </select>
      </div>
      <button
        className="btn btn--primary btn--block"
        type="button"
        disabled={assign.isPending || chosen === null}
        onClick={() => {
          if (chosen === null) return;
          setProblem("");
          assign.mutate(chosen, {
            onSuccess: () => push({ level: "success", title: t("اتبعت للتيم ليدر", "Sent to the team leader") }),
            onError: (error) => setProblem(taskProblem(error, t)),
          });
        }}
      >
        <Icon name="send" size="sm" />
        <span>{assign.isPending ? t("بيتبعت...", "Sending...") : t("ابعتها للتيم ليدر", "Send to team leader")}</span>
      </button>
      <Problem text={problem} />
      <DirectBox task={task} />
    </>
  );
}

/** The reviewed job is taken off the leader's hands by a person, on record, before any file can go to the client. */
export function TakeOverBox({ task }: { task: OpsTask }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const take = useTakeOver(task.code);
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState("");

  return (
    <>
      <div className="note note--warn">
        <Icon name="shield" />
        <div>
          <strong>{t("التاسك مستنية استلامك", "Waiting for you to take it over")}</strong>
          <div>
            {t(
              "التيم ليدر خلص المراجعة. مفيش ملف بيروح للعميل قبل ما حد يستلم التاسك بإيده.",
              "The team leader is done. No file reaches the client until somebody takes the task over.",
            )}
          </div>
        </div>
      </div>
      <button
        className="btn btn--primary btn--block mt"
        type="button"
        onClick={() => {
          setProblem("");
          setAsking(true);
        }}
      >
        <Icon name="user-check" size="sm" />
        <span>{t("استلمت التاسك", "I have the task")}</span>
      </button>
      {asking && (
        <Confirm
          title={t("تأكيد إنك استلمت التاسك من التيم ليدر؟", "Confirm you are taking this task over?")}
          yes={t("أيوه، استلمتها", "Yes, I have it")}
          icon="user-check"
          busy={take.isPending}
          problem={problem}
          onNo={() => setAsking(false)}
          onYes={() =>
            take.mutate(undefined, {
              onSuccess: () => {
                setAsking(false);
                push({ level: "success", title: t("التاسك مستلمة", "Task taken over") });
              },
              onError: (error) => setProblem(taskProblem(error, t)),
            })
          }
        />
      )}
    </>
  );
}

/**
 * What goes to the client: the files ticked (the translator's own ticked to begin with), a line of words, and the
 * channel it will leave by. Sending cannot be undone - that is why taking the task over is a press of its own.
 */
export function DeliverBox({ task }: { task: OpsTask }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const deliver = useDeliver(task.code);
  const info = task.deliver;
  const [ticked, setTicked] = useState<Set<number> | null>(null);
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");
  const [closing, setClosing] = useState(false);

  if (!info || !task.handover) return null;
  const files = ticked ?? new Set(info.files.filter((file) => file.final).map((file) => file.id));
  const toggle = (id: number) => {
    const next = new Set(files);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setTicked(next);
  };

  const run = (send: boolean, after?: () => void) => {
    setProblem("");
    deliver.mutate(
      { files: send ? [...files] : [], note: send ? note.trim() : "", send },
      {
        onSuccess: () => {
          after?.();
          push({ level: "success", title: t("تم التسليم", "Delivered") });
        },
        onError: (error) => setProblem(taskProblem(error, t)),
      },
    );
  };

  return (
    <>
      <div className="note note--ok">
        <Icon name="user-check" />
        <div>
          <div className="note__where mono">
            {task.handover.by ?? "—"} · {task.handover.at ? (lang === "ar" ? task.handover.at.ar : task.handover.at.en) : ""}
          </div>
          <div>{t("التاسك مستلمة — تقدر تبعتها للعميل.", "Taken over — you can send it to the client.")}</div>
        </div>
      </div>

      <div className="deliver" id="deliverBox">
        <div className="label">{t("الملفات اللي هتتبعت للعميل", "Files to send to the client")}</div>
        {info.files.length > 0 ? (
          <div className="picker">
            {info.files.map((file) => (
              <label className="picker__row" key={file.id}>
                <input type="checkbox" name="attachments" checked={files.has(file.id)} onChange={() => toggle(file.id)} />
                <span className="grow">{file.name}</span>
                <small className="muted nowrap">
                  {file.sender ?? "—"} · {file.size}
                </small>
              </label>
            ))}
          </div>
        ) : (
          <div className="muted" style={{ fontSize: ".8rem" }}>
            {t("مفيش ملفات في الشات — هيتبعت النص بس.", "No files in the chat — only the message will be sent.")}
          </div>
        )}

        <textarea
          className="input mt"
          rows={2}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder={t("رسالة للعميل (اختياري)", "Message to the client (optional)")}
          aria-label={t("رسالة للعميل", "Message to the client")}
        />

        <div className="row row--tight mt" style={{ fontSize: ".78rem" }}>
          {info.reachable ? (
            <>
              <span className="badge badge--ok">
                <Icon name="send" size="sm" />
                {info.channel === "whatsapp" ? "WhatsApp" : "Email"}
              </span>
              <span className="muted">{t("هيتبعت على قناة العميل", "Sent over the channel the client used")}</span>
            </>
          ) : (
            <span className="badge badge--dead">
              <Icon name="alert" size="sm" />
              <span>{t("مفيش رقم ولا إيميل للعميل", "No phone or e-mail on file")}</span>
            </span>
          )}
        </div>

        <button
          className="btn btn--ok btn--block mt"
          type="button"
          disabled={!info.reachable || deliver.isPending}
          onClick={() => run(true)}
        >
          <Icon name="upload" size="sm" />
          <span>{deliver.isPending ? t("بيتبعت…", "Sending…") : t("ابعت للعميل وسلّم", "Send to client & close")}</span>
        </button>
        <button className="btn btn--ghost btn--block btn--sm mt" type="button" disabled={deliver.isPending} onClick={() => setClosing(true)}>
          {t("قفل التاسك من غير إرسال", "Close without sending")}
        </button>
        <Problem text={problem} />
      </div>

      {closing && (
        <Confirm
          title={t("تقفل التاسك من غير ما تبعت للعميل؟", "Close the task without sending anything to the client?")}
          yes={t("اقفلها", "Close it")}
          danger
          busy={deliver.isPending}
          problem={problem}
          onNo={() => setClosing(false)}
          onYes={() => run(false, () => setClosing(false))}
        />
      )}
    </>
  );
}

/** The client's date, from "in how long" the way the client said it. Empty boxes leave it; zeros clear it. */
export function DeadlineBox({ task }: { task: OpsTask }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const save = useSaveDeadline(task.code);
  const [values, setValues] = useState({ days: "", hours: "", minutes: "" });
  const [problem, setProblem] = useState("");
  const typed = values.days.trim() !== "" || values.hours.trim() !== "" || values.minutes.trim() !== "";

  return (
    <form
      className="mt"
      onSubmit={(event) => {
        event.preventDefault();
        if (!typed || save.isPending) return;
        setProblem("");
        save.mutate(values, {
          onSuccess: () => {
            setValues({ days: "", hours: "", minutes: "" });
            push({ level: "success", title: t("الديدلاين اتحفظ", "Deadline saved") });
          },
          onError: (error) => setProblem(taskProblem(error, t)),
        });
      }}
    >
      <label className="label">{t("الديدلاين (من العميل)", "Deadline (from the client)")}</label>
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
              onChange={(event) => setValues({ ...values, [name]: event.target.value })}
            />
            <span className="dur__unit">{unit}</span>
          </label>
        ))}
      </div>
      <small className="muted">
        {t("سيبها فاضية يعني سيب الديدلاين زي ما هو. أصفار يعني من غير ديدلاين.", "Leave it empty to keep the deadline. Zeros mean no deadline.")}
      </small>
      <button className="btn btn--block btn--sm mt" type="submit" disabled={!typed || save.isPending}>
        {t("حفظ الديدلاين", "Save the deadline")}
      </button>
      <Problem text={problem} />
    </form>
  );
}

/** An admin who took the client's message opens the group with no operation in it: this is how one is added after. */
export function AddMemberBox({ task }: { task: OpsTask }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const add = useAddMember(task.code);
  const [person, setPerson] = useState<number | null>(null);
  const [problem, setProblem] = useState("");
  const chosen = person ?? task.group_candidates[0]?.id ?? null;
  if (!task.can.add_member || task.group_candidates.length === 0) return null;

  return (
    <form
      className="mt"
      onSubmit={(event) => {
        event.preventDefault();
        if (chosen === null || add.isPending) return;
        setProblem("");
        add.mutate(chosen, {
          onSuccess: () => push({ level: "success", title: t("اتضاف للجروب", "Added to the group") }),
          onError: (error) => setProblem(taskProblem(error, t)),
        });
      }}
    >
      <label className="label" htmlFor="member-select">
        {t("ضيف حد لجروب التاسك", "Add somebody to the task group")}
      </label>
      <div className="row row--tight">
        <select id="member-select" className="input grow" value={chosen ?? ""} onChange={(event) => setPerson(Number(event.target.value))}>
          {task.group_candidates.map((candidate) => (
            <option key={candidate.id} value={candidate.id}>
              {candidate.name} — {candidate.role}
            </option>
          ))}
        </select>
        <button className="btn" type="submit" disabled={add.isPending}>
          {t("ضيف", "Add")}
        </button>
      </div>
      <Problem text={problem} />
    </form>
  );
}

export function CancelButton({ task }: { task: OpsTask }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const cancel = useCancelTask(task.code);
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState("");
  if (!task.can.cancel) return null;

  return (
    <>
      <button
        className="btn btn--danger btn--block mt"
        type="button"
        onClick={() => {
          setProblem("");
          setAsking(true);
        }}
      >
        <Icon name="x" size="sm" />
        <span>{t("إلغاء التاسك", "Cancel task")}</span>
      </button>
      {asking && (
        <Confirm
          title={t("إلغاء التاسك؟", "Cancel this task?")}
          yes={t("ألغي التاسك", "Cancel the task")}
          danger
          busy={cancel.isPending}
          problem={problem}
          onNo={() => setAsking(false)}
          onYes={() =>
            cancel.mutate(undefined, {
              onSuccess: () => {
                setAsking(false);
                push({ level: "warning", title: t("التاسك اتلغت", "Task cancelled") });
              },
              onError: (error) => setProblem(taskProblem(error, t)),
            })
          }
        />
      )}
    </>
  );
}
