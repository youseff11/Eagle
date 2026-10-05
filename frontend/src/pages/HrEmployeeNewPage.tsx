import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router";
import { formErrors, useCreateUser } from "../api/adminActions";
import { useAdminUserNew, useMe } from "../api/queries";
import type { FormErrors } from "../api/types";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { Icon } from "../components/Icon";
import { usePreferences } from "../i18n/Preferences";

/** A new person, the admin's. The password is typed here, goes in the one request that makes them, and is read back by nobody. */
export function HrEmployeeNewPage() {
  const { t } = usePreferences();
  const navigate = useNavigate();
  const me = useMe();
  const allowed = me.data !== undefined && me.data.user.is_admin;
  const query = useAdminUserNew(allowed);
  const create = useCreateUser();
  const edits = useFormEdits(query.data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [failed, setFailed] = useState(false);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = query.data;
  if (!data) {
    return query.isError ? (
      <div className="card empty" role="alert">
        <Icon name="alert" size="xl" />
        <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
      </div>
    ) : (
      <div className="card empty">
        <Icon name="refresh" size="xl" />
        <span>{t("بيحمّل...", "Loading...")}</span>
      </div>
    );
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setFailed(false);
    create.mutate(edits.edited, {
      onSuccess: (answer) => {
        // The password the request carried is not kept in its state once it is over.
        create.reset();
        navigate(`/hr/employees/${answer.id}`);
      },
      onError: (error) => {
        create.reset();
        const found = formErrors(error);
        if (found) setErrors(found);
        else setFailed(true);
      },
    });
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("موظف جديد", "New staff member")}</h1>
        <div className="grow" />
        <Link className="btn btn--sm" to="/hr/employees">
          {t("كل الموظفين", "All staff")}
        </Link>
      </div>
      <div className="card">
        <form onSubmit={submit}>
          <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="new" />
          {failed && (
            <div className="note note--high" role="alert">
              <Icon name="alert" />
              <div>{t("حصلت مشكلة، ماتعملش.", "Something went wrong, nobody was made.")}</div>
            </div>
          )}
          <button className="btn btn--primary" type="submit" disabled={create.isPending}>
            <Icon name="check" size="sm" />
            <span>{t("حفظ", "Save")}</span>
          </button>
        </form>
      </div>
    </>
  );
}
