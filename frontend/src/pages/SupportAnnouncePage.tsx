import { useState, type FormEvent } from "react";
import { Navigate } from "react-router";
import { ApiError } from "../api/client";
import { useAnnounce, useMe, useSendAnnouncement } from "../api/queries";
import type { NotificationItem } from "../api/types";
import { Confirm } from "../components/Confirm";
import { Icon } from "../components/Icon";
import { NotificationCard } from "../components/NotificationCard";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

const BLANK = { title: "", body: "", level: "info" as "info" | "warning", sound: false };

/**
 * Technical support tells everybody something: a notification to every active employee, when support wants to. What is typed
 * is drawn beside the box as the employees will see it (lines stay lines), it asks once before it sends (it reaches the whole
 * company and cannot be taken back), and it says how many it reached.
 */
export function SupportAnnouncePage() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const me = useMe();
  // The same people the server lets in (`api_role_required`: technical support, and the admin).
  const allowed = me.data !== undefined && (me.data.user.role === "support" || me.data.user.is_admin);
  const query = useAnnounce(allowed);
  const send = useSendAnnouncement();
  const [values, setValues] = useState(BLANK);
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState("");

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = query.data;
  const reach = data?.reach ?? 0;
  const titleMax = data?.limits.title ?? 200;
  const bodyMax = data?.limits.body ?? 1000;
  const user = me.data?.user;

  const reason = (error: unknown) => {
    const code = error instanceof ApiError ? error.code : "";
    if (code === "repeat") return t("نفس الإشعار اتبعت من أقل من دقيقة.", "The same announcement was sent less than a minute ago.");
    if (code === "empty") return t("اكتب عنوان للإشعار.", "Write a title for the announcement.");
    if (code === "too_long") return t("النص أطول من المسموح.", "The text is longer than allowed.");
    return t("حصلت مشكلة، الإشعار ماوصلش.", "Something went wrong, the announcement did not go out.");
  };

  const ask = (event: FormEvent) => {
    event.preventDefault();
    setProblem("");
    if (values.title.trim()) setAsking(true);
    else setProblem(reason(new ApiError(400, "empty")));
  };

  const confirm = () => {
    send.mutate(
      { title: values.title.trim(), body: values.body.trim(), level: values.level, sound: values.sound },
      {
        onSuccess: (answer) => {
          push({ level: "success", title: t(`اتبعت لـ ${answer.reached} موظف.`, `Sent to ${answer.reached} people.`) });
          setValues(BLANK);
          setAsking(false);
        },
        onError: (error) => {
          setProblem(reason(error));
          setAsking(false);
        },
      },
    );
  };

  // What the employees will see: the same card, from this person, marked unread.
  const preview: NotificationItem = {
    id: 0,
    level: values.level,
    title_ar: values.title.trim() || t("عنوان الإشعار", "Announcement title"),
    title_en: values.title.trim() || t("عنوان الإشعار", "Announcement title"),
    body_ar: values.body.trim(),
    body_en: values.body.trim(),
    url: "",
    sound: values.sound,
    created: t("دلوقتي", "now"),
    date: "",
    read: false,
    sender: user ? { id: user.id, name: user.short_name, initials: user.initials, avatar: user.avatar, role: user.role } : null,
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("إشعار لكل الموظفين", "Notify everyone")}</h1>
        <span className="page-head__sub">
          {t("بيوصل لكل موظف على الجرس، من غير ما تفتح شات.", "It reaches every employee's bell, without opening a chat.")}
        </span>
      </div>

      <div className="grid grid--main">
        <div className="card">
          <form onSubmit={ask}>
            <div className="field">
              <label htmlFor="ann-title">{t("العنوان", "Title")}</label>
              <input
                id="ann-title"
                className="input"
                maxLength={titleMax}
                placeholder={t("مثلًا: تحديث في النظام", "For example: A system update")}
                value={values.title}
                onChange={(event) => setValues({ ...values, title: event.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="ann-body">{t("التفاصيل (اختياري)", "Details (optional)")}</label>
              <textarea
                id="ann-body"
                className="input announce__body"
                rows={8}
                maxLength={bodyMax}
                placeholder={t("اكتب كل نقطة في سطر: اضغط Enter للسطر الجديد.", "Write each point on its own line: press Enter for a new line.")}
                value={values.body}
                onChange={(event) => setValues({ ...values, body: event.target.value })}
              />
              <small className="muted">
                {values.body.length} / {bodyMax}
              </small>
            </div>
            <div className="announce__options">
              <div className="field">
                <label htmlFor="ann-level">{t("النوع", "Kind")}</label>
                <select
                  id="ann-level"
                  className="input"
                  value={values.level}
                  onChange={(event) => setValues({ ...values, level: event.target.value === "warning" ? "warning" : "info" })}
                >
                  <option value="info">{t("معلومة", "Information")}</option>
                  <option value="warning">{t("تنبيه مهم", "Important")}</option>
                </select>
              </div>
              <label className="announce__sound" htmlFor="ann-sound">
                <input
                  id="ann-sound"
                  type="checkbox"
                  checked={values.sound}
                  onChange={(event) => setValues({ ...values, sound: event.target.checked })}
                />
                <span>{t("رنّة مع الإشعار", "Ring with it")}</span>
              </label>
            </div>
            {problem && (
              <div className="note note--high" role="alert">
                <Icon name="alert" />
                <div>{problem}</div>
              </div>
            )}
            <button className="btn btn--primary" type="submit" disabled={send.isPending}>
              <Icon name="bell" size="sm" />
              <span>{t("ابعت للكل", "Send to everyone")}</span>
            </button>
          </form>
        </div>

        <div className="sticky-side">
          <div className="card">
            <div className="card__head">
              <Icon name="eye" />
              <h3>{t("هيظهر كده للموظفين", "How it will look")}</h3>
            </div>
            <div data-preview="">
              <NotificationCard item={preview} />
            </div>
          </div>
          <div className="card mt">
            <div className="card__head">
              <Icon name="history" />
              <h3>{t("آخر الإشعارات", "Latest announcements")}</h3>
            </div>
            <ul className="timeline">
              {(data?.recent ?? []).map((row) => (
                <li key={row.id} data-announcement={row.id}>
                  <span className="grow">
                    <strong>{row.title}</strong>
                    {row.body && <div className="muted announce__recent">{row.body}</div>}
                    <small className="muted">
                      {t(row.at.ar, row.at.en)} · {row.by ?? "—"} · {row.reached}
                    </small>
                  </span>
                </li>
              ))}
              {data && data.recent.length === 0 && <li className="muted">{t("لسه مفيش.", "None yet.")}</li>}
            </ul>
          </div>
        </div>
      </div>

      {asking && (
        <Confirm
          title={t("تبعت الإشعار للكل؟", "Send this to everyone?")}
          icon="bell"
          yes={t("ابعت", "Send")}
          busy={send.isPending}
          problem={problem}
          body={
            <>
              <strong>{values.title.trim()}</strong>
              {values.body.trim() && <div className="notice__body">{values.body.trim()}</div>}
              <div className="muted" style={{ marginTop: 6 }}>
                {t(`هيوصل لـ ${reach} موظف ومينفعش يتسحب.`, `It reaches ${reach} people and cannot be taken back.`)}
              </div>
            </>
          }
          onYes={confirm}
          onNo={() => setAsking(false)}
        />
      )}
    </>
  );
}
