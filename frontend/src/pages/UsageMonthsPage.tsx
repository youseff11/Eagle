import { Navigate } from "react-router";
import { useMe } from "../api/queries";
import { useUsageMonths, type UsageMonthCell } from "../api/usageMonths";
import { Loading } from "../components/Loading";
import { usePreferences } from "../i18n/Preferences";

function money(value: number): string {
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** One host's month: its figure, «مش متقاس» rather than a made-up zero, and what the figure is (the last read, counted since). */
function Cell({ cell }: { cell: UsageMonthCell }) {
  const { t, lang } = usePreferences();
  let shown;
  if (cell.state === "off") shown = <span className="muted">{t("مش متربط", "Not linked")}</span>;
  else if (cell.state === "error")
    shown = (
      <span className="muted" title={cell.error}>
        {t("مش متاح", "Unavailable")}
      </span>
    );
  else if (cell.usd !== null)
    shown = (
      <span className="mono" dir="ltr">
        {cell.estimate ? "≈ " : ""}
        {money(cell.usd)}
      </span>
    );
  else if (cell.amount)
    shown = (
      <span className="mono" dir="ltr">
        {cell.estimate ? "≈ " : ""}
        {cell.amount}
      </span>
    );
  else shown = <span className="muted">{t("مش متقاس", "Not measured")}</span>;
  return (
    <>
      {shown}
      {cell.note && <div className="muted" style={{ fontSize: "0.8em" }}>{lang === "ar" ? cell.note.ar : cell.note.en}</div>}
    </>
  );
}

/**
 * «سجل الدفع»: what each subscription's bill came to, month by month, and the month's total, the admin's alone. This month is
 * on top as the usage panel last read it; a month that is over is closed with each host's figure for the whole of it.
 */
export function UsageMonthsPage() {
  const { t, lang } = usePreferences();
  const me = useMe();
  const allowed = me.data !== undefined && me.data.user.is_admin;
  const history = useUsageMonths(allowed);

  if (me.data && !allowed) return <Navigate to="/" replace />;
  const data = history.data;

  return (
    <>
      <div className="page-head">
        <h1>{t("سجل الدفع", "Payment history")}</h1>
        <span className="page-head__sub">
          {t(
            "المفروض اتدفع كام لكل اشتراك في كل شهر، والإجمالي. الشهر الحالي لحد آخر قراية للوحة الاستهلاك، والشهر اللي خلص بيتقفل بالرقم بتاعه كله. ≈ يعني تقدير، و«مش متقاس» يعني مافيش رقم نعرفه.",
            "What each subscription should have cost each month, and the total. This month is as the usage panel last read it; a month that is over is closed with its whole figure. ≈ is an estimate; «Not measured» means there is no figure to know.",
          )}
        </span>
      </div>
      {history.isPending && <Loading />}
      {history.isError && <div className="card muted">{t("مش قادر يجيب السجل دلوقتي", "Could not get the history now")}</div>}
      {data && (
        <div className="card">
          <div className="table-wrap">
            <table className="table" data-usage-months>
              <thead>
                <tr>
                  <th>{t("الشهر", "Month")}</th>
                  {data.hosts.map((host) => (
                    <th key={host.key}>
                      <a href={host.link} target="_blank" rel="noreferrer noopener">
                        {host.name}
                      </a>
                    </th>
                  ))}
                  <th>{t("الإجمالي", "Total")}</th>
                </tr>
              </thead>
              <tbody>
                {data.months.map((row) => (
                  <tr key={row.month} data-month={row.month}>
                    <td>
                      <strong>{lang === "ar" ? row.label.ar : row.label.en}</strong>
                      {row.running ? (
                        <div className="muted" style={{ fontSize: "0.8em" }}>
                          {row.at
                            ? t(`لحد ${row.at.ar}`, `Up to ${row.at.en}`)
                            : t("لسه ماتقريش", "Not read yet")}
                        </div>
                      ) : (
                        !row.closed && (
                          <div className="muted" style={{ fontSize: "0.8em" }}>
                            {t("لسه بيتقفل", "Being closed")}
                          </div>
                        )
                      )}
                    </td>
                    {data.hosts.map((host) => (
                      <td key={host.key} data-host={host.key}>
                        {row.cells[host.key] && <Cell cell={row.cells[host.key]!} />}
                      </td>
                    ))}
                    <td data-total>
                      {row.total_usd === null ? (
                        <span className="muted">{t("مش متقاس", "Not measured")}</span>
                      ) : (
                        <strong className="mono" dir="ltr">
                          {row.estimate ? "≈ " : ""}
                          {money(row.total_usd)}
                        </strong>
                      )}
                      {row.total_usd !== null && !row.complete && (
                        <div className="muted" style={{ fontSize: "0.8em" }}>
                          {t("من غير اللي مش متقاس", "Without what is not measured")}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
