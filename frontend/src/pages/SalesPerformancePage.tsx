import { Navigate } from "react-router";
import { useB2bKpis, type KpiCounts } from "../api/b2b";
import { useMe } from "../api/queries";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { PeriodPicker, usePeriod } from "../components/PeriodPicker";
import { TargetsCard } from "../components/b2b/TargetsCard";
import { usePreferences } from "../i18n/Preferences";

/** A percentage, or «مش متقاس» when there was nothing to measure (never a made-up 0%). */
function Rate({ value }: { value: number | null }) {
  const { t } = usePreferences();
  if (value === null) return <span className="muted">{t("مش متقاس", "Not measured")}</span>;
  return <span className="mono">{value}%</span>;
}

/** The columns of the table, in the order of the B2B requirements' section 11. */
const COLUMNS: { key: keyof KpiCounts; ar: string; en: string; hint?: [string, string] }[] = [
  { key: "new_leads", ar: "شركات جديدة", en: "New leads" },
  { key: "contacted", ar: "اتواصلنا معاهم", en: "Contacted" },
  { key: "whatsapp", ar: "رسايل واتساب", en: "WhatsApp messages" },
  { key: "emails", ar: "إيميلات", en: "E-mails sent" },
  { key: "calls", ar: "مكالمات", en: "Calls logged" },
  { key: "replies", ar: "ردّوا", en: "Answered" },
  { key: "visits", ar: "زيارات", en: "Visits" },
  { key: "quotations", ar: "عروض اتبعتت", en: "Quotations sent" },
  { key: "quotes_accepted", ar: "عروض اتقبلت", en: "Quotations accepted" },
  { key: "revenue", ar: "الإيراد", en: "Revenue", hint: ["إجمالي العروض اللي اتقبلت في الفترة، كل عملة لوحدها.", "The accepted quotations' totals in the period, each currency on its own."] },
  { key: "won", ar: "تم التعاقد", en: "Contracted" },
  { key: "lost", ar: "مرفوض", en: "Refused" },
  { key: "conversion_rate", ar: "نسبة التحويل", en: "Conversion", hint: ["من الشركات اللي اتحسمت (تم التعاقد أو مرفوض) في الفترة: نسبة اللي اتعاقدنا معاهم.", "Of the companies decided (contracted or refused) in the period: the share contracted."] },
  { key: "follow_ups_on_time", ar: "متابعات في يومها", en: "Follow-ups on time" },
  { key: "follow_ups_late", ar: "متابعات متأخرة اتعملت", en: "Follow-ups done late" },
  { key: "follow_ups_missed", ar: "متابعات ماتعملتش", en: "Follow-ups missed" },
  { key: "follow_up_rate", ar: "الالتزام بالمتابعة", en: "Follow-up on time", hint: ["من المتابعات اللي كان يومها في الفترة: اللي اتعملت في يومها.", "Of the follow-ups due in the period: the ones done on their day."] },
  { key: "overdue_now", ar: "متأخرة دلوقتي", en: "Overdue now" },
  { key: "holding", ar: "الشركات عنده", en: "Companies held" },
  { key: "untouched", ar: "لسه ماتواصلناش", en: "Not contacted yet" },
];
const RATES = new Set<keyof KpiCounts>(["conversion_rate", "follow_up_rate"]);

/** The revenue, one figure per currency (never added across them); none accepted is a real zero. */
function Revenue({ value }: { value: Record<string, string> }) {
  const entries = Object.entries(value);
  if (entries.length === 0) return <span className="mono">0</span>;
  return (
    <span className="mono">
      {entries.map(([currency, amount]) => (
        <div key={currency}>
          {Number(amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {currency}
        </div>
      ))}
    </span>
  );
}

function Cell({ counts, name }: { counts: KpiCounts; name: keyof KpiCounts }) {
  const value = counts[name];
  if (name === "revenue") return <Revenue value={value as Record<string, string>} />;
  if (RATES.has(name)) return <Rate value={value as number | null} />;
  const count = value as number;
  return <span className={name === "overdue_now" && count > 0 ? "mono deadline--late" : "mono"}>{count}</span>;
}

/**
 * The Sales numbers (the B2B requirements' sections 11 and 12): a Sales person's own, or every Sales person's and the team's
 * for the Sales manager and the owner. The period is in the address, so a reload and a shared link keep it.
 */
export function SalesPerformancePage() {
  const { t, lang } = usePreferences();
  const me = useMe();
  const [from, to] = usePeriod();
  const allowed = me.data !== undefined && (me.data.user.role === "sales" || me.data.user.is_admin);
  const numbers = useB2bKpis(from, to, allowed);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = numbers.data;
  const shown = data ? { from: data.from, to: data.to } : { from, to };
  const tiles: { key: keyof KpiCounts; ar: string; en: string; tone?: string }[] = [
    { key: "new_leads", ar: "شركات جديدة", en: "New leads" },
    { key: "contacted", ar: "اتواصلنا معاهم", en: "Contacted" },
    { key: "replies", ar: "ردّوا", en: "Answered" },
    { key: "visits", ar: "زيارات", en: "Visits" },
    { key: "won", ar: "تم التعاقد", en: "Contracted", tone: "kpi--ok" },
    { key: "quotations", ar: "عروض اتبعتت", en: "Quotations sent" },
    { key: "revenue", ar: "الإيراد", en: "Revenue" },
    { key: "lost", ar: "مرفوض", en: "Refused" },
    { key: "conversion_rate", ar: "نسبة التحويل", en: "Conversion" },
    { key: "overdue_now", ar: "متابعات متأخرة دلوقتي", en: "Overdue follow-ups now", tone: "kpi--danger" },
  ];

  return (
    <>
      <div className="page-head">
        <h1>{t("أداء المبيعات", "Sales performance")}</h1>
        <span className="page-head__sub">
          {data?.team
            ? t("أرقام كل Sales والفريق كله في الفترة اللي تختارها.", "Every Sales person's numbers, and the team's, for the period you choose.")
            : t("أرقامك انت في الفترة اللي تختارها.", "Your own numbers for the period you choose.")}
        </span>
      </div>

      {allowed && <TargetsCard />}

      <PeriodPicker shown={shown} />

      {data ? (
        <>
          <div className="grid grid--4" style={{ marginBottom: 14 }}>
            {tiles.map((tile) => (
              <div key={tile.key} className={tile.tone && Number(data.total[tile.key]) > 0 ? `kpi ${tile.tone}` : "kpi"} data-kpi={tile.key}>
                <div className="kpi__value">
                  <Cell counts={data.total} name={tile.key} />
                </div>
                <div className="kpi__label">{t(tile.ar, tile.en)}</div>
              </div>
            ))}
          </div>

          <div className="card">
            <div className="card__head">
              <Icon name="chart" />
              <h3>{data.team ? t("كل Sales", "Each Sales person") : t("التفاصيل", "The details")}</h3>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("الـSales", "Sales person")}</th>
                    {COLUMNS.map((column) => (
                      <th key={column.key} title={column.hint ? (lang === "ar" ? column.hint[0] : column.hint[1]) : undefined}>
                        {t(column.ar, column.en)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => (
                    <tr key={row.person.id} data-person={row.person.id}>
                      <td>
                        <strong>{row.person.name}</strong>
                        {!row.person.active && <div className="muted">{t("حسابه مقفول", "Account closed")}</div>}
                      </td>
                      {COLUMNS.map((column) => (
                        <td key={column.key}>
                          <Cell counts={row} name={column.key} />
                        </td>
                      ))}
                    </tr>
                  ))}
                  {data.team && data.rows.length > 1 && (
                    <tr data-person="total">
                      <td>
                        <strong>{t("الفريق كله", "The whole team")}</strong>
                      </td>
                      {COLUMNS.map((column) => (
                        <td key={column.key}>
                          <strong>
                            <Cell counts={data.total} name={column.key} />
                          </strong>
                        </td>
                      ))}
                    </tr>
                  )}
                  {data.rows.length === 0 && (
                    <tr>
                      <td colSpan={COLUMNS.length + 1} className="empty">
                        <Icon name="chart" size="xl" />
                        <span>{t("مفيش Sales لسه.", "No Sales people yet.")}</span>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <p className="muted" style={{ marginTop: 10 }}>
              {t(
                "الأرقام بتتحسب للـSales اللي كانت الشركة معاه وقت ما الحاجة حصلت. «متأخرة دلوقتي» و«الشركات عنده» و«لسه ماتواصلناش» عن النهارده مش عن الفترة. الإيراد = العروض اللي اتقبلت، كل عملة لوحدها.",
                "Numbers count for the Sales person who held the company when it happened. «Overdue now», «Companies held» and «Not contacted yet» are about today, not the period. Revenue = the accepted quotations, each currency on its own.",
              )}
            </p>
          </div>
        </>
      ) : numbers.isError ? (
        <div className="card empty" role="alert">
          <Icon name="alert" size="xl" />
          <span>{t("الفترة دي مش مظبوطة أو حصلت مشكلة في التحميل.", "That period is not valid, or it could not load.")}</span>
        </div>
      ) : (
        <Loading />
      )}
    </>
  );
}
