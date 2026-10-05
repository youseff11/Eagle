import { Link } from "react-router";
import { useHrPerformanceBoard } from "../../api/queries";
import type { HrRankRow } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { Avatar } from "../Avatar";
import { MonthPicker } from "../accounts/MonthPicker";
import { Waiting } from "../accounts/shared";
import { Icon } from "../Icon";
import { Meter } from "./Meter";

/** Where one translator's own page is, in the month being looked at: a plain address, so it can be sent. */
export function personHref(id: number, period: string): string {
  const params = new URLSearchParams({ user: String(id) });
  if (period) params.set("period", period);
  return `/hr/performance?${params.toString()}`;
}

const ORDINAL: Record<number, string> = { 1: "1st", 2: "2nd", 3: "3rd" };

const words = (count: number) => count.toLocaleString("en-US");

/**
 * The three who delivered the most: the best in the middle and the tallest step, the second on one side, the third on the other.
 * HR and the admin press a step to open that person's figures (`linkPeople`); for everybody else it is a picture to look at.
 */
function Podium({ rows, period, linkPeople }: { rows: HrRankRow[]; period: string; linkPeople: boolean }) {
  const { t } = usePreferences();
  return (
    <div className="podium" data-board="podium">
      {rows.map((row) => {
        const common = {
          className: `podium__spot podium__spot--${row.rank}`,
          "data-rank": row.rank ?? undefined,
          "aria-label": `${ORDINAL[row.rank ?? 0] ?? ""} ${row.name}`,
        };
        const body = (
          <>
            <div className="podium__card">
              {row.rank === 1 && <Icon name="star" filled className="podium__star" />}
              <Avatar src={row.avatar} initials={row.initials} tone="" className="podium__face" />
              <b className="podium__name">{row.name}</b>
              <span className="podium__score mono">{row.score === null ? "—" : `${row.score}%`}</span>
              <small className="muted mono">
                {words(row.words)} {t("كلمة", "words")}
              </small>
              <small className="muted">
                {row.projects} {t("مشروع", "projects")}
              </small>
            </div>
            <div className="podium__step">
              <span className="podium__rank mono">{ORDINAL[row.rank ?? 0]}</span>
            </div>
          </>
        );
        return linkPeople ? (
          <Link key={row.id} to={personHref(row.id, period)} {...common}>
            {body}
          </Link>
        ) : (
          <div key={row.id} {...common}>
            {body}
          </div>
        );
      })}
    </div>
  );
}

/** Everybody the podium does not have: ranked by the same rule, then the ones who have delivered nothing yet, with no rank. */
function Rest({ rows, period, ranked, linkPeople }: { rows: HrRankRow[]; period: string; ranked: boolean; linkPeople: boolean }) {
  const { t } = usePreferences();
  return (
    <div className="card" data-board="rest">
      <div className="card__head">
        <Icon name="users" />
        <h3>{ranked ? t("باقي المترجمين", "The rest") : t("المترجمين", "Translators")}</h3>
        <span className="chip chip--sm mono">{rows.length}</span>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>#</th>
              <th>{t("المترجم", "Translator")}</th>
              <th>{t("الإنتاجية", "Productivity")}</th>
              <th>{t("الكلمات", "Words")}</th>
              <th>{t("المشاريع", "Projects")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const who = (
                <>
                  <Avatar src={row.avatar} initials={row.initials} tone="" className="avatar--sm" />
                  <span>{row.name}</span>
                </>
              );
              return (
                <tr key={row.id} data-user={row.id}>
                  <td className="mono muted">{row.rank ?? "—"}</td>
                  <td>
                    {linkPeople ? (
                      <Link className="row row--tight board-name" to={personHref(row.id, period)}>
                        {who}
                      </Link>
                    ) : (
                      <span className="row row--tight board-name board-name--plain">{who}</span>
                    )}
                  </td>
                  <td>
                    <div className="score-row">
                      <Meter score={row.score} band={row.band.value} />
                      {row.score === null ? (
                        <span className="chip chip--sm">{t("مابتتقاسش", "Not measured")}</span>
                      ) : (
                        <span className="score-row__value mono">{row.score}%</span>
                      )}
                    </div>
                  </td>
                  <td className="mono">
                    {words(row.words)}
                    {row.target ? <span className="muted"> / {words(row.target)}</span> : null}
                  </td>
                  <td className="mono">{row.projects}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * Who delivered the most in a month: the best three on a podium, everybody else below. Every employee reads it; HR and the
 * admin (`linkPeople`) also get a way into each person's own page. The score is the productivity indicator (words against the
 * target): the same figure that page shows.
 */
export function PerformanceBoard({ period, linkPeople, onPeriod }: { period: string; linkPeople: boolean; onPeriod: (period: string) => void }) {
  const { t } = usePreferences();
  const query = useHrPerformanceBoard(period);
  const data = query.data;
  if (!data) return <Waiting failed={query.isError} />;

  const nobody = data.podium.length === 0 && data.rest.length === 0;
  return (
    <>
      <div className="page-head">
        <h1>{t("الأداء", "Performance")}</h1>
        <div className="grow" />
        <MonthPicker periods={data.periods} year={data.year} month={data.month} onChange={onPeriod} className="input input--inline" />
      </div>
      <p className="muted board-lede">
        {t(
          "ترتيب المترجمين بالإنتاجية: الكلمات اللي اتسلّمت الشهر ده مقابل التارجت.",
          "Translators ranked by productivity: the words delivered this month against the target.",
        )}
        {linkPeople && " "}
        {linkPeople && t("دوس على أي اسم تشوف تفاصيله وسجل شهوره.", "Press a name for their details and monthly record.")}
      </p>

      {nobody ? (
        <div className="card empty">{t("مفيش مترجمين.", "There are no translators.")}</div>
      ) : (
        <>
          {data.podium.length > 0 ? (
            <Podium rows={data.podium} period={period} linkPeople={linkPeople} />
          ) : (
            <div className="note note--info" data-board="no-podium">
              <Icon name="info" />
              <div>{t("لسه مفيش كلمات اتسلّمت في الشهر ده، فمفيش ترتيب.", "Nothing has been delivered this month yet, so there is no ranking.")}</div>
            </div>
          )}
          {data.rest.length > 0 && <Rest rows={data.rest} period={period} ranked={data.podium.length > 0} linkPeople={linkPeople} />}
        </>
      )}
    </>
  );
}
