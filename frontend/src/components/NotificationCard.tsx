import type { NotificationItem, NotificationLevel } from "../api/types";
import { usePreferences } from "../i18n/Preferences";
import { ROLE_LABELS } from "../lib/roles";
import { safeInternalPath } from "../lib/safeUrl";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";

/** The same four looks the classic page draws. */
const LEVEL_CLASS: Record<NotificationLevel, string> = {
  danger: "note--high",
  warning: "note--warn",
  success: "note--ok",
  info: "note--info",
};

const LEVEL_ICON: Record<NotificationLevel, string> = {
  danger: "alert",
  warning: "alert",
  success: "check-circle",
  info: "info",
};

/**
 * One notification: who it is from (when a person wrote it), when, the title, and the words under it - lines the sender typed
 * stay lines. `onOpen` and `onRead` are the buttons beside it («افتح» when it points at a page of this site, «مقروء» while it
 * is unread); a card given neither is only to be looked at (the preview of an announcement before it goes out).
 */
export function NotificationCard({
  item,
  onOpen,
  onRead,
  busy = false,
}: {
  item: NotificationItem;
  onOpen?: (id: number) => void;
  /** The button beside an unread notification: mark this one read, without opening it. */
  onRead?: (id: number) => void;
  busy?: boolean;
}) {
  const { t, lang } = usePreferences();
  const title = lang === "ar" ? item.title_ar : item.title_en;
  const body = lang === "ar" ? item.body_ar : item.body_en;
  // The server wrote the address; it is shown only if it is a path on this site.
  const href = safeInternalPath(item.url);
  const level = LEVEL_CLASS[item.level] ?? LEVEL_CLASS.info;
  const role = item.sender ? ROLE_LABELS[item.sender.role] : undefined;

  return (
    <div className={`note ${level} notice${item.read ? "" : " is-unread"}`} data-notification={item.id}>
      <Icon name={LEVEL_ICON[item.level] ?? "info"} />
      <div className="notice__main">
        <div className="notice__meta">
          {item.sender ? (
            <span className="notice__from" data-sender={item.sender.id}>
              <Avatar src={item.sender.avatar} initials={item.sender.initials} tone="staff" className="avatar--sm" />
              <strong className="notice__name">{item.sender.name}</strong>
              <span className="chip chip--sm">{role ? t(role[0], role[1]) : item.sender.role}</span>
            </span>
          ) : (
            <span />
          )}
          <span className="notice__time mono">
            {item.date} {item.created}
          </span>
        </div>
        <div className="notice__title">{title}</div>
        {body && <div className="notice__body">{body}</div>}
      </div>
      {(href && onOpen) || (!item.read && onRead) ? (
        <div className="notice__actions">
          {href && onOpen && (
            <a className="btn btn--sm" href={href} onClick={() => !item.read && onOpen(item.id)}>
              {t("افتح", "Open")}
            </a>
          )}
          {!item.read && onRead && (
            <button
              className="btn btn--sm"
              type="button"
              disabled={busy}
              title={t("علّمه مقروء", "Mark as read")}
              aria-label={`${t("علّمه مقروء", "Mark as read")}: ${title}`}
              onClick={() => onRead(item.id)}
            >
              <Icon name="check" size="sm" />
              {t("مقروء", "Read")}
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}
