import { Loading } from "../components/Loading";
import { useMarkRead, useNotifications } from "../api/queries";
import { Icon } from "../components/Icon";
import { NotificationCard } from "../components/NotificationCard";
import { usePreferences } from "../i18n/Preferences";

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
          <Loading className="empty" />
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
          <NotificationCard
            key={item.id}
            item={item}
            onOpen={(id) => markRead.mutate([id])}
            onRead={(id) => markRead.mutate([id])}
            busy={markRead.isPending}
          />
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
