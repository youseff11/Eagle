import { useState, type FormEvent } from "react";
import { Navigate, useSearchParams } from "react-router";
import { useHrCandidates } from "../api/queries";
import { Waiting } from "../components/accounts/shared";
import { useHrAllowed } from "../components/hr/shared";
import { Icon } from "../components/Icon";
import { useLeaveWords } from "../components/leave/shared";
import { usePreferences } from "../i18n/Preferences";
import { CandidateRows } from "./HrRecruitmentPage";

const FILTERS = ["status", "source", "vacancy", "q"] as const;

/** Everyone who applied. The filters and the search live in the address, so a list can be sent to somebody and comes back as it was. */
export function HrCandidatesPage() {
  const { t } = usePreferences();
  const words = useLeaveWords();
  const { me, allowed } = useHrAllowed();
  const [params, setParams] = useSearchParams();
  const search = FILTERS.filter((name) => params.get(name))
    .map((name) => `${name}=${encodeURIComponent(params.get(name) ?? "")}`)
    .join("&");
  const query = useHrCandidates(search, allowed);
  const [typed, setTyped] = useState(params.get("q") ?? "");
  const data = query.data;

  if (me.data && !allowed) return <Navigate to="/" replace />;
  if (!data) return <Waiting failed={query.isError} />;

  const set = (name: (typeof FILTERS)[number], value: string) => {
    const next = new URLSearchParams();
    for (const key of FILTERS) {
      const kept = key === name ? value : (params.get(key) ?? "");
      if (kept) next.set(key, kept);
    }
    setParams(next);
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    set("q", typed.trim());
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("المرشحين", "Candidates")}</h1>
        <div className="grow" />
        <span className="chip mono">
          {data.rows.length} / {data.total}
        </span>
      </div>

      <div className="card">
        <form className="row row--tight" style={{ flexWrap: "wrap" }} onSubmit={submit} role="search">
          <input
            className="input"
            type="search"
            aria-label={t("بحث", "Search")}
            placeholder={t("اسم، موبايل، كود، إيميل", "Name, phone, code, e-mail")}
            value={typed}
            maxLength={80}
            onChange={(event) => setTyped(event.target.value)}
          />
          <button className="btn btn--sm" type="submit">
            <Icon name="search" size="sm" />
            <span>{t("دوّر", "Search")}</span>
          </button>
          <select className="input" aria-label={t("الحالة", "Status")} value={params.get("status") ?? ""} onChange={(event) => set("status", event.target.value)}>
            <option value="">{t("كل الحالات", "Any status")}</option>
            {data.statuses.map((one) => (
              <option key={one.value} value={one.value}>
                {words(one)}
              </option>
            ))}
          </select>
          <select className="input" aria-label={t("المصدر", "Source")} value={params.get("source") ?? ""} onChange={(event) => set("source", event.target.value)}>
            <option value="">{t("كل المصادر", "Any source")}</option>
            {data.sources.map((one) => (
              <option key={one.value} value={one.value}>
                {words(one)}
              </option>
            ))}
          </select>
          <select className="input" aria-label={t("الوظيفة", "Vacancy")} value={params.get("vacancy") ?? ""} onChange={(event) => set("vacancy", event.target.value)}>
            <option value="">{t("كل الوظائف", "Any vacancy")}</option>
            {data.vacancies.map((one) => (
              <option key={one.code} value={one.code}>
                {one.code} · {one.title}
              </option>
            ))}
          </select>
        </form>
      </div>

      {data.total > data.rows.length && (
        <div className="note note--info" data-note="limit">
          <Icon name="info" />
          <div>
            {t(`بيعرض أحدث ${data.rows.length} من ${data.total} — ضيّق البحث عشان توصل للباقي.`, `Showing the newest ${data.rows.length} of ${data.total}. Narrow the search for the rest.`)}
          </div>
        </div>
      )}

      <div className="card">
        <CandidateRows rows={data.rows} phones empty={t("مفيش مرشحين بالشروط دي.", "Nobody matches.")} />
      </div>
    </>
  );
}
