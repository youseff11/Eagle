import { usePreferences } from "../i18n/Preferences";

/**
 * A staff member's name where work is listed (a task's people, a translator's share). Somebody the admin deleted from the staff
 * keeps their name on what they did, drawn in the "deleted" colour and saying so when hovered: the server says who (`gone`).
 */
export function PersonName({ name, gone = false }: { name: string | null | undefined; gone?: boolean }) {
  const { t } = usePreferences();
  if (!name) return <>—</>;
  if (!gone) return <>{name}</>;
  const said = t("موظف اتمسح", "Deleted employee");
  return (
    <span className="person-gone" data-gone="" title={said} aria-label={`${name} (${said})`}>
      {name}
    </span>
  );
}
