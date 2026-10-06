import { Loading } from "../components/Loading";
import { Navigate } from "react-router";
import { useMe } from "../api/queries";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";
import { OperationTaskPage } from "./OperationTaskPage";
import { TaskPage } from "./TaskPage";

/**
 * `/tasks/<code>` is two pages: the translator's (their own job, with the upload box and the Finished button) and the
 * operation's (where it stands, and what can be done with it next - which for the task's team leader means giving it to a
 * translator, answering a request for more time and finishing the review). Who the person is decides; the server decides
 * again what each may read and do. The admin gets the operation's - the translator's page is theirs only to look at.
 */
export function TaskRoute() {
  const { t } = usePreferences();
  const me = useMe();

  if (!me.data) {
    return (
      <div className="card">
        {me.isError ? (
          <div className="empty" role="alert">
            <Icon name="alert" size="xl" />
            <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
          </div>
        ) : (
          <Loading className="empty" />
        )}
      </div>
    );
  }
  const { role, is_admin: admin } = me.data.user;
  if (role === "translator" && !admin) return <TaskPage />;
  if (role === "operation" || role === "team_lead" || role === "support" || admin) return <OperationTaskPage />;
  return <Navigate to="/" replace />;
}
