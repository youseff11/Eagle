import { useState, type FormEvent } from "react";
import { formErrors, useSaveUser } from "../../api/adminActions";
import type { AdminUser, FormErrors } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { DjangoForm, useFormEdits } from "../admin/DjangoForm";
import { Icon } from "../Icon";
import { useToasts } from "../Toasts";

/**
 * The admin's form for one person's account: name, role, leader, the mail address they receive for, the flags that say what they may
 * do. The form is the server's (`StaffEditForm`), so what it refuses comes back beside its box and nothing was saved.
 */
export function AccountCard({ id, data, onClose }: { id: number; data: AdminUser; onClose: () => void }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const save = useSaveUser(id);
  const edits = useFormEdits(data.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [failed, setFailed] = useState(false);

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

  return (
    <div className="card" data-card="account">
      <div className="card__head">
        <Icon name="lock" />
        <h3>{t("الحساب والصلاحيات", "Account and access")}</h3>
      </div>
      <form onSubmit={submit}>
        <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="staff" />
        {failed && (
          <div className="note note--high" role="alert">
            <Icon name="alert" />
            <div>{t("حصلت مشكلة، ماتحفظش.", "Something went wrong, nothing was saved.")}</div>
          </div>
        )}
        <div className="row row--tight">
          <button className="btn btn--primary" type="submit" disabled={save.isPending || !edits.dirty}>
            <Icon name="check" size="sm" />
            <span>{t("حفظ", "Save")}</span>
          </button>
          <button className="btn btn--ghost" type="button" onClick={onClose}>
            {t("قفل", "Close")}
          </button>
        </div>
      </form>
    </div>
  );
}
