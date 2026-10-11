import type { ReactNode } from "react";
import { Link, Navigate } from "react-router";
import { useCeoBoard, type PerCurrency } from "../api/ceo";
import { useMe } from "../api/queries";
import { Icon } from "../components/Icon";
import { Loading } from "../components/Loading";
import { PeriodPicker, usePeriod } from "../components/PeriodPicker";
import { usePreferences } from "../i18n/Preferences";

const number = (value: string) => Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Money per currency, one line each (never added together); nothing is a real zero. */
function Money({ value }: { value: PerCurrency }) {
  const entries = Object.entries(value);
  if (entries.length === 0) return <span className="mono">0</span>;
  return (
    <span className="mono">
      {entries.map(([currency, amount]) => (
        <div key={currency}>
          {number(amount)} {currency}
        </div>
      ))}
    </span>
  );
}

/** A figure that may not be known: «مش متقاس» rather than a made-up zero. */
function Maybe({ value, unit }: { value: string | number | null; unit?: string }) {
  const { t } = usePreferences();
  if (value === null) return <span className="muted">{t("مش متقاس", "Not measured")}</span>;
  return (
    <span className="mono">
      {typeof value === "string" ? number(value) : value}
      {unit ? ` ${unit}` : ""}
    </span>
  );
}

function Tile({ label, children, tone = "", name }: { label: string; children: ReactNode; tone?: string; name: string }) {
  return (
    <div className={`kpi ${tone}`.trim()} data-ceo={name}>
      <div className="kpi__value">{children}</div>
      <div className="kpi__label">{label}</div>
    </div>
  );
}

function Section({ icon, title, children }: { icon: string; title: string; children: ReactNode }) {
  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="card__head">
        <Icon name={icon} />
        <h3>{title}</h3>
      </div>
      {children}
    </div>
  );
}

/**
 * The CEO board (the B2B requirements' section 21): sales, the work, the translators' load, the money and its profit, and
 * the money by client and by project - for a period, the owner's alone.
 */
export function CeoBoardPage() {
  const { t } = usePreferences();
  const me = useMe();
  const [from, to] = usePeriod();
  const allowed = me.data !== undefined && me.data.user.is_admin;
  const board = useCeoBoard(from, to, allowed);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = board.data;
  const shown = data ? { from: data.from, to: data.to } : { from, to };

  return (
    <>
      <div className="page-head">
        <h1>{t("لوحة الـCEO", "CEO board")}</h1>
        <span className="page-head__sub">
          {t(
            "الشركة كلها في صفحة: المبيعات والشغل والمترجمين والفلوس والربح، للفترة اللي تختارها. الفلوس كل عملة لوحدها، والربح بالجنيه.",
            "The whole company on one page: sales, the work, the translators, the money and the profit, for the period you choose. Money is per currency; profit is in EGP.",
          )}
        </span>
      </div>

      <PeriodPicker shown={shown} />

      {!data ? (
        board.isError ? (
          <div className="card empty" role="alert">
            <Icon name="alert" size="xl" />
            <span>{t("الفترة دي مش مظبوطة أو حصلت مشكلة في التحميل.", "That period is not valid, or it could not load.")}</span>
          </div>
        ) : (
          <Loading />
        )
      ) : (
        <>
          <Section icon="target" title={t("المبيعات", "Sales")}>
            <div className="grid grid--4">
              <Tile name="won_today" label={t("اتقفل النهارده (عروض اتقبلت)", "Won today (accepted quotations)")} tone="kpi--ok">
                <Money value={data.sales.today.won_value} />
              </Tile>
              <Tile name="new_leads" label={t("شركات جديدة", "New leads")}>
                <span className="mono">{data.sales.period.new_leads}</span>
              </Tile>
              <Tile name="quotations" label={t("عروض اتبعتت", "Quotations sent")}>
                <span className="mono">{data.sales.period.quotations}</span>
              </Tile>
              <Tile name="won_lost" label={t("Won / Lost", "Won / Lost")}>
                <span className="mono">
                  {data.sales.period.won} / {data.sales.period.lost}
                </span>
              </Tile>
              <Tile name="conversion" label={t("نسبة التحويل", "Conversion")}>
                <Maybe value={data.sales.period.conversion_rate} unit="%" />
              </Tile>
              <Tile name="sales_revenue" label={t("قيمة العروض اللي اتقبلت", "Accepted quotations' value")}>
                <Money value={data.sales.period.revenue} />
              </Tile>
            </div>
            {data.sales.people.length > 0 && (
              <div className="table-wrap" style={{ marginTop: 12 }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>{t("الـSales", "Sales person")}</th>
                      <th>{t("شركات جديدة", "New leads")}</th>
                      <th>{t("اتواصلنا معاهم", "Contacted")}</th>
                      <th>{t("عروض", "Quotations")}</th>
                      <th>Won</th>
                      <th>Lost</th>
                      <th>{t("نسبة التحويل", "Conversion")}</th>
                      <th>{t("قيمة اللي اتقبل", "Accepted value")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.sales.people.map((row) => (
                      <tr key={row.person.id} data-ceo-person={row.person.id}>
                        <td>{row.person.name}</td>
                        <td className="mono">{row.new_leads}</td>
                        <td className="mono">{row.contacted}</td>
                        <td className="mono">{row.quotations}</td>
                        <td className="mono">{row.won}</td>
                        <td className="mono">{row.lost}</td>
                        <td>
                          <Maybe value={row.conversion_rate} unit="%" />
                        </td>
                        <td>
                          <Money value={row.revenue} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>

          <Section icon="layers" title={t("الشغل والجودة", "Work and quality")}>
            <div className="grid grid--4">
              <Tile name="active" label={t("مشاريع شغالة", "Active projects")}>
                <span className="mono">{data.projects.active}</span>
              </Tile>
              <Tile name="late" label={t("متأخرة عن الديدلاين", "Past their deadline")} tone={data.projects.late > 0 ? "kpi--danger" : ""}>
                <span className="mono">{data.projects.late}</span>
              </Tile>
              <Tile name="delivered" label={t("اتسلّمت في الفترة", "Delivered in the period")}>
                <span className="mono">
                  {data.projects.delivered}
                  {data.projects.words_delivered > 0 && <div className="muted">{t(`${data.projects.words_delivered.toLocaleString()} كلمة`, `${data.projects.words_delivered.toLocaleString()} words`)}</div>}
                </span>
              </Tile>
              <Tile name="rework" label={t("رجعت للتعديل", "Sent back for rework")} tone="kpi--warn">
                <Maybe value={data.projects.rework_rate} unit="%" />
              </Tile>
              <Tile name="score" label={t("متوسط تقييم المراجعة", "Average review score")}>
                <Maybe value={data.projects.review_score} />
              </Tile>
              <Tile name="complaints" label={t("شكاوى عملاء (مفتوحة)", "Client complaints (open)")}>
                <span className="mono">
                  {data.projects.complaints} ({data.projects.complaints_open})
                </span>
              </Tile>
            </div>
          </Section>

          <Section icon="users" title={t("ضغط المترجمين", "Translator workload")}>
            <p className="muted">{t(`${data.workload.free} مترجم فاضي دلوقتي.`, `${data.workload.free} translator(s) free now.`)}</p>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("المترجم", "Translator")}</th>
                    <th>{t("تاسكات في إيده", "Tasks in hand")}</th>
                    <th>{t("الكلمات", "Words")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.workload.translators.map((row) => (
                    <tr key={row.id} data-ceo-translator={row.id}>
                      <td>{row.name}</td>
                      <td className="mono">{row.tasks}</td>
                      <td className="mono">{row.words ? row.words.toLocaleString() : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          <Section icon="chart" title={t("الفلوس", "Money")}>
            <div className="grid grid--4">
              <Tile name="invoiced" label={t(`اتفوتر في الفترة (${data.money.invoices} فاتورة)`, `Invoiced in the period (${data.money.invoices})`)}>
                <Money value={data.money.invoiced} />
              </Tile>
              <Tile name="received" label={t("اتحصّل في الفترة", "Collected in the period")} tone="kpi--ok">
                <Money value={data.money.received} />
              </Tile>
              <Tile name="owed" label={t("لسه ماتدفعش (كله)", "Still owed (all)")} tone="kpi--warn">
                <Money value={data.money.owed} />
              </Tile>
              <Tile name="overdue" label={t(`متأخر (${data.money.overdue_count} فاتورة)`, `Overdue (${data.money.overdue_count})`)} tone={data.money.overdue_count > 0 ? "kpi--danger" : ""}>
                <Money value={data.money.overdue} />
              </Tile>
              <Tile name="revenue" label={t("الإيراد بالجنيه", "Revenue in EGP")}>
                <Maybe value={data.money.revenue_egp} />
              </Tile>
              <Tile name="costs" label={t("التكلفة المباشرة بالجنيه", "Direct costs in EGP")}>
                <Maybe value={data.money.costs_egp} />
              </Tile>
              <Tile name="profit" label={t("إجمالي الربح بالجنيه", "Gross profit in EGP")} tone="kpi--ok">
                <Maybe value={data.money.profit_egp} />
              </Tile>
              <Tile name="margin" label={t("نسبة الربح", "Margin")}>
                <Maybe value={data.money.margin} unit="%" />
              </Tile>
            </div>
            {data.money.drafts > 0 && (
              <p className="muted" style={{ marginTop: 10 }}>
                <Link to="/accounts/invoices?show=draft">{t(`${data.money.drafts} فاتورة مسودة لسه ماتبعتتش`, `${data.money.drafts} draft invoice(s) not sent yet`)}</Link>
              </p>
            )}
            <p className="muted" style={{ marginTop: 10 }}>
              {t(
                "الإيراد = الفواتير اللي اتعملت في الفترة بسعر الصرف المكتوب على كل واحدة. لو فاتورة مالهاش سعر صرف، أو تكلفة مترجم مش محسوبة، الرقم بيبان «مش متقاس».",
                "Revenue = the invoices dated in the period, at each one's own exchange rate. If an invoice has no rate, or a translator's cost is not priced, the figure reads «Not measured».",
              )}
            </p>
          </Section>

          <div className="grid grid--2">
            <Section icon="contact" title={t("حسب العميل", "By client")}>
              {data.by_client.length ? (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>{t("العميل", "Client")}</th>
                        <th>{t("اتفوتر", "Invoiced")}</th>
                        <th>{t("الإيراد", "Revenue")}</th>
                        <th>{t("الربح", "Profit")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.by_client.map((row) => (
                        <tr key={row.code} data-ceo-client={row.code}>
                          <td>
                            <strong className="mono">{row.code}</strong>
                            {row.name && <div className="muted">{row.name}</div>}
                          </td>
                          <td>
                            <Money value={row.invoiced} />
                          </td>
                          <td>
                            <Maybe value={row.revenue_egp} />
                          </td>
                          <td>
                            <Maybe value={row.profit_egp} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="muted">{t("مفيش فواتير في الفترة دي.", "No invoices in this period.")}</p>
              )}
            </Section>

            <Section icon="file" title={t("حسب المشروع", "By project")}>
              {data.by_project.length ? (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>{t("المشروع", "Project")}</th>
                        <th>{t("السعر", "Price")}</th>
                        <th>{t("الربح", "Profit")}</th>
                        <th>%</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.by_project.map((row) => (
                        <tr key={row.invoice} data-ceo-project={row.invoice}>
                          <td>
                            <Link className="mono" to={`/accounts/invoices/${row.invoice_id}`}>
                              {row.invoice}
                            </Link>
                            <div className="muted mono">
                              {row.task || "—"} · {row.client}
                            </div>
                          </td>
                          <td className="mono">
                            {number(row.amount)} {row.currency}
                          </td>
                          <td>
                            <Maybe value={row.profit_egp} />
                          </td>
                          <td>
                            <Maybe value={row.margin} unit="%" />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="muted">{t("مفيش فواتير في الفترة دي.", "No invoices in this period.")}</p>
              )}
            </Section>
          </div>
        </>
      )}
    </>
  );
}
