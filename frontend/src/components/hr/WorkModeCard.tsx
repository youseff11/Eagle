import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { ApiError } from "../../api/client";
import { useSetWorkMode } from "../../api/hrActions";
import type { HrEmployee } from "../../api/types";
import { Icon } from "../Icon";
import { useToasts } from "../Toasts";
import { usePreferences } from "../../i18n/Preferences";

/**
 * Home or office, from the employee's file. The office ties the punch to the zone set on the offices page; home does not - a
 * remote day is never asked for a location at all. Hybrid is only kept for somebody already on it (the roster then decides each
 * day): it is not offered as a fresh choice.
 */
export function WorkModeCard({ id, card }: { id: number; card: NonNullable<HrEmployee["work_mode_card"]> }) {
  const { t, lang } = usePreferences();
  const { push } = useToasts();
  const save = useSetWorkMode(id);
  const [mode, setMode] = useState(card.work_mode?.value ?? "");
  useEffect(() => setMode(card.work_mode?.value ?? ""), [card.work_mode?.value]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate(mode, {
      onSuccess: () => push({ level: "success", title: t("اتحفظ", "Saved") }),
      onError: (error) =>
        push({
          level: "danger",
          title: error instanceof ApiError && error.code === "bad_mode" ? t("اختار من البيت أو من الشركة.", "Pick home or the office.") : t("حصلت مشكلة.", "Something went wrong."),
        }),
    });
  };
  const choice = (value: string, ar: string, en: string, noteAr: string, noteEn: string) => (
    <label className="kv" style={{ cursor: "pointer" }}>
      <span>
        <input type="radio" name="work_mode" value={value} checked={mode === value} onChange={() => setMode(value)} /> <b>{t(ar, en)}</b>
      </span>
      <span className="muted">{t(noteAr, noteEn)}</span>
    </label>
  );

  return (
    <div className="card" data-card="work-mode">
      <div className="card__head">
        <Icon name="map-pin" />
        <h3>{t("مكان الشغل", "Where they work")}</h3>
        <div className="grow" />
        {card.work_mode && <span className="chip">{lang === "ar" ? card.work_mode.ar : card.work_mode.en}</span>}
      </div>
      <form onSubmit={submit}>
        {choice("office", "من الشركة", "From the office", "مربوط بنطاق المكتب", "Tied to the office zone")}
        {choice("remote", "من البيت", "From home", "مش مربوط بأي نطاق", "Not tied to any zone")}
        {card.is_hybrid && choice("hybrid", "هجين", "Hybrid", "كل يوم حسب الجدول", "Each day follows the roster")}
        <div className="mt">
          {card.offices.length > 0 ? (
            <>
              <div className="muted" style={{ fontSize: ".8rem" }}>
                {t("الشغل من الشركة بيتحقق من مكان التسجيل جوه:", "Working from the office checks where the punch is made, inside:")}
              </div>
              {card.offices.map((office) => (
                <div className="kv" key={office.label}>
                  <span>{office.label}</span>
                  <b className="mono">
                    {office.radius_meters} {t("متر", "m")}
                  </b>
                </div>
              ))}
              <p className="muted" style={{ fontSize: ".8rem" }}>
                {card.policy_reject
                  ? t("لو سجّل من بره النطاق التسجيل بيترفض.", "A punch from outside the zone is refused.")
                  : t("لو سجّل من بره النطاق التسجيل بيتسجّل ويتعلّم للمراجعة.", "A punch from outside the zone is recorded and flagged for review.")}
              </p>
            </>
          ) : (
            <div className="note note--warn" data-note="no-office">
              <Icon name="alert" />
              <div>
                {t("مفيش مكتب متسجّل، فمفيش فحص موقع لأي حد.", "No office is set, so nobody's punch is location-checked.")}{" "}
                <Link to="/hr/offices">{t("سجّل المكتب والنطاق", "Set the office and zone")}</Link>
              </div>
            </div>
          )}
          {card.pinned_days > 0 && (
            <p className="muted" style={{ fontSize: ".8rem" }}>
              {t(
                `في ${card.pinned_days} يوم في جدوله متحدد له نظام بنفسه، واليوم ده بيمشي على الجدول مش على الاختيار ده.`,
                `${card.pinned_days} roster day(s) carry their own mode, and those days follow the roster, not this choice.`,
              )}
            </p>
          )}
          <p className="muted" style={{ fontSize: ".8rem" }}>
            {t(
              "بيسري على أي يوم لسه ماتسجلش فيه حضور. اليوم اللي اتسجل فيه حضور بيفضل على اللي اتفتح بيه.",
              "Applies to any day with no check-in yet. A day already checked into keeps the mode it was opened with.",
            )}
          </p>
        </div>
        <button className="btn btn--primary btn--sm btn--block" type="submit" disabled={save.isPending || mode === (card.work_mode?.value ?? "")}>
          <Icon name="check" size="sm" />
          <span>{t("احفظ", "Save")}</span>
        </button>
      </form>
    </div>
  );
}
