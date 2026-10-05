import { Loading } from "../Loading";
import { ApiError } from "../../api/client";
import { useMe } from "../../api/queries";
import type { AccountsViolation } from "../../api/types";
import { usePreferences } from "../../i18n/Preferences";
import { hasMoney } from "../../lib/payroll";

/** The people who run the month: Accounting and the admin (the same ones the doors let in). */
export function useMayRunTheMonth() {
  const me = useMe();
  const user = me.data?.user;
  return { me, allowed: user !== undefined && (user.role === "accounting" || user.is_admin) };
}

/** What a refused write says: the server's words when it gave some. */
export function refusal(error: unknown, fallback: string): string {
  return (error instanceof ApiError && error.detail) || fallback;
}

/** The deduction's price as the classic table draws it: days and/or an amount. */
export function Penalty({ row }: { row: AccountsViolation }) {
  const { t } = usePreferences();
  return (
    <>
      {hasMoney(row.penalty_days) && (
        <>
          {row.penalty_days} <span className="muted">{t("يوم", "days")}</span>{" "}
        </>
      )}
      {hasMoney(row.penalty_amount) && row.penalty_amount}
    </>
  );
}

/** A page that is loading, or could not load. */
export function Waiting({ failed }: { failed: boolean }) {
  const { t } = usePreferences();
  return failed ? (
    <div className="card empty" role="alert">
      <span>{t("حصلت مشكلة في التحميل.", "Could not load.")}</span>
    </div>
  ) : (
    <Loading className="card empty" />
  );
}
