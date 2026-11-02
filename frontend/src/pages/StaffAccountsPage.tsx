import { useMemo, useState, type FormEvent } from "react";
import { Link, Navigate } from "react-router";
import { formErrors } from "../api/adminActions";
import { useEnterAccount, useMe, useSetAccountPassword, useStaffAccounts } from "../api/queries";
import type { StaffAccount } from "../api/types";
import { Avatar } from "../components/Avatar";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { Modal } from "../components/Modal";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { ROLE_LABELS } from "../lib/roles";

/** The app starts again on the other person's account: nothing cached of the one before may be drawn. */
function reloadApp(): void {
  window.location.assign("/app/");
}

/**
 * A new password for one person, typed twice. The old one is not asked (they forgot it); every refusal is the server's (the
 * project's rules for a password) and is said beside the boxes. The person is signed out everywhere by the change.
 */
function PasswordDialog({ person, onClose }: { person: StaffAccount; onClose: () => void }) {
  const { t } = usePreferences();
  const { push } = useToasts();
  const save = useSetAccountPassword();
  const [boxes, setBoxes] = useState({ new_password1: "", new_password2: "" });
  const [problem, setProblem] = useState("");
  const ready = boxes.new_password1 !== "" && boxes.new_password2 !== "";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setProblem("");
    save.mutate(
      { id: person.id, ...boxes },
      {
        onSuccess: () => {
          push({ level: "success", title: t(`الباسورد بتاع ${person.name} اتغيّر`, `${person.name}'s password was changed`) });
          onClose();
        },
        onError: (error) => {
          // The boxes keep what was typed, but the request's copy of it does not stay in the mutation.
          save.reset();
          const found = formErrors(error);
          const messages = found ? Object.values(found).flat() : [];
          setProblem(messages.length > 0 ? messages.join(" ") : t("الباسورد ماتغيّرش. جرّب تاني.", "The password was not changed. Try again."));
        },
      },
    );
  };

  const box = (name: keyof typeof boxes, label: string) => (
    <div className="field">
      <label htmlFor={`account-${name}`}>{label}</label>
      <input
        id={`account-${name}`}
        className="input"
        type="password"
        dir="ltr"
        autoComplete="new-password"
        value={boxes[name]}
        onChange={(event) => setBoxes({ ...boxes, [name]: event.target.value })}
      />
    </div>
  );

  return (
    <Modal title={t(`باسورد جديد لـ${person.name}`, `A new password for ${person.name}`)} icon="lock" busy={save.isPending} onClose={onClose}>
      <form onSubmit={submit} data-dialog="password">
        {box("new_password1", t("الباسورد الجديد", "New password"))}
        {box("new_password2", t("الجديد تاني", "New password again"))}
        <small className="muted">
          {t("هيتخرج من السيستم في كل مكان وهيدخل بالجديد.", "They are signed out everywhere and sign in with the new one.")}
        </small>
        {problem && (
          <div className="note note--high mt" role="alert">
            <Icon name="alert" />
            <div>{problem}</div>
          </div>
        )}
        <div className="row row--tight mt">
          <button type="submit" className="btn btn--primary" disabled={!ready || save.isPending}>
            <Icon name="check" size="sm" />
            <span>{t("احفظ الباسورد", "Save password")}</span>
          </button>
          <button type="button" className="btn btn--ghost" onClick={onClose} disabled={save.isPending}>
            {t("إلغاء", "Cancel")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/**
 * «حسابات الموظفين»: technical support opens any employee's account and works in it exactly as they do (all but the attendance
 * punch, `impersonation.py`), or gives them a new password. The owner and support
 * accounts are not on the list.
 */
export function StaffAccountsPage() {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const me = useMe();
  // The same people the server lets in (`api_role_required`: technical support, and the admin).
  const allowed = me.data !== undefined && (me.data.user.role === "support" || me.data.user.is_admin);
  const query = useStaffAccounts(allowed);
  const enter = useEnterAccount();
  const [search, setSearch] = useState("");
  const [password, setPassword] = useState<StaffAccount | null>(null);

  const rows = useMemo(() => {
    const words = search.trim().toLowerCase();
    const all = query.data?.accounts ?? [];
    if (!words) return all;
    return all.filter((person) => `${person.name} ${person.username}`.toLowerCase().includes(words));
  }, [query.data, search]);

  if (me.data && !allowed) return <Navigate to="/" replace />;

  const open = (person: StaffAccount) =>
    enter.mutate(person.id, {
      onSuccess: reloadApp,
      onError: () => push({ level: "danger", title: t("ماقدرناش نفتح الحساب ده.", "Could not open that account.") }),
    });

  return (
    <>
      <div className="page-head">
        <h1>{t("حسابات الموظفين", "Staff accounts")}</h1>
        <span className="page-head__sub">
          {t(
            "ادخل على حساب أي موظف واشتغل من شاشته زي ما هو شايفها، أو غيّر الباسورد بتاعه.",
            "Open any employee's account and work from their screen as they see it, or change their password.",
          )}
        </span>
        <div className="grow" />
        <Link className="btn btn--sm btn--primary" to="/hr/employees/new">
          <Icon name="plus" size="sm" />
          <span>{t("موظف جديد", "New staff member")}</span>
        </Link>
      </div>

      <div className="card">
        <div className="card__head">
          <Icon name="user-check" />
          <h3>{t("الموظفين", "People")}</h3>
          {query.data && <span className="chip chip--sm mono">{rows.length}</span>}
          <div className="grow" />
          <input
            className="input"
            type="search"
            aria-label={t("دوّر بالاسم أو اليوزرنيم", "Search by name or username")}
            placeholder={t("دوّر بالاسم أو اليوزرنيم", "Search by name or username")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        {query.isPending ? (
          <Loading className="empty" />
        ) : query.isError ? (
          <div className="empty" role="alert">
            <Icon name="alert" size="xl" />
            <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table" data-table="accounts">
              <thead>
                <tr>
                  <th>{t("الموظف", "Employee")}</th>
                  <th>{t("الدور", "Role")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((person) => (
                  <tr key={person.id} data-account={person.id}>
                    <td>
                      <div className="row row--tight">
                        <Avatar src={person.avatar} initials={person.initials} tone="" className="avatar--sm" />
                        <div>
                          <div>{person.name}</div>
                          <small className="muted mono">{person.username}</small>
                        </div>
                      </div>
                    </td>
                    <td>
                      <span className="chip">{ROLE_LABELS[person.role]?.[lang === "ar" ? 0 : 1] ?? person.role}</span>
                    </td>
                    <td>
                      <div className="row row--tight" style={{ justifyContent: "flex-end" }}>
                        <button className="btn btn--sm btn--primary" type="button" disabled={enter.isPending} onClick={() => open(person)}>
                          <Icon name="eye" size="sm" />
                          <span>{t("ادخل على حسابه", "Open their account")}</span>
                        </button>
                        <button className="btn btn--sm" type="button" onClick={() => setPassword(person)}>
                          <Icon name="lock" size="sm" />
                          <span>{t("غيّر الباسورد", "Change password")}</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={3} className="empty">
                      {t("مفيش موظف بالاسم ده.", "Nobody by that name.")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {password && <PasswordDialog person={password} onClose={() => setPassword(null)} />}
    </>
  );
}
