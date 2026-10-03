import { useState, type FormEvent } from "react";
import { Navigate } from "react-router";
import { formErrors, useSimulateSend } from "../api/adminActions";
import { useAdminSimulate, useMe } from "../api/queries";
import type { FormErrors } from "../api/types";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

const BLANK = { channel: "whatsapp", sender_identity: "", subject: "", body: "" };

/**
 * Simulate a client's message: the whole flow before WhatsApp or Gmail are connected. The message goes through the same
 * function a real one does, so a word about rates holds it back from the operation, and the operation is notified.
 */
export function AdminSimulatePage() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const me = useMe();
  const allowed = me.data !== undefined && me.data.user.is_admin;
  const query = useAdminSimulate(allowed);
  const send = useSimulateSend();
  const [values, setValues] = useState(BLANK);
  const [files, setFiles] = useState<File[]>([]);
  const [fileKey, setFileKey] = useState(0);
  const [errors, setErrors] = useState<FormErrors>({});
  const [failed, setFailed] = useState(false);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = query.data;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setFailed(false);
    send.mutate(
      { ...values, files },
      {
        onSuccess: (answer) => {
          push({ level: "success", title: answer.code });
          setValues({ ...BLANK, channel: values.channel });
          setFiles([]);
          setFileKey(fileKey + 1);
        },
        onError: (error) => {
          const found = formErrors(error);
          if (found) setErrors(found);
          else setFailed(true);
        },
      },
    );
  };
  const problems = (name: string) =>
    errors[name]?.length ? (
      <ul className="errorlist" role="alert">
        {errors[name]!.map((message, index) => (
          <li key={index}>{message}</li>
        ))}
      </ul>
    ) : null;

  return (
    <>
      <div className="page-head">
        <h1>{t("محاكاة رسالة عميل", "Simulate a client message")}</h1>
        <span className="page-head__sub">{t("تجرب بيها الفلو كله من غير ما تربط واتساب أو جيميل.", "Exercise the whole flow before WhatsApp or Gmail are connected.")}</span>
      </div>

      <div className="grid grid--main">
        <div className="card">
          <form onSubmit={submit}>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="sim-channel">{t("القناة", "Channel")}</label>
                <select id="sim-channel" className="input" value={values.channel} onChange={(event) => setValues({ ...values, channel: event.target.value })}>
                  {(data?.channels ?? [{ value: "whatsapp", label: "WhatsApp" }]).map((choice) => (
                    <option key={choice.value} value={choice.value}>
                      {choice.label}
                    </option>
                  ))}
                </select>
                {problems("channel")}
              </div>
              <div className="field">
                <label htmlFor="sim-sender">{t("رقم / إيميل العميل", "Client phone / email")}</label>
                <input
                  id="sim-sender"
                  className="input"
                  dir="ltr"
                  placeholder="+201000000000"
                  value={values.sender_identity}
                  onChange={(event) => setValues({ ...values, sender_identity: event.target.value })}
                />
                {problems("sender_identity")}
              </div>
            </div>
            <div className="field">
              <label htmlFor="sim-subject">{t("الموضوع", "Subject")}</label>
              <input id="sim-subject" className="input" value={values.subject} onChange={(event) => setValues({ ...values, subject: event.target.value })} />
              {problems("subject")}
            </div>
            <div className="field">
              <label htmlFor="sim-body">{t("نص الرسالة", "Message body")}</label>
              <textarea id="sim-body" className="input" rows={4} value={values.body} onChange={(event) => setValues({ ...values, body: event.target.value })} />
              {problems("body")}
            </div>
            <div className="field">
              <label htmlFor="sim-files">{t("مرفقات", "Attachments")}</label>
              <input key={fileKey} id="sim-files" className="input" type="file" multiple onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
              {problems("files")}
            </div>
            {failed && (
              <div className="note note--high" role="alert">
                <Icon name="alert" />
                <div>{t("حصلت مشكلة، الرسالة ماوصلتش.", "Something went wrong, the message did not arrive.")}</div>
              </div>
            )}
            <button className="btn btn--primary" type="submit" disabled={send.isPending}>
              <Icon name="send" size="sm" />
              <span>{t("ابعت", "Send")}</span>
            </button>
          </form>

          <div className="note note--warn mt">
            <Icon name="shield" />
            <div>{t("لو النص فيه كلمة rate أو ريت، الرسالة هتتحجب عن الأوبريشن وتظهر للأدمن بس.", "If the text contains rate the message is hidden from Operation and shown to the admin only.")}</div>
          </div>
        </div>

        <div className="sticky-side">
          <div className="card">
            <div className="card__head">
              <Icon name="inbox" />
              <h3>{t("آخر الرسايل", "Latest messages")}</h3>
            </div>
            <ul className="timeline">
              {(data?.recent ?? []).map((message) => (
                <li key={message.id} data-message={message.id}>
                  <span className="mono">{message.code}</span>
                  <span className="grow">{message.body}</span>
                  {message.blocked && <span className="badge badge--dead">{t("محجوبة", "Hidden")}</span>}
                </li>
              ))}
              {data && data.recent.length === 0 && <li className="muted">{t("مفيش.", "None.")}</li>}
            </ul>
          </div>
        </div>
      </div>
    </>
  );
}
