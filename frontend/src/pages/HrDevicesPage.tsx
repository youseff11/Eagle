import { Navigate } from "react-router";
import { useDecideDevice } from "../api/hrActions";
import { useHrDevices } from "../api/queries";
import { Waiting, refusal } from "../components/accounts/shared";
import { useHrAllowed, useStamp } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/**
 * The browsers people punch from. A token is a random number the browser keeps; it says nothing about the machine or its owner,
 * and a page here shows only the start of it. Somebody's first browser is approved on its own, so a new joiner is never locked
 * out; a later one waits here for HR to recognise it.
 */
export function HrDevicesPage() {
  const { t } = usePreferences();
  const stamp = useStamp();
  const { push } = useToasts();
  const { me, allowed } = useHrAllowed();
  const query = useHrDevices(allowed);
  const decide = useDecideDevice();
  const data = query.data;

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const act = (id: number, action: "approve" | "reject") =>
    decide.mutate({ id, action }, { onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) }) });

  return (
    <>
      <div className="page-head">
        <h1>{t("أجهزة الحضور", "Attendance devices")}</h1>
      </div>

      <div className="note note--info">
        <Icon name="shield" />
        <div>
          {t(
            "البصمة دي رقم عشوائي المتصفح بيحتفظ بيه — مش بيقول حاجة عن الجهاز ولا عن صاحبه. أول متصفح لأي موظف بيتعتمد تلقائي عشان الجديد ميتقفلش بره.",
            "The fingerprint is a random token the browser keeps - it says nothing about the machine or its owner. Somebody's very first browser is approved automatically, so a new joiner is never locked out.",
          )}
        </div>
      </div>

      <div className="card">
        <div className="card__head">
          <Icon name="user-check" />
          <h3>{t("مستنية موافقة", "Waiting for approval")}</h3>
        </div>
        <div className="table-wrap">
          <table className="table" data-table="pending">
            <thead>
              <tr>
                <th>{t("الموظف", "Employee")}</th>
                <th>{t("البصمة", "Fingerprint")}</th>
                <th>{t("المتصفح", "Browser")}</th>
                <th>{t("أول ظهور", "First seen")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.pending.map((device) => (
                <tr key={device.id} data-device={device.id}>
                  <td>{device.user}</td>
                  <td className="mono muted">{device.fingerprint}</td>
                  <td className="muted">{device.browser}</td>
                  <td className="mono">{stamp(device.first_seen)}</td>
                  <td>
                    <div className="row row--tight">
                      <button className="btn btn--ok btn--sm" type="button" disabled={decide.isPending} onClick={() => act(device.id, "approve")}>
                        <Icon name="check" size="sm" />
                        <span>{t("اعتمد", "Approve")}</span>
                      </button>
                      <button className="btn btn--danger btn--sm" type="button" disabled={decide.isPending} onClick={() => act(device.id, "reject")}>
                        <Icon name="x" size="sm" />
                        <span>{t("ارفض", "Reject")}</span>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {data.pending.length === 0 && (
                <tr>
                  <td colSpan={5} className="empty">
                    {t("مفيش أجهزة مستنية.", "Nothing waiting.")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card__head">
          <Icon name="history" />
          <h3>{t("اتقرر فيها", "Decided")}</h3>
        </div>
        <div className="table-wrap">
          <table className="table" data-table="decided">
            <thead>
              <tr>
                <th>{t("الموظف", "Employee")}</th>
                <th>{t("البصمة", "Fingerprint")}</th>
                <th>{t("الحالة", "Status")}</th>
                <th>{t("مين", "By")}</th>
                <th>{t("آخر استخدام", "Last used")}</th>
              </tr>
            </thead>
            <tbody>
              {data.decided.map((device) => (
                <tr key={device.id} data-device={device.id}>
                  <td>{device.user}</td>
                  <td className="mono muted">{device.name}</td>
                  <td>
                    {device.status === "approved" ? (
                      <span className="badge badge--ok">{t("معتمد", "Approved")}</span>
                    ) : (
                      <span className="badge badge--dead">{t("مرفوض", "Rejected")}</span>
                    )}
                  </td>
                  <td>{device.decided_by ?? "—"}</td>
                  <td className="mono muted">{stamp(device.last_seen)}</td>
                </tr>
              ))}
              {data.decided.length === 0 && (
                <tr>
                  <td colSpan={5} className="empty">
                    {t("لسه مفيش.", "Nothing yet.")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
