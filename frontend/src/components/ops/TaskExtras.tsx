import { useState } from "react";
import { useAddRequirement, useSaveWords } from "../../api/opsActions";
import type { OpsTask } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { ROLE_LABELS } from "../../lib/roles";
import { safeInternalPath } from "../../lib/safeUrl";
import { taskProblem } from "../../lib/taskProblem";
import { Icon } from "../Icon";
import { pagesOf } from "../PartBox";
import { Requirements } from "./Requirements";
import { useToasts } from "../Toasts";

/** The number the accounts side reads as the translator's production. It is typed by a person, never by the translator. */
export function WordCountCard({ task }: { task: OpsTask }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const save = useSaveWords(task.code);
  const [typed, setTyped] = useState<string | null>(null);
  const [problem, setProblem] = useState("");
  const set = task.words.state === "confirmed";
  const value = typed ?? (task.words.value !== null ? String(task.words.value) : "");
  const valid = /^\d{1,8}$/.test(value.trim());

  return (
    <div className="card" id="wordCount">
      <div className="card__head">
        <Icon name="list-checks" />
        <h3>{t("عدد الكلمات", "Word count")}</h3>
        <div className="grow" />
        {set ? <span className="badge badge--ok">{t("متسجّل", "Set")}</span> : <span className="badge badge--dead">{t("لسه متكتبش", "Not set yet")}</span>}
      </div>
      <div className="kv">
        <strong>{t("اللي الحسابات بتاخده", "What payroll uses")}</strong>
        <strong className="mono">{set && task.words.value !== null ? task.words.value : "—"}</strong>
      </div>
      <form
        className="mt"
        onSubmit={(event) => {
          event.preventDefault();
          if (!valid || save.isPending) return;
          setProblem("");
          save.mutate(Number(value.trim()), {
            onSuccess: () => {
              setTyped(null);
              push({ level: "success", title: t("عدد الكلمات اتسجّل", "Word count saved") });
            },
            onError: (error) => setProblem(taskProblem(error, t)),
          });
        }}
      >
        <label className="label" htmlFor="wordsInput">
          {t("عدد الكلمات", "Words")}
        </label>
        <div className="row row--tight">
          <input
            className="input grow"
            id="wordsInput"
            type="number"
            min={0}
            dir="ltr"
            inputMode="numeric"
            placeholder="0"
            value={value}
            onChange={(event) => setTyped(event.target.value)}
          />
          <button className="btn btn--sm btn--primary" type="submit" disabled={!valid || save.isPending}>
            {t("حفظ", "Save")}
          </button>
        </div>
        {problem && (
          <div className="note note--high mt" role="alert">
            <Icon name="alert" />
            <div>{problem}</div>
          </div>
        )}
      </form>
    </div>
  );
}

/** What the client likes, dislikes and insists on - read by everybody on the job, added to here. */
export function RequirementsCard({ task }: { task: OpsTask }) {
  const { t } = usePreferences();
  const add = useAddRequirement(task.code);
  return (
    <div className="card">
      <div className="card__head">
        <Icon name="list-checks" />
        <h3>{t("متطلبات العميل", "Client requirements")}</h3>
        <div className="grow" />
        <span className="chip mono">{task.client_code}</span>
      </div>
      <Requirements requirements={task.requirements} add={add} />
    </div>
  );
}

/** What was sent to the client for this task, when, over what, and why a send failed. */
export function DeliveriesCard({ task }: { task: OpsTask }) {
  const { t, lang } = usePreferences();
  if (task.deliveries.length === 0) return null;
  return (
    <div className="card">
      <div className="card__head">
        <Icon name="upload" />
        <h3>{t("سجل التسليم", "Delivery log")}</h3>
      </div>
      {task.deliveries.map((delivery) => (
        <div className={`note ${delivery.status === "failed" ? "note--high" : delivery.status === "sent" ? "note--ok" : "note--warn"}`} key={delivery.id}>
          <Icon name={delivery.status === "sent" ? "check-circle" : delivery.status === "failed" ? "alert" : "info"} />
          <div>
            <div className="note__where mono">
              {delivery.at ? (lang === "ar" ? delivery.at.ar : delivery.at.en) : ""} · {delivery.channel === "whatsapp" ? "WhatsApp" : "Email"} · {delivery.files} · {delivery.by ?? "—"}
            </div>
            <div>{delivery.error || delivery.status}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

/** The client's own words and files on this task - the operation reads them, and nobody else on the job does. */
export function MessagesCard({ task }: { task: OpsTask }) {
  const { t, lang } = usePreferences();
  if (task.messages.length === 0) return null;
  return (
    <div className="card">
      <div className="card__head">
        <Icon name="inbox" />
        <h3>{t("رسايل العميل", "Client messages")}</h3>
      </div>
      {task.messages.map((message) => (
        <div className="note" key={message.id}>
          <Icon name={message.channel === "whatsapp" ? "phone" : "mail"} />
          <div>
            <div className="note__where mono">
              {message.channel === "whatsapp" ? "WhatsApp" : "Email"} · {message.at ? (lang === "ar" ? message.at.ar : message.at.en) : ""}
            </div>
            {message.body && <div>{message.body}</div>}
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
        </div>
      ))}
    </div>
  );
}

const HISTORY_BADGE: Record<string, [string, string, string]> = {
  accepted: ["badge--ok", "استلم", "Accepted"],
  expired: ["badge--dead", "مردش", "Expired"],
  declined: ["badge--dead", "رفض", "Declined"],
  pending: ["badge--wait", "مستني", "Pending"],
};

/** Who the task was handed to, when, and what they said. */
/**
 * Who translates what (07/10/2026): each translator on the task with the pair, the pages and the words the leader gave them, and
 * where they stand - an offer waiting for their yes, working, or handed in. Drawn for a task with a translator on it; the one with
 * several is the page that needs it most.
 */
export function PartsCard({ task }: { task: OpsTask }) {
  const { t, lang } = usePreferences();
  if (task.parts.length === 0) return null;
  const total = task.parts.reduce((sum, part) => sum + part.words, 0);
  const done = task.parts.filter((part) => part.done).length;
  return (
    <div className="card" data-card="parts">
      <div className="card__head">
        <Icon name="users" />
        <h3>{t("المترجمين على التاسك", "Translators on the task")}</h3>
        <span className="chip chip--sm">
          {done}/{task.parts.length}
        </span>
        {total > 0 && <span className="chip chip--sm mono">{total.toLocaleString("en")}</span>}
      </div>
      <ul className="timeline">
        {task.parts.map((part) => {
          const pages = pagesOf(part);
          const [tone, ar, en] = part.done
            ? ["badge--ok", "سلّم", "Handed in"]
            : part.status === "pending"
              ? ["badge--wait", "مستني الرد", "Waiting"]
              : ["badge--info", "شغال", "Working"];
          return (
            <li key={part.id} data-part-row={part.id}>
              <span className="avatar avatar--sm">{part.initials}</span>
              <div className="grow">
                <div>{part.name}</div>
                <small className="muted mono">
                  {[
                    part.source_lang || part.target_lang ? `${part.source_lang || "—"} → ${part.target_lang || "—"}` : "",
                    part.words ? `${part.words.toLocaleString("en")} ${t("كلمة", "words")}` : "",
                    pages ? `${t("صفحات", "pages")} ${pages}` : "",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </small>
                {part.done && part.done_at && <small className="muted mono"> · {lang === "ar" ? part.done_at.ar : part.done_at.en}</small>}
              </div>
              <span className={`badge ${tone}`}>
                {t(ar, en)}
                {part.status === "pending" && part.seconds_left !== null && <span className="mono"> {part.seconds_left}s</span>}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function HistoryCard({ task }: { task: OpsTask }) {
  const { t, lang } = usePreferences();
  return (
    <div className="card">
      <div className="card__head">
        <Icon name="history" />
        <h3>{t("سجل التوزيع", "Assignment history")}</h3>
      </div>
      <ul className="timeline">
        {task.history.map((row) => {
          const [tone, ar, en] = HISTORY_BADGE[row.status] ?? ["", "ملغي", "Cancelled"];
          return (
            <li key={row.id}>
              <span className="avatar avatar--sm">{row.initials}</span>
              <div className="grow">
                <div>
                  {row.name} <span className="chip">{ROLE_LABELS[row.role]?.[lang === "ar" ? 0 : 1] ?? row.role}</span>
                </div>
                <small className="muted mono">{row.at ? (lang === "ar" ? row.at.ar : row.at.en) : ""}</small>
              </div>
              <span className={`badge ${tone}`}>{t(ar, en)}</span>
            </li>
          );
        })}
        {task.history.length === 0 && <li className="muted">{t("لسه مفيش توزيع.", "Not assigned yet.")}</li>}
      </ul>
    </div>
  );
}
