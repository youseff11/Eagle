import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { formErrors } from "../api/adminActions";
import { useDeleteOffice, useSaveOffice } from "../api/hrActions";
import { useHrOffices } from "../api/queries";
import type { FormErrors } from "../api/types";
import { Waiting, refusal } from "../components/accounts/shared";
import { DjangoForm, useFormEdits } from "../components/admin/DjangoForm";
import { useHrAllowed } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { useToasts } from "../components/Toasts";
import { usePreferences } from "../i18n/Preferences";
import { position } from "../lib/attendance";

/**
 * Where a punch may be made from. With no office there is no location check on any punch. The button that fills the
 * coordinates reads this device once, when it is pressed (the same one-shot reading the check-in uses), and nothing is
 * stored until the form is saved.
 */
export function HrOfficesPage() {
  const { t } = usePreferences();
  const { push } = useToasts();
  const { me, allowed } = useHrAllowed();
  const [params, setParams] = useSearchParams();
  const edit = params.get("edit") ?? "";
  const query = useHrOffices(edit, allowed);
  const save = useSaveOffice();
  const remove = useDeleteOffice();
  const data = query.data;
  const edits = useFormEdits(data?.form);
  const [errors, setErrors] = useState<FormErrors>({});
  const [problem, setProblem] = useState("");
  const [locating, setLocating] = useState<"" | "busy" | "denied">("");
  const editing = data?.editing ?? null;
  const { reset, set } = edits;
  useEffect(() => {
    reset();
    setErrors({});
    setProblem("");
    setLocating("");
  }, [editing, reset]);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setErrors({});
    setProblem("");
    save.mutate(
      { id: editing, values: edits.edited },
      {
        onSuccess: () => {
          edits.reset();
          push({ level: "success", title: editing === null ? t("اتسجل", "Recorded") : t("اتحفظ", "Saved") });
          if (editing !== null) setParams({});
        },
        onError: (error) => {
          const found = formErrors(error);
          if (found) setErrors(found);
          else setProblem(refusal(error, t("حصلت مشكلة، ماتحفظش.", "Something went wrong, nothing was saved.")));
        },
      },
    );
  };
  const useHere = async () => {
    setLocating("busy");
    const fix = await position();
    if (!fix) {
      setLocating("denied");
      return;
    }
    set("latitude", fix.lat.toFixed(6));
    set("longitude", fix.lng.toFixed(6));
    setLocating("");
  };
  const drop = (id: number) =>
    remove.mutate(id, {
      onSuccess: () => push({ level: "success", title: t("اتمسح", "Deleted") }),
      onError: (error) => push({ level: "danger", title: refusal(error, t("حصلت مشكلة.", "Something went wrong.")) }),
    });

  return (
    <>
      <div className="page-head">
        <h1>{t("مواقع المكاتب", "Office locations")}</h1>
      </div>

      <div className="grid grid--main">
        <div className="card">
          <div className="card__head">
            <Icon name="map-pin" />
            <h3>{t("المواقع", "Locations")}</h3>
          </div>
          <div className="table-wrap">
            <table className="table" data-table="offices">
              <thead>
                <tr>
                  <th>{t("المكتب", "Office")}</th>
                  <th>{t("الإحداثيات", "Coordinates")}</th>
                  <th>{t("النطاق", "Radius")}</th>
                  <th>{t("الحالة", "Status")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.offices.map((office) => (
                  <tr key={office.id} data-office={office.id}>
                    <td>{office.label}</td>
                    <td className="mono" dir="ltr">
                      {office.latitude}, {office.longitude}{" "}
                      <a
                        className="muted"
                        href={`https://www.google.com/maps?q=${encodeURIComponent(`${office.latitude},${office.longitude}`)}`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {t("على الخريطة", "On the map")}
                      </a>
                    </td>
                    <td className="mono">
                      {office.radius_meters}
                      {t("م", "m")}
                    </td>
                    <td>
                      {office.is_active ? <span className="badge badge--ok">{t("شغال", "Active")}</span> : <span className="badge">{t("مقفول", "Off")}</span>}
                    </td>
                    <td>
                      <div className="row row--tight">
                        <Link className="btn btn--sm btn--ghost" to={`/hr/offices?edit=${office.id}`}>
                          <Icon name="pen" size="sm" />
                          <span>{t("عدّل", "Edit")}</span>
                        </Link>
                        <button className="btn btn--sm btn--ghost" type="button" aria-label={t("احذف", "Delete")} disabled={remove.isPending} onClick={() => drop(office.id)}>
                          <Icon name="trash" size="sm" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {data.offices.length === 0 && (
                  <tr>
                    <td colSpan={5} className="empty">
                      {t("مفيش مواقع — يعني مفيش فحص موقع على أي حضور.", "No locations, which means no punch is location-checked at all.")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="sticky-side">
          <div className="card">
            <div className="card__head">
              <Icon name="plus" />
              <h3>{editing !== null ? t("تعديل مكتب", "Edit office") : t("ضيف مكتب", "Add an office")}</h3>
              {editing !== null && (
                <>
                  <div className="grow" />
                  <Link className="btn btn--sm btn--ghost" to="/hr/offices">
                    <Icon name="plus" size="sm" />
                    <span>{t("مكتب جديد", "New office")}</span>
                  </Link>
                </>
              )}
            </div>
            <form onSubmit={submit}>
              <DjangoForm fields={data.form} edits={edits} errors={errors} prefix="office" />
              <div className="mt">
                <button className="btn btn--sm btn--block" type="button" disabled={locating === "busy"} onClick={() => void useHere()}>
                  <Icon name="map-pin" size="sm" />
                  <span>{t("استخدم موقعي الحالي", "Use my current location")}</span>
                </button>
                <small className="muted" aria-live="polite">
                  {locating === "denied"
                    ? t("مقدرتش أقرا الموقع. اسمح للمتصفح أو اكتب الإحداثيات بإيدك.", "Could not read the location. Allow it in the browser, or type the coordinates.")
                    : t(
                        "وانت واقف في المكتب دوس هنا يملى الإحداثيات. بيقرا موقع جهازك مرة واحدة وقت الضغط بس ومابيتخزنش غير لما تدوس احفظ.",
                        "Standing in the office, press this to fill the coordinates. It reads this device once, when pressed, and nothing is stored until you Save.",
                      )}
                </small>
              </div>
              {problem && (
                <div className="note note--high" role="alert">
                  <Icon name="alert" />
                  <div>{problem}</div>
                </div>
              )}
              <button className="btn btn--primary btn--block mt" type="submit" disabled={save.isPending || !edits.dirty}>
                <Icon name="check" size="sm" />
                <span>{t("احفظ", "Save")}</span>
              </button>
            </form>
          </div>

          <div className="note note--info" data-note="policy">
            <Icon name="info" />
            <div>
              <div>{t("السياسة دلوقتي:", "The current policy:")}</div>
              <b>{data.policy === "reject" ? t("رفض الحضور من بره النطاق", "Refuse off-site punches") : t("تسجيله وتعليمه للمراجعة", "Record and flag for review")}</b>
              <div className="muted mt">
                {t(
                  "بتتغير من صفحة قواعد الحساب. دقة الـGPS بتتضاف على النطاق تلقائيًا، فالتسجيل بدقة ±80م بيعدي جوه نطاق 200م.",
                  "Changed from the payroll rules page. The phone's own accuracy is added to the radius, so a punch reported at ±80 m still passes a 200 m radius.",
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
