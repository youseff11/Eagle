import { useState, type FormEvent } from "react";
import { Link, Navigate } from "react-router";
import { formErrors } from "../api/adminActions";
import { useSaveRecruitSettings } from "../api/hrActions";
import { useHrRecruitSettings, useMe } from "../api/queries";
import type { FormErrors } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { useHrAllowed } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/**
 * The module's own rules: the words scrubbed from anything an anonymous candidate reads (a filter in the code, not an instruction),
 * the bot, the probation length, and the line it listens on. The sample shows what the filter makes of a message that names the
 * company - the proof it works, beside the list that drives it.
 */
export function HrRecruitmentSettingsPage() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const { me, allowed } = useHrAllowed();
  const user = useMe().data?.user;
  const query = useHrRecruitSettings(allowed);
  const save = useSaveRecruitSettings();
  const data = query.data;
  const edits = useFormEdits(data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setProblem("");
    save.mutate(edits.edited, {
      onSuccess: () => {
        edits.reset();
        push({ level: "success", title: t("اتحفظ", "Saved") });
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found) setErrors(found);
        else setProblem(refusal(error, t("حصلت مشكلة، ماتحفظش.", "Something went wrong, nothing was saved.")));
      },
    });
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("إعدادات التوظيف", "Recruitment settings")}</h1>
      </div>

      {!data.privacy_armed && (
        <div className="note note--high" data-note="privacy">
          <Icon name="alert" />
          <div>
            {t(
              "مفيش كلمات متسجلة للإخفاء — اكتب اسم الشركة والدومين والعنوان تحت.",
              "Nothing is configured to redact, so the company name can reach a candidate. Add the names, domain and address below.",
            )}
          </div>
        </div>
      )}

      <div className="grid grid--main">
        <form onSubmit={submit}>
          <div className="card">
            <div className="card__head">
              <Icon name="shield" />
              <h3>{t("إخفاء هوية الشركة والبوت", "The identity rule and the bot")}</h3>
            </div>
            <div className="note note--info">
              <Icon name="info" />
              <div>
                {t(
                  "الكلمات دي بتتشال من أي رسالة بتروح لمرشح مجهول الجهة — من البوت ومن الـHR. مش تعليمات، ده فلتر في الكود.",
                  "These are stripped from anything sent to a candidate who is still anonymous, whether the bot wrote it or HR did. Not an instruction: a filter in the code.",
                )}
              </div>
            </div>
            <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="recruit" />
            {data.privacy_armed && (
              <div className="note note--ok" data-note="sample">
                <Icon name="check-circle" />
                <div>
                  {t("مثال على النتيجة:", "What that looks like:")} <span className="mono">{data.sample}</span>
                </div>
              </div>
            )}
            {problem && (
              <div className="note note--high" role="alert">
                <Icon name="alert" />
                <div>{problem}</div>
              </div>
            )}
          </div>
          <button className="btn btn--primary" type="submit" disabled={save.isPending || !edits.dirty}>
            <Icon name="check" size="sm" />
            <span>{t("احفظ", "Save")}</span>
          </button>
        </form>

        <div className="sticky-side">
          <div className="card card--flat" data-card="line">
            <div className="card__head">
              <Icon name="phone" />
              <h3>{t("رقم التوظيف", "The recruitment line")}</h3>
            </div>
            <div className="kv">
              <span>{t("الرقم", "Number")}</span>
              <b className="mono" dir="ltr">
                {data.line.number || "—"}
              </b>
            </div>
            <div className="kv">
              <span>Phone number ID</span>
              <b>{data.line.phone_number_id ? t("متسجل", "Set") : "—"}</b>
            </div>
            {!data.line.phone_number_id && (
              <div className="note note--warn mt" data-note="no-id">
                <Icon name="alert" />
                <div>
                  {t("من غير الرقم ده البوت مش هيستقبل حاجة — ", "Without this, the bot receives nothing. ")}
                  {user?.is_admin ? <Link to="/admin/settings">{t("حطه من الإعدادات", "Set it on the settings page")}</Link> : t("الأدمن بيحطه من الإعدادات.", "The admin sets it on the settings page.")}
                </div>
              </div>
            )}
            <small className="muted">
              {t(
                "نفس الويب هوك ونفس التوكن بيخدموا الرقمين — الـID ده هو اللي بيفرّق بينهم.",
                "One webhook and one token serve both lines. This ID is the only thing that separates them, so a client and a candidate can never be confused.",
              )}
            </small>
          </div>
        </div>
      </div>
    </>
  );
}
