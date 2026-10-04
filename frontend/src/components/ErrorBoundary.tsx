import { Component, type ErrorInfo, type ReactNode } from "react";
import { usePreferences } from "../i18n/Preferences";
import { Icon } from "./Icon";

function Fallback() {
  const { t } = usePreferences();
  return (
    <div className="card">
      <div className="empty" role="alert">
        <Icon name="alert" size="xl" />
        <span>{t("حصلت مشكلة في عرض الصفحة دي.", "Something went wrong showing this page.")}</span>
        <div className="row">
          <button className="btn btn--sm" type="button" onClick={() => window.location.reload()}>
            {t("جرّب تاني", "Try again")}
          </button>
          <a className="btn btn--sm" href="/app/">
            {t("الرئيسية", "Home")}
          </a>
        </div>
      </div>
    </div>
  );
}

interface Props {
  children: ReactNode;
  /** Changing it (the path, say) gives the next page a fresh start. */
  resetKey?: string;
}

/**
 * A page that throws must not take the app down with it.
 *
 * The heartbeat runs above the pages, and it is what keeps a person shown as online and what
 * carries the 60-second assignment screen: a blank page that also stopped it would lose them
 * the assignment and cost them the rating penalty. So the failure stays inside the page: the
 * menu and the heartbeat carry on, and the way home is on screen.
 */
export class ErrorBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    console.error("A page failed to render", error, info.componentStack);
  }

  componentDidUpdate(previous: Props): void {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({ failed: false });
  }

  render() {
    return this.state.failed ? <Fallback /> : this.props.children;
  }
}
