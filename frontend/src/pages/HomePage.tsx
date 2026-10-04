import { Navigate } from "react-router";
import { useMe } from "../api/queries";
import type { Role } from "../api/types";

/** Where each role starts: the screen its work is on (the address the classic `/` used to send them to). */
export const LANDING: Record<Role, string> = {
  admin: "/admin",
  operation: "/inbox",
  team_lead: "/lead",
  translator: "/translator",
  hr: "/hr/recruitment",
  reviewer: "/reviewer/tests",
  accounting: "/accounts",
  sales: "/clients",
};

/**
 * `/`: nothing to show of its own. Everybody has a screen their work is on, so this hands them to it.
 *
 * A role this app does not know (a server newer than the page) lands on the notifications, which every role has.
 */
export function HomePage() {
  const me = useMe();
  if (!me.data) return null;
  return <Navigate to={LANDING[me.data.user.role] ?? "/notifications"} replace />;
}
