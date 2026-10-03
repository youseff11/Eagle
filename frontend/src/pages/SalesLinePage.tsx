import { useState, type FormEvent } from "react";
import { Navigate } from "react-router";
import { ApiError } from "../api/client";
import { useSaveLine } from "../api/opsActions";
import { useMe, useSalesLine } from "../api/queries";
import type { SalesLine } from "../api/types";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";

function LineForm({ line }: { line: SalesLine }) {
  const { t } = usePreferences();
  const save = useSaveLine();
  const [phoneId, setPhoneId] = useState(line.values.wa_phone_number_id);
  const [display, setDisplay] = useState(line.values.wa_display_number);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const owner = line.is_owner;

  // The refusal names the box and says why, in the words the classic page uses. Anything else is not a refusal of the number.
  const problem = (failure: unknown): string => {
    if (failure instanceof ApiError) {
      const fields = (failure.payload as { fields?: { wa_phone_number_id?: string } } | null)?.fields;
      if (fields?.wa_phone_number_id) return fields.wa_phone_number_id;
      if (failure.status === 400) return t("القيمة مش مظبوطة.", "That value is not right.");
    }
    return t("مقدرتش أحفظ. جرّب تاني.", "Could not save. Try again.");
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!owner || save.isPending) return;
    setSaved(false);
    setError("");
    save.mutate(
      { wa_phone_number_id: phoneId.trim(), wa_display_number: display.trim() },
      {
        onSuccess: (answer) => {
          setPhoneId(answer.values.wa_phone_number_id);
          setDisplay(answer.values.wa_display_number);
          setSaved(true);
        },
        onError: (failure) => setError(problem(failure)),
      },
    );
  };

  return (
    <>
      {saved && (
        <div className="note note--ok" role="status" style={{ marginBottom: 14 }}>
          <Icon name="check-circle" />
          <div>{t("اتحفظ. أي عميل يكلمك على الرقم أو الإيميل ده هيظهر عندك انت بس.", "Saved. Clients who write to this number or address show up for you only.")}</div>
        </div>
      )}
      {!owner && (
        <div className="note note--info" style={{ marginBottom: 14 }}>
          <Icon name="info" />
          <div>{t("الصفحة دي بيملاها الـSales لنفسه. تقدر تشوفها عشان تعرف هي بتطلب إيه.", "Each Sales person fills this in for themselves. You can read what it asks for.")}</div>
        </div>
      )}

      <form className="grid grid--main" onSubmit={submit}>
        <div className="card">
          <div className="card__head">
            <Icon name="phone" />
            <h3>{t("رقم الواتساب", "WhatsApp number")}</h3>
          </div>
          <div className="field">
            <label htmlFor="waId">Phone number ID</label>
            <input
              className="input mono"
              id="waId"
              name="wa_phone_number_id"
              dir="ltr"
              inputMode="numeric"
              maxLength={40}
              value={phoneId}
              disabled={!owner}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? "waIdProblem" : undefined}
              onChange={(event) => setPhoneId(event.target.value)}
            />
            {error && (
              <small className="deadline--late" id="waIdProblem" role="alert">
                {error}
              </small>
            )}
          </div>
          <div className="field">
            <label htmlFor="waNum">{t("الرقم زي ما العميل بيكتبه (للعرض بس)", "The number as clients dial it (display only)")}</label>
            <input
              className="input mono"
              id="waNum"
              name="wa_display_number"
              dir="ltr"
              maxLength={30}
              value={display}
              placeholder="+20 1…"
              disabled={!owner}
              onChange={(event) => setDisplay(event.target.value)}
            />
          </div>
          <div className="note note--info">
            <Icon name="info" />
            <div>
              <div>
                {t(
                  "الرقم لازم يبقى متضاف على حساب الواتساب بيزنس بتاع الشركة (WhatsApp Manager ← Phone numbers ← Add). الـPhone number ID بيظهر جنبه هناك.",
                  "The number has to be added to the company's WhatsApp Business account (WhatsApp Manager > Phone numbers > Add). Its Phone number ID is shown next to it there.",
                )}
              </div>
              <div className="muted">
                {t(
                  "رقم متربط بالـCloud API مينفعش يشتغل على تطبيق واتساب العادي على الموبايل.",
                  "A number on the Cloud API cannot also run in the ordinary WhatsApp app on a phone.",
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card__head">
            <Icon name="mail" />
            <h3>{t("الإيميل", "E-mail")}</h3>
          </div>
          <div className="field">
            <label htmlFor="alias">{t("عنوانك على ميل الشركة", "Your address on the company mailbox")}</label>
            <input className="input mono" id="alias" dir="ltr" type="email" value={line.values.mail_alias} placeholder="—" disabled readOnly />
            <small className="muted">{t("الأدمن هو اللي بيحدد العنوان ده من صفحة الموظفين.", "The admin sets this address on the staff page.")}</small>
          </div>
          <div className="note note--info">
            <Icon name="info" />
            <div>
              <div>
                {t("العنوان ده لازم يتحوّل لميل الشركة", "This address must deliver into the company mailbox")}
                {line.company_mail && (
                  <>
                    {" ("}
                    <span className="mono">{line.company_mail}</span>
                    {")"}
                  </>
                )}
                {t(
                  " — عنوان فرعي (alias) أو تحويل. السيستم بيجيب الميل من هناك ويفرزه عليك حسب العنوان اللي اتبعت له.",
                  " - an alias or a forward. The system reads mail from there and sorts it to you by the address it was sent to.",
                )}
              </div>
              <div className="muted">
                {t(
                  "عشان الرد يطلع باسم عنوانك: في Gmail ضيفه من Settings ← Accounts ← Send mail as. من غيرها الرد بيطلع من ميل الشركة، بس رد العميل بيرجعلك برضه.",
                  "For replies to show your address: in Gmail add it under Settings > Accounts > Send mail as. Without it the reply leaves from the company address, but the client's answer still comes back to you.",
                )}
              </div>
            </div>
          </div>
        </div>

        {owner && (
          <div>
            <button className="btn btn--primary" type="submit" disabled={save.isPending}>
              <Icon name="check" size="sm" />
              <span>{t("حفظ", "Save")}</span>
            </button>
          </div>
        )}
      </form>
    </>
  );
}

/** A Sales person's own line: the WhatsApp number they put on the company's account, and the address the admin gave them. */
export function SalesLinePage() {
  const { t } = usePreferences();
  const me = useMe();
  // The same people the server lets in (`api_role_required`: the Sales, and the admin, who reads what it asks for).
  const allowed = me.data !== undefined && (me.data.user.role === "sales" || me.data.user.is_admin);
  const query = useSalesLine(allowed);

  if (me.data && !allowed) return <Navigate to="/" replace />;

  return (
    <>
      <div className="page-head">
        <h1>{t("رقمي وإيميلي", "My number & mail")}</h1>
      </div>
      {query.data ? (
        <LineForm line={query.data} />
      ) : query.isError ? (
        <div className="card empty" role="alert">
          <Icon name="alert" size="xl" />
          <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
        </div>
      ) : (
        <div className="card empty">
          <Icon name="refresh" size="xl" />
          <span>{t("بيحمّل...", "Loading...")}</span>
        </div>
      )}
    </>
  );
}
