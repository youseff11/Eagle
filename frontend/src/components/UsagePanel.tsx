import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import { qk } from "../api/keys";
import { useAdminUsage } from "../api/queries";
import type { UsageCard, UsageReport } from "../api/types";
import { usePreferences } from "../i18n/Preferences";
import { Icon } from "./Icon";

/** What a host's short error code means, in both languages. An unknown one (an HTTP status from the host) is shown as it is. */
const ERRORS: Record<string, [string, string]> = {
  key_refused: ["المفتاح مرفوض", "The key was refused"],
  unreachable: ["مش قادر يوصل له", "Could not reach it"],
  bad_answer: ["رد بحاجة مش مفهومة", "Answered something unreadable"],
  neon_org_missing: ["ناقص الـOrganization ID", "The organization ID is missing"],
  failed: ["حصل خطأ", "Something went wrong"],
};

function money(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : `$${value.toFixed(2)}`;
}

function Card({ card }: { card: UsageCard }) {
  const { t, lang } = usePreferences();
  return (
    <div className={`usage-card is-${card.state}`} data-host={card.key}>
      <div className="usage-card__head">
        <a href={card.link} target="_blank" rel="noreferrer noopener" className="usage-card__name">
          {card.name}
        </a>
        <span className="usage-card__amount">
          {card.state === "ok"
            ? `${card.estimate ? "≈ " : ""}${card.amount || money(card.month_usd)}`
            : card.state === "off"
              ? t("مش متربط", "Not linked")
              : t("مش متاح", "Unavailable")}
        </span>
      </div>
      {card.state === "error" && (
        <div className="usage-card__error">{ERRORS[card.error] ? t(...ERRORS[card.error]!) : card.error}</div>
      )}
      {card.state === "ok" &&
        card.lines.map((line) => (
          <div className="usage-card__line" key={line.en}>
            <span>{lang === "ar" ? line.ar : line.en}</span>
            <span dir="ltr">{line.value}</span>
          </div>
        ))}
    </div>
  );
}

/**
 * The admin's usage panel at the foot of the menu: this month's bill so far at Bunny, Neon, Render, Claude and Meta, and the
 * total of those billed in dollars.
 * Shut it shows the total only; open it shows each host's card. The server asks the hosts at most every ten minutes;
 * «حدّث» asks them again now.
 */
export function UsagePanel() {
  const { t, lang } = usePreferences();
  const client = useQueryClient();
  const report = useAdminUsage();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const data = report.data;
  const linked = data ? data.cards.some((card) => card.state !== "off") : false;

  const refresh = async () => {
    setBusy(true);
    try {
      client.setQueryData(qk.adminUsage, await api<UsageReport>("/api/v1/admin/usage/?fresh=1"));
    } catch {
      // The panel keeps what it had; the next look asks again.
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`usage-panel${open ? " is-open" : ""}`}>
      <button type="button" className="usage-panel__head" aria-expanded={open} onClick={() => setOpen((was) => !was)}>
        <Icon name="chart" size="sm" />
        <span className="usage-panel__title">{t("استهلاك الشهر", "This month's usage")}</span>
        <span className="usage-panel__total" dir="ltr">
          {report.isPending ? "…" : data?.total_usd != null ? `${data.estimate ? "≈ " : ""}${money(data.total_usd)}` : "-"}
        </span>
        <Icon name="chevron-down" size="sm" className="usage-panel__chev" />
      </button>
      {open && (
        <div className="usage-panel__body">
          {report.isError && <div className="usage-card__error">{t("مش قادر يجيب الأرقام دلوقتي", "Could not get the numbers now")}</div>}
          {data && data.cards.map((card) => <Card card={card} key={card.key} />)}
          {data && !linked && (
            <Link to="/admin/settings" className="usage-panel__setup">
              {t("حط المفاتيح من الإعدادات ← متابعة الاستهلاك", "Add the keys in Settings, Usage and bills")}
            </Link>
          )}
          {data && (
            <div className="usage-panel__foot">
              <span>
                {t("آخر تحديث", "Updated")} {lang === "ar" ? data.at.ar : data.at.en}
              </span>
              <button type="button" className="usage-panel__refresh" onClick={refresh} disabled={busy}>
                <Icon name="refresh" size="sm" />
                {busy ? t("بيحدّث...", "Updating...") : t("حدّث", "Refresh")}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
