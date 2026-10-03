import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import { formErrors, useCreateClient, useSaveClient } from "../api/adminActions";
import { useAdminClient, useMe } from "../api/queries";
import type { FormErrors } from "../api/types";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";

/**
 * A client's identity: name, company, the main number and address, the others, the country and the admin's notes. A number
 * or an address that already belongs to another client is refused by the form (two clients answering to one number would
 * split the messages between two codes). Opening an existing client is written to the audit log.
 */
export function AdminClientFormPage() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const navigate = useNavigate();
  const params = useParams();
  const code = params.code ?? "";
  const me = useMe();
  const allowed = me.data !== undefined && me.data.user.is_admin;
  const query = useAdminClient(code, allowed);
  const create = useCreateClient();
  const save = useSaveClient(code);
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
    const onError = (error: unknown) => {
      const found = formErrors(error);
      if (found) setErrors(found);
      else setFailed(true);
    };
    if (code) {
      save.mutate(edits.edited, {
        onSuccess: () => {
          edits.reset();
          push({ level: "success", title: t("اتحفظ", "Saved") });
        },
        onError,
      });
    } else {
      create.mutate(edits.edited, { onSuccess: (answer) => navigate(`/clients/${encodeURIComponent(answer.code)}`), onError });
    }
  };

  return (
    <>
      <div className="page-head">
        <h1>{code ? <span className="mono">{code}</span> : t("عميل جديد", "New client")}</h1>
        <div className="grow" />
        <Link className="btn btn--sm" to="/admin/clients">
          {t("كل العملاء", "All clients")}
        </Link>
      </div>
      <div className="card" style={{ maxWidth: 680 }}>
        <form onSubmit={submit}>
          <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="client" />
          {failed && (
            <div className="note note--high" role="alert">
              <Icon name="alert" />
              <div>{t("حصلت مشكلة، ماتحفظش.", "Something went wrong, nothing was saved.")}</div>
            </div>
          )}
          <button className="btn btn--primary" type="submit" disabled={create.isPending || save.isPending || (Boolean(code) && !edits.dirty)}>
            <Icon name="check" size="sm" />
            <span>{t("حفظ", "Save")}</span>
          </button>
        </form>
      </div>
    </>
  );
}
