import { Link } from "react-router";
import type { ChatKind, ChatRow } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { clockText } from "../../lib/clock";
import { useOutboxProblems } from "../../lib/outbox";
import { Avatar } from "../Avatar";
import { Icon } from "../Icon";
import { Ticks } from "./Ticks";

/** The tabs a role may have and what they are called (the server's `chat_tabs`). */
export const TAB_LABELS: Record<ChatKind, [string, string]> = {
  clients: ["العملاء", "Clients"],
  groups: ["الجروبات", "Groups"],
  staff: ["الزمايل", "Colleagues"],
};

function RowAvatar({ row }: { row: ChatRow }) {
  if (row.group) {
    return (
      <span className="avatar avatar--group">
        <Icon name="users" size="sm" />
      </span>
    );
  }
  if (row.staff) return <Avatar src={row.avatar} initials={row.initials ?? ""} tone="staff" />;
  // "CL-0001": the number is what tells clients apart at a glance.
  return <span className="avatar avatar--brand">{row.code.slice(3)}</span>;
}

function Row({ row, kind, active, problem }: { row: ChatRow; kind: ChatKind; active: boolean; problem: boolean }) {
  const { t, lang } = usePreferences();
  const monospaced = !(row.staff || row.team);
  return (
    <Link
      className={`cthread${active ? " is-active" : ""}${row.unread > 0 && !active ? " has-unread" : ""}`}
      to={`/chats/${row.code}?type=${kind}`}
      data-code={row.code}
    >
      <RowAvatar row={row} />
      <span className="cthread__body">
        <span className="cthread__top">
          <b className={monospaced ? "mono" : undefined}>{row.label}</b>
          {row.reaches_client && <span className="chip chip--sm cthread__tag">{t("مع العميل", "With the client")}</span>}
          {problem && (
            <span className="cthread__problem" title={t("فيه رسالة ماتبعتتش", "A message did not go")}>
              <Icon name="alert" size="sm" />
            </span>
          )}
          {row.time && <span className="muted mono cthread__time">{clockText(row.time, lang)}</span>}
        </span>
        <span className="cthread__line">
          <span className="cthread__snippet">
            {row.outgoing && <Ticks status={row.status} receipt={row.receipt} mine />}
            {row.text}
          </span>
          {row.unread > 0 && !active && (
            <span className="cthread__unread" title={t("رسايل مااتقرتش", "Unread messages")}>
              {row.unread > 99 ? "99+" : row.unread}
            </span>
          )}
        </span>
      </span>
    </Link>
  );
}

/** One of the three lists, with its search box and the tabs this role has. */
export function ChatList({
  kinds,
  kind,
  onKind,
  query,
  onQuery,
  rows,
  state,
  activeCode,
  onNewGroup,
}: {
  kinds: ChatKind[];
  kind: ChatKind;
  onKind: (kind: ChatKind) => void;
  query: string;
  onQuery: (query: string) => void;
  rows: ChatRow[] | undefined;
  state: "loading" | "error" | "ready";
  activeCode: string | undefined;
  /** Open the dialog for a new work group: given only to somebody who may open one, and drawn in the groups list. */
  onNewGroup?: () => void;
}) {
  const { t } = usePreferences();
  const problems = useOutboxProblems();
  return (
    <aside className="cchat__list">
      <div className="cchat__search">
        <div className="field-icon" style={{ margin: 0 }}>
          <Icon name="search" className="ic--lead" />
          <input
            className="input"
            type="search"
            value={query}
            onChange={(event) => onQuery(event.target.value)}
            placeholder={
              kind === "staff"
                ? t("دوّر على اسم موظف…", "Search a colleague…")
                : t("دوّر على كود عميل أو اسم جروب…", "Search a client code or group…")
            }
            aria-label={t("بحث", "Search")}
          />
        </div>
      </div>

      <div className="cchat__filter" role="tablist">
        {kinds.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={key === kind}
            className={`cchat__pill${key === kind ? " is-active" : ""}`}
            onClick={() => onKind(key)}
          >
            {t(...TAB_LABELS[key])}
          </button>
        ))}
      </div>

      {kind === "groups" && onNewGroup && (
        <div className="cchat__new">
          <button type="button" className="btn btn--sm btn--primary grow" onClick={onNewGroup}>
            <Icon name="users" size="sm" />
            <span>{t("جروب شغل", "Work group")}</span>
          </button>
        </div>
      )}

      <div className="cchat__threads">
        {state === "loading" && (
          <div className="empty">
            <Icon name="refresh" size="xl" />
            <span>{t("بيحمّل...", "Loading...")}</span>
          </div>
        )}
        {state === "error" && (
          <div className="empty" role="alert">
            <Icon name="alert" size="xl" />
            <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
          </div>
        )}
        {state === "ready" && rows && rows.length === 0 && (
          <div className="empty">
            <Icon name="message" size="xl" />
            <span>
              {kind === "staff" ? t("مفيش زمايل هنا.", "Nobody here yet.") : t("مفيش محادثات لسه.", "No conversations yet.")}
            </span>
          </div>
        )}
        {rows?.map((row) => (
          <Row key={row.code} row={row} kind={kind} active={row.code === activeCode} problem={problems.includes(row.code)} />
        ))}
      </div>
    </aside>
  );
}
