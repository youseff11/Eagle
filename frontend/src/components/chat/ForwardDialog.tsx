import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { useChatList, useForward } from "../../api/queries";
import type { ChatKind, ChatRow } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { Icon } from "../Icon";

/** The longest note that goes with a forward (the server cuts at the same number). */
const NOTE_LIMIT = 2000;

/** Why a forward did not happen, in the person's words: the server's own reason when it gave one. */
function problemText(error: unknown, t: (ar: string, en: string) => string): string {
  if (error instanceof ApiError) {
    if (error.detail) return error.detail;
    if (error.code === "empty") return t("اختار رسالة الأول.", "Pick a message first.");
    if (error.code === "csrf") return t("الجلسة محتاجة تتحدّث. حدّث الصفحة وجرّب تاني.", "The session needs a refresh. Reload the page and try again.");
    if (error.status < 500) return t("مقدرتش أحوّل.", "Could not forward.");
  }
  // Nothing came back, or the server failed: the messages may be there already.
  return t(
    "مش متأكدين إن التحويل تم. بص على المحادثة التانية قبل ما تحوّل تاني.",
    "We are not sure the forward went through. Look at the other conversation before forwarding again.",
  );
}

function kindText(row: ChatRow, t: (ar: string, en: string) => string): string {
  if (row.group) return row.reaches_client ? t("جروب مع العميل", "Group with the client") : t("جروب", "Group");
  if (row.staff) return t("زميل", "Colleague");
  return t("عميل · واتساب", "Client · WhatsApp");
}

/**
 * "Forward to": colleagues, groups and - for the operation and the admin - clients, from the lists the page already
 * has. Choosing where and sending are all this does; every rule about what may travel where (a client's own words
 * reach only people who may read them, a client's files never go to another client) is the server's, which says why
 * when it refuses. A forward that got there and then did not reach its end (a client's phone, a group's relay) is
 * not an error: the messages are in the other conversation, so it says so and offers to open it, never to send again.
 */
export function ForwardDialog({
  source,
  count,
  uids,
  kinds,
  onClose,
  onDone,
}: {
  /** The code of the conversation the messages come from. */
  source: string;
  count: number;
  uids: string[];
  /** The lists this person may forward to. */
  kinds: ChatKind[];
  onClose: () => void;
  /** The forward happened: the code of the conversation it went to, to open it - or `null` to stay. */
  onDone: (code: string | null) => void;
}) {
  const { t } = usePreferences();
  const staff = useChatList("staff", "", kinds.includes("staff"));
  const groups = useChatList("groups", "", kinds.includes("groups"));
  const clients = useChatList("clients", "", kinds.includes("clients"));
  const forward = useForward();
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState("");
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");
  const [arrived, setArrived] = useState<{ code: string; message: string } | null>(null);
  const pending = forward.isPending;

  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !pending) (arrived ? () => onDone(null) : onClose)();
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [pending, arrived, onClose, onDone]);

  const lists = [
    { kind: "staff", list: staff },
    { kind: "groups", list: groups },
    { kind: "clients", list: clients },
  ]
    .filter((entry) => kinds.includes(entry.kind as ChatKind))
    .map((entry) => entry.list);
  const loading = lists.some((list) => list.isPending);
  const failed = !loading && lists.some((list) => list.isError && !list.data);
  const needle = query.trim().toLowerCase();
  const rows = [staff.data, groups.data, clients.data]
    .flatMap((answer) => answer?.items ?? [])
    .filter((row) => row.code !== source)
    .filter((row) => !needle || row.label.toLowerCase().includes(needle) || row.code.toLowerCase().includes(needle));

  const send = () => {
    if (!chosen || pending) return;
    setProblem("");
    forward.mutate(
      { source, target: chosen, uids, note: note.trim() },
      {
        onSuccess: (answer) => {
          if (answer.delivered) onDone(answer.code);
          else setArrived({ code: answer.code, message: answer.message });
        },
        onError: (error) => setProblem(problemText(error, t)),
      },
    );
  };

  const title = t("تحويل لـ", "Forward to");
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !pending) (arrived ? () => onDone(null) : onClose)();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="forward-title" style={{ textAlign: "start" }}>
        <div className="row row--tight">
          <Icon name="forward" />
          <div className="modal__title" id="forward-title">
            {title}
          </div>
          <span className="chip chip--sm mono" title={t("عدد الرسايل", "Messages")}>
            {count}
          </span>
          <div className="grow" />
          <button
            type="button"
            className="icon-btn"
            onClick={arrived ? () => onDone(null) : onClose}
            disabled={pending}
            title={t("إغلاق", "Close")}
            aria-label={t("إغلاق", "Close")}
          >
            <Icon name="x" />
          </button>
        </div>

        {arrived ? (
          <>
            <div className="note note--warn" role="alert">
              <Icon name="alert" />
              <div>{arrived.message || t("اتحوّلت، بس مروحتش لآخرها.", "Forwarded, but it did not reach its end.")}</div>
            </div>
            <div className="row" style={{ marginTop: 14 }}>
              <div className="grow" />
              <button type="button" className="btn" onClick={() => onDone(null)}>
                {t("إغلاق", "Close")}
              </button>
              <button type="button" className="btn btn--primary" onClick={() => onDone(arrived.code)}>
                {t("افتح المحادثة", "Open the conversation")}
              </button>
            </div>
          </>
        ) : (
          <>
            <input
              className="input"
              type="search"
              autoComplete="off"
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("دوّر على زميل أو جروب أو كود عميل...", "Search a colleague, group or client code...")}
              aria-label={t("دوّر", "Search")}
            />
            <div className="fwd-list" role="radiogroup" aria-label={title}>
              {loading && <div className="muted">{t("بحمّل...", "Loading...")}</div>}
              {failed && (
                <div className="muted" role="alert">
                  {t("مش قادرين نجيب القايمة.", "Could not load the list.")}
                </div>
              )}
              {!loading && !failed && rows.length === 0 && <div className="muted">{t("مفيش نتايج.", "Nothing matches.")}</div>}
              {rows.map((row) => (
                <label className={`fwd-row${row.code === chosen ? " is-on" : ""}`} key={row.code}>
                  <input type="radio" name="forward-target" value={row.code} checked={row.code === chosen} onChange={() => setChosen(row.code)} />
                  <span className={`avatar ${row.group ? "avatar--group" : row.staff ? "avatar--staff" : "avatar--brand"}`}>
                    {row.group ? <Icon name="users" size="sm" /> : row.staff ? row.initials : row.code.slice(3)}
                  </span>
                  <span className="fwd-row__body">
                    <b>{row.label || row.code}</b>
                    <span className="muted">{kindText(row, t)}</span>
                  </span>
                </label>
              ))}
            </div>

            <p className="muted fwd-hint">
              {t(
                "كلام العميل بيتحول للأوبريشن والأدمن بس. لأي حد تاني بتتحول ملفاته من غير نصه.",
                "A client's own words reach operation and admin only. Anyone else gets the files without the text.",
              )}
            </p>

            <input
              className="input"
              value={note}
              maxLength={NOTE_LIMIT}
              onChange={(event) => setNote(event.target.value)}
              placeholder={t("كلمة مع التحويل (اختياري)", "Add a note (optional)")}
              aria-label={t("كلمة مع التحويل", "Note")}
            />

            <div className="row" style={{ marginTop: 14, alignItems: "center" }}>
              <div role="alert" style={{ color: "var(--danger, #e5484d)", fontSize: ".8rem" }}>
                {problem}
              </div>
              <div className="grow" />
              <button type="button" className="btn" onClick={onClose} disabled={pending}>
                {t("إلغاء", "Cancel")}
              </button>
              <button type="button" className="btn btn--primary" onClick={send} disabled={!chosen || pending}>
                <Icon name="send" size="sm" />
                <span>{pending ? t("بيتحوّل...", "Forwarding...") : t("ابعت", "Send")}</span>
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
