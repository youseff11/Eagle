import { useMarkRead, useNotifications } from "../api/queries";
import type { NotificationItem, NotificationLevel } from "../api/types";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";
import { safeInternalPath } from "../lib/safeUrl";

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

function Row({ item, onOpen }: { item: NotificationItem; onOpen: (id: number) => void }) {
  const { t, lang } = usePreferences();
  const title = lang === "ar" ? item.title_ar : item.title_en;
  const body = lang === "ar" ? item.body_ar : item.body_en;
  // The server wrote the address; it is shown only if it is a path on this site.
  const href = safeInternalPath(item.url);
  const level = LEVEL_CLASS[item.level] ?? LEVEL_CLASS.info;

  return (
    <div className={`note ${level}${item.read ? "" : " is-unread"}`} data-notification={item.id}>
      <Icon name={LEVEL_ICON[item.level] ?? "info"} />
      <div className="grow">
        <div className="note__where mono">
          {item.date} {item.created}
        </div>
        <strong>{title}</strong>
        {body && <div className="muted">{body}</div>}
      </div>
      {href && (
        <a className="btn btn--sm" href={href} onClick={() => !item.read && onOpen(item.id)}>
          {t("افتح", "Open")}
        </a>
      )}
    </div>
  );
}

export function NotificationsPage() {
  const { t } = usePreferences();
  const query = useNotifications();
  const markRead = useMarkRead();

  const items = query.data?.pages.flatMap((page) => page.items) ?? [];
  const unread = query.data?.pages[0]?.unread ?? 0;

  return (
    <>
      <div className="page-head">
        <h1>{t("التنبيهات", "Notifications")}</h1>
        <div className="topbar__spacer" />
        <button
          className="btn btn--sm"
          type="button"
          disabled={unread === 0 || markRead.isPending}
          onClick={() => markRead.mutate(undefined)}
        >
          <Icon name="check-double" size="sm" />
          {t("علّم الكل مقروء", "Mark all read")}
        </button>
      </div>

      <div className="card">
        {query.isPending && (
          <div className="empty">
            <Icon name="refresh" size="xl" />
            <span>{t("بيحمّل...", "Loading...")}</span>
          </div>
        )}
        {query.isError && (
          <div className="empty" role="alert">
            <Icon name="alert" size="xl" />
            <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
          </div>
        )}
        {query.isSuccess && items.length === 0 && (
          <div className="empty">
            <Icon name="bell" size="xl" />
            <span>{t("مفيش تنبيهات.", "No notifications.")}</span>
          </div>
        )}
        {items.map((item) => (
          <Row key={item.id} item={item} onOpen={(id) => markRead.mutate([id])} />
        ))}
      </div>

      {query.hasNextPage && (
        <div className="list-more">
          <button
            className="btn"
            type="button"
            disabled={query.isFetchingNextPage}
            onClick={() => void query.fetchNextPage()}
          >
            {t("المزيد", "Load more")}
          </button>
        </div>
      )}
    </>
  );
}
