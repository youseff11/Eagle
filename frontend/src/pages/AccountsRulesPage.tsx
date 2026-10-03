import { useMemo, useState, type FormEvent } from "react";
import { Navigate } from "react-router";
import { useAddTier, useDeleteTier, useSaveRules } from "../api/accountsActions";
import { formErrors } from "../api/adminActions";
import { useAccountsRules, useMe } from "../api/queries";
import type { AccountsTier, FormErrors, FormField } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

function Tiers({ rows, onRemove, busy }: { rows: AccountsTier[]; onRemove: (id: number) => void; busy: boolean }) {
  const { t } = usePreferences();
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>{t("أكتر من", "Above")}</th>
            <th>{t("لحد", "Up to")}</th>
            <th>{t("بونص اليوم", "Day bonus")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((tier) => (
            <tr key={tier.id} data-tier={tier.id}>
              <td className="mono">{tier.min_words}</td>
              <td className="mono">{tier.max_words ?? "—"}</td>
              <td className="mono">{tier.bonus}</td>
              <td>
                <button className="btn btn--sm btn--ghost" type="button" disabled={busy} onClick={() => onRemove(tier.id)}>
                  {t("شيل", "Remove")}
                </button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={4} className="empty">
                {t("مفيش شرائح.", "No bands.")}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Every number the payroll runs on, as the admin's alone to change: the month and the day, the deductions, the bonuses,
 * attendance, overtime, alerts, leave and the performance weights, and the bands of the daily production bonus. Changing a
 * number never rewrites a month already run. The form decides what is valid (a target nobody could reach is refused).
 */
export function AccountsRulesPage() {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const me = useMe();
  const allowed = me.data !== undefined && me.data.user.is_admin;
  const query = useAccountsRules(allowed);
  const data = query.data;
  const edits = useFormEdits(data?.fields);
  const tierEdits = useFormEdits(data?.tier_form);
  const save = useSaveRules();
  const addTier = useAddTier();
  const removeTier = useDeleteTier();
  const [errors, setErrors] = useState<FormErrors>({});
  const [tierErrors, setTierErrors] = useState<FormErrors>({});
  const [failed, setFailed] = useState(false);
  const byName = useMemo(() => new Map((data?.fields ?? []).map((field) => [field.name, field])), [data]);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;
  const pick = (names: string[]) => names.map((name) => byName.get(name)).filter((field): field is FormField => field !== undefined);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setFailed(false);
    save.mutate(edits.edited, {
      onSuccess: () => {
        edits.reset();
        push({ level: "success", title: t("اتحفظ", "Saved") });
      },
      onError: (error) => {
        const found = formErrors(error);
        if (found) setErrors(found);
        else setFailed(true);
      },
    });
  };
  const submitTier = (event: FormEvent) => {
    event.preventDefault();
    setTierErrors({});
    addTier.mutate(tierEdits.edited, {
      onSuccess: () => tierEdits.reset(),
      onError: (error) => {
        const found = formErrors(error);
        if (found) setTierErrors(found);
        else push({ level: "danger", title: t("الشريحة مش مظبوطة.", "The band is not right.") });
      },
    });
  };
  const lone: FormErrors = Object.fromEntries(Object.entries(errors).filter(([name]) => name !== "__all__"));

  return (
    <>
      <div className="page-head">
        <h1>{t("قواعد حساب المستحقات", "Payroll rules")}</h1>
        <div className="page-head__sub">{t("كل رقم هنا بيتعدل من غير ما حد يفتح الكود.", "Every number here changes without touching the code.")}</div>
      </div>

      <div className="grid grid--main">
        <div>
          <form onSubmit={submit}>
            {errors.__all__ && (
              <ul className="errorlist" role="alert">
                {errors.__all__.map((message, index) => (
                  <li key={index}>{message}</li>
                ))}
              </ul>
            )}
            {data.sections.map((section) => (
              <div className="card" id={`r-${section.key}`} key={section.key} data-section={section.key}>
                <div className="card__head">
                  <Icon name={section.icon} />
                  <h3>{lang === "ar" ? section.ar : section.en}</h3>
                </div>
                {section.note_ar && (
                  <div className="note note--info">
                    <Icon name="info" />
                    <div>{lang === "ar" ? section.note_ar : section.note_en}</div>
                  </div>
                )}
                <DjangoForm fields={pick(section.fields)} edits={edits} errors={lone} prefix="rules" />
              </div>
            ))}
            {failed && (
              <div className="note note--high" role="alert">
                <Icon name="alert" />
                <div>{t("حصلت مشكلة، ماتحفظش حاجة.", "Something went wrong, nothing was saved.")}</div>
              </div>
            )}
            <button className="btn btn--primary" type="submit" disabled={save.isPending || !edits.dirty}>
              <Icon name="check" size="sm" />
              <span>{t("حفظ", "Save")}</span>
            </button>
          </form>

          <div className="card" id="r-bands">
            <div className="card__head">
              <Icon name="layers" />
              <h3>{t("شرائح بونص الإنتاج اليومي", "Daily production bonus bands")}</h3>
            </div>
            <div className="note note--info">
              <Icon name="info" />
              <div>
                {t(
                  "الشريحة مفتوحة من تحت ومقفولة من فوق: اليوم بياخد الشريحة لما الكلمات تكون أكتر من البداية ولحد النهاية. يعني الحد اليومي نفسه مش بونص — اللي فوقه هو البونص.",
                  "A band is open on the left and closed on the right: the day pays it when words are above the lower edge and up to the upper one. Hitting the floor itself pays nothing; beating it is what pays.",
                )}
              </div>
            </div>
            <h4>{t("اللغة الأساسية", "Primary language")}</h4>
            <div data-tiers="primary">
              <Tiers
                rows={data.tiers.primary}
                busy={removeTier.isPending}
                onRemove={(id) => removeTier.mutate(id, { onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) }) })}
              />
            </div>
            <h4 className="mt">{t("لغة غير أساسية", "Secondary language")}</h4>
            <div data-tiers="secondary">
              <Tiers
                rows={data.tiers.secondary}
                busy={removeTier.isPending}
                onRemove={(id) => removeTier.mutate(id, { onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) }) })}
              />
            </div>
            <form onSubmit={submitTier} className="mt">
              <DjangoForm fields={data.tier_form} edits={tierEdits} errors={tierErrors} prefix="tier" />
              <button className="btn" type="submit" disabled={addTier.isPending || !tierEdits.dirty}>
                <Icon name="plus" size="sm" />
                <span>{t("ضيف شريحة", "Add a band")}</span>
              </button>
            </form>
          </div>
        </div>

        <div className="sticky-side">
          <div className="card">
            <div className="card__head">
              <Icon name="target" />
              <h3>{t("اتأكد إن الأرقام متسقة", "Keep the numbers consistent")}</h3>
            </div>
            <div className="kv">
              <span>{t("أيام × الحد اليومي", "Days x daily floor")}</span>
              <span className="mono">
                {data.check.working_days} × {data.check.daily_target_words}
              </span>
            </div>
            <div className="kv">
              <span>{t("التارجت الشهري", "Monthly target")}</span>
              <span className="mono">{data.check.monthly_target_words}</span>
            </div>
            <div className="note note--warn">
              <Icon name="alert" />
              <div>
                {t(
                  "لو التارجت أكبر من أيام العمل × الحد اليومي، مفيش مترجم هيقدر يوصله مهما شغل.",
                  "If the target exceeds working days times the daily floor, nobody can reach it however hard they work.",
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
