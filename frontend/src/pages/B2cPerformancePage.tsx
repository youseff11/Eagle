import { Link, Navigate, useSearchParams } from "react-router";
import { boardQuery, useB2cBoard, type BoardCompany, type BoardCounts, type BoardRate } from "../api/b2c";
import { useMe } from "../api/queries";
import { B2C_STATUS_AR } from "../components/b2b/SheetGrid";
import { TargetsCard } from "../components/b2b/TargetsCard";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { PeriodPicker, usePeriod } from "../components/PeriodPicker";
import { usePreferences } from "../i18n/Preferences";

/**
 * The B2C numbers (15/10/2026, the B2C requirements' section 9): a Sales person's own, or - for the B2C manager and the
 * owner - every B2C Sales person's, the team's total, the breakdowns and the companies that need someone. The period and
 * the filters are in the address, so a reload, a shared link and the export all read the same thing. Every figure is the
 * server's (`b2c_board.py`); a rate is drawn with what it is made of, and «مش متقاس» when there is nothing to divide by.
 */

/** The six figures of the requirements, in their order. */
const RATES: { key: keyof BoardCounts; ar: string; en: string; field?: boolean }[] = [
  { key: "visit_achievement", ar: "تحقيق تارجت الزيارات", en: "Visit achievement", field: true },
  { key: "verification_rate", ar: "نسبة اعتماد الزيارات", en: "Visit verification rate", field: true },
  { key: "lead_conversion", ar: "تحويل الزيارات لفرص", en: "Lead conversion", field: true },
  { key: "quotation_conversion", ar: "تحويل الفرص لعروض", en: "Quotation conversion" },
  { key: "win_rate", ar: "نسبة الكسب", en: "Win rate" },
  { key: "follow_up_compliance", ar: "الالتزام بالمتابعات", en: "Follow-up compliance" },
];

/** The counts beside them. */
const COUNTS: { key: keyof BoardCounts; ar: string; en: string; tone?: string }[] = [
  { key: "new_leads", ar: "شركات جديدة", en: "New leads" },
  { key: "contacted", ar: "اتواصلنا معاهم", en: "Contacted" },
  { key: "calls", ar: "مكالمات", en: "Calls" },
  { key: "messages", ar: "رسايل", en: "Messages" },
  { key: "verified", ar: "زيارات معتمدة", en: "Verified visits", tone: "kpi--ok" },
  { key: "pending", ar: "زيارات مستنية", en: "Visits waiting" },
  { key: "qualified", ar: "فرص مؤهلة", en: "Qualified" },
  { key: "quotations", ar: "عروض أسعار اتبعتت", en: "Quotations sent" },
  { key: "quotes_waiting", ar: "عروض مستنية الرد", en: "Quotations awaiting reply" },
  { key: "won", ar: "تم التعاقد", en: "Won", tone: "kpi--ok" },
  { key: "overdue_now", ar: "متابعات متأخرة دلوقتي", en: "Overdue follow-ups now", tone: "kpi--danger" },
  { key: "untouched", ar: "لسه محدش كلمهم", en: "Untouched", tone: "kpi--warn" },
];

/** The filters the address holds besides the period. */
const FILTERS = ["person", "source", "governorate"] as const;

function Rate({ rate }: { rate: BoardRate }) {
  const { t } = usePreferences();
  if (rate.value === null) return <span className="muted">{t("مش متقاس", "Not measured")}</span>;
  return (
    <span className="mono">
      {rate.value}% <span className="muted">({rate.part}/{rate.whole})</span>
    </span>
  );
}

/** A list of companies that need someone, each opening its sheet. */
function Companies({ title, icon, items, empty, day }: { title: string; icon: string; items: BoardCompany[]; empty: string; day?: boolean }) {
  const { t } = usePreferences();
  return (
    <div className="card">
      <div className="card__head">
        <Icon name={icon} />
        <h3>{title}</h3>
        <span className="chip chip--sm mono">{items.length}</span>
      </div>
      {items.length ? (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {items.map((item) => (
            <li key={item.id} className="row row--tight" style={{ padding: "6px 0", borderBottom: "1px solid var(--border)" }} data-company={item.id}>
              <strong>{item.company_name}</strong>
              <span className="muted">{[item.person, item.governorate].filter(Boolean).join(" · ")}</span>
              {day && item.next_follow_up && <span className="mono deadline--late">{item.next_follow_up}</span>}
              <div className="grow" />
              <Link className="btn btn--sm" to={`/leads/${item.sheet}`}>
                {t("افتح الشيت", "Open the sheet")}
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <div className="muted">{empty}</div>
      )}
    </div>
  );
}

export function B2cPerformancePage() {
  const { t, lang } = usePreferences();
  const me = useMe();
  const user = me.data?.user;
  // The B2C Sales people (their own numbers) and the owner (the server holds the same rule, `b2c_board.has_door`).
  const allowed = Boolean(user && (user.is_admin || (user.role === "sales" && (user.sales_track ?? "b2b") !== "b2b")));
  const [from, to] = usePeriod();
  const [params, setParams] = useSearchParams();
  const values: Record<"from" | "to" | (typeof FILTERS)[number], string> = {
    from,
    to,
    person: params.get("person") ?? "",
    source: params.get("source") ?? "",
    governorate: params.get("governorate") ?? "",
  };
  const board = useB2cBoard(values, allowed);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = board.data;
  const shown = data ? { from: data.from, to: data.to } : { from, to };
  const pick = (name: (typeof FILTERS)[number], value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  };
  const stageWord = (value: string) => (lang === "ar" ? (B2C_STATUS_AR[value] ?? value) : value);
  const field = data ? data.rows.some((row) => row.field) : false;
  const rates = RATES.filter((rate) => field || !rate.field);

  return (
    <>
      <div className="page-head">
        <h1>{t("أداء B2C", "B2C performance")}</h1>
        <span className="page-head__sub">
          {data?.team
            ? t("أرقام فريق B2C كله وكل Sales في الفترة والفلتر اللي تختارهم.", "The whole B2C team's numbers, and each Sales person's, for the period and filters you choose.")
            : t("أرقامك انت في الفترة اللي تختارها.", "Your own numbers for the period you choose.")}
        </span>
      </div>

      <PeriodPicker shown={shown} />

      {data && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="row">
            {data.filters.people.length > 0 && (
              <select className="input" style={{ width: "auto" }} aria-label={t("الـSales", "Sales person")} value={values.person} onChange={(event) => pick("person", event.target.value)}>
                <option value="">{t("كل الفريق", "The whole team")}</option>
                {data.filters.people.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name}
                  </option>
                ))}
              </select>
            )}
            <select className="input" style={{ width: "auto" }} aria-label={t("المصدر", "Source")} value={values.source} onChange={(event) => pick("source", event.target.value)}>
              <option value="">{t("كل المصادر", "Every source")}</option>
              {data.filters.sources.map((source) => (
                <option key={source} value={source}>
                  {source}
                </option>
              ))}
            </select>
            <select className="input" style={{ width: "auto" }} aria-label={t("المحافظة", "Governorate")} value={values.governorate} onChange={(event) => pick("governorate", event.target.value)}>
              <option value="">{t("كل المحافظات", "Every governorate")}</option>
              {data.filters.governorates.map((place) => (
                <option key={place} value={place}>
                  {place}
                </option>
              ))}
            </select>
            <div className="grow" />
            {/* The same period and filters as the page, as a file: the server writes it (names of the Sales people only). */}
            <a className="btn" href={`/api/v1/b2c/board/export/${boardQuery(values)}`} download>
              <Icon name="download" />
              {t("نزّل CSV", "Download CSV")}
            </a>
          </div>
        </div>
      )}

      {data ? (
        <>
          <div className="grid grid--3" style={{ marginBottom: 14 }}>
            {rates.map((rate) => (
              <div key={rate.key} className="kpi" data-rate={rate.key}>
                <div className="kpi__value">
                  <Rate rate={data.total[rate.key] as BoardRate} />
                </div>
                <div className="kpi__label">{t(rate.ar, rate.en)}</div>
              </div>
            ))}
          </div>
          <div className="grid grid--4" style={{ marginBottom: 14 }}>
            {COUNTS.filter((count) => field || !["verified", "pending"].includes(count.key)).map((count) => (
              <div key={count.key} className={count.tone && Number(data.total[count.key]) > 0 ? `kpi ${count.tone}` : "kpi"} data-kpi={count.key}>
                <div className="kpi__value mono">{data.total[count.key] as number}</div>
                <div className="kpi__label">{t(count.ar, count.en)}</div>
              </div>
            ))}
            <div className="kpi" data-kpi="open_value">
              <div className="kpi__value mono">{data.total.open_value}</div>
              <div className="kpi__label">{t("قيمة الفرص المفتوحة", "Open deal value")}</div>
            </div>
            {Object.entries(data.total.quote_average).map(([currency, average]) => (
              <div className="kpi" key={currency} data-kpi={`quote_average_${currency}`}>
                <div className="kpi__value mono">
                  {average} {currency}
                </div>
                <div className="kpi__label">{t("متوسط عرض السعر", "Average quotation")}</div>
              </div>
            ))}
          </div>

          {allowed && <TargetsCard />}

          <div className="card" style={{ marginBottom: 14 }}>
            <div className="card__head">
              <Icon name="users" />
              <h3>{data.team ? t("كل Sales", "Each Sales person") : t("التفاصيل", "The details")}</h3>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("الـSales", "Sales person")}</th>
                    <th>{t("تارجت الزيارات", "Visits owed")}</th>
                    <th>{t("زيارات معتمدة", "Verified visits")}</th>
                    <th>{t("اترفضت", "Turned down")}</th>
                    {RATES.map((rate) => (
                      <th key={rate.key}>{t(rate.ar, rate.en)}</th>
                    ))}
                    <th>{t("متابعات متأخرة", "Overdue")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => (
                    <tr key={row.person.id} data-person={row.person.id}>
                      <td>
                        {row.person.name}
                        <div className="muted">{row.field ? t("ميداني", "Field") : t("أونلاين", "Online")}</div>
                      </td>
                      <td className="mono">{row.field ? row.due : "—"}</td>
                      <td className="mono">{row.verified}</td>
                      <td className="mono">{row.rejected}</td>
                      {RATES.map((rate) => (
                        <td key={rate.key}>
                          <Rate rate={row[rate.key] as BoardRate} />
                        </td>
                      ))}
                      <td className={row.overdue_now > 0 ? "mono deadline--late" : "mono"}>{row.overdue_now}</td>
                    </tr>
                  ))}
                  {data.rows.length === 0 && (
                    <tr>
                      <td colSpan={RATES.length + 5} className="empty">
                        {t("مفيش Sales في فريق B2C لسه.", "Nobody on the B2C team yet.")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="grid grid--3" style={{ marginBottom: 14 }}>
            <div className="card">
              <div className="card__head">
                <Icon name="target" />
                <h3>{t("المراحل دلوقتي", "Stages now")}</h3>
              </div>
              <table className="table">
                <tbody>
                  {data.stages.map((stage) => (
                    <tr key={stage.value} data-stage={stage.value}>
                      <td>{stageWord(stage.value)}</td>
                      <td className="mono">{stage.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card">
              <div className="card__head">
                <Icon name="tag" />
                <h3>{t("الشركات الجديدة حسب المصدر", "New leads by source")}</h3>
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("المصدر", "Source")}</th>
                    <th>{t("العدد", "Count")}</th>
                    <th>{t("تم التعاقد", "Won")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.sources.map((source) => (
                    <tr key={source.value} data-source={source.value}>
                      <td>{source.value || <span className="muted">{t("مش مكتوب", "Not written")}</span>}</td>
                      <td className="mono">{source.count}</td>
                      <td className="mono">{source.won}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card">
              <div className="card__head">
                <Icon name="map-pin" />
                <h3>{t("حسب المحافظة", "By governorate")}</h3>
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("المحافظة", "Governorate")}</th>
                    <th>{t("الشركات", "Companies")}</th>
                    <th>{t("زيارات معتمدة", "Verified visits")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.governorates.map((place) => (
                    <tr key={place.value} data-governorate={place.value}>
                      <td>{place.value || <span className="muted">{t("مش مكتوب", "Not written")}</span>}</td>
                      <td className="mono">{place.count}</td>
                      <td className="mono">{place.verified}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {data.team && data.matrix.length > 0 && (
            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card__head">
                <Icon name="layers" />
                <h3>{t("الشركات حسب الموظف والمرحلة", "Companies by person and stage")}</h3>
              </div>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>{t("الـSales", "Sales person")}</th>
                      {data.stages.map((stage) => (
                        <th key={stage.value}>{stageWord(stage.value)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.matrix.map((line) => (
                      <tr key={line.person.id} data-matrix={line.person.id}>
                        <td>{line.person.name}</td>
                        {data.stages.map((stage) => (
                          <td key={stage.value} className="mono">
                            {line.stages[stage.value] ?? 0}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="grid grid--2" style={{ marginBottom: 14 }}>
            <Companies
              title={t("شركات لسه محدش كلمها", "Companies nobody has contacted")}
              icon="alert"
              items={data.untouched}
              empty={t("كل الشركات اتكلّمت.", "Every company was contacted.")}
            />
            <Companies
              title={t("متابعات متأخرة", "Overdue follow-ups")}
              icon="calendar"
              items={data.overdue}
              empty={t("مفيش متابعات متأخرة.", "No overdue follow-ups.")}
              day
            />
          </div>

          {data.rejected.length > 0 && (
            <div className="card">
              <div className="card__head">
                <Icon name="x" />
                <h3>{t("زيارات اترفضت وأسبابها", "Turned-down visits and why")}</h3>
              </div>
              <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {data.rejected.map((visit) => (
                  <li key={visit.code} className="row row--tight" style={{ padding: "6px 0", borderBottom: "1px solid var(--border)" }} data-rejected={visit.code}>
                    <span className="mono">{visit.code}</span>
                    <strong>{visit.company_name}</strong>
                    <span className="muted">{visit.person}</span>
                    <span>{visit.note}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      ) : board.isError ? (
        <div className="card empty" role="alert">
          <Icon name="alert" size="xl" />
          <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
        </div>
      ) : (
        <Loading />
      )}
    </>
  );
}
