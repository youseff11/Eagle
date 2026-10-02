import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { NotificationLevel } from "../api/types";
import { usePreferences } from "../i18n/Preferences";
import { navigation } from "../lib/navigation";
import { safeInternalPath } from "../lib/safeUrl";
import { Icon } from "./Icon";

/** The small notices that slide in at the top: the same four looks and the same icons as the classic `toast()`. */
export interface ToastInput {
  level?: NotificationLevel;
  title: string;
  body?: string;
  /** Where a click goes. Only a path on this site is followed (`safeInternalPath`). */
  url?: string;
  /** Stays longer: a notice that needs to be read, not glanced at. */
  sticky?: boolean;
}

interface ToastItem extends ToastInput {
  key: number;
}

interface Toaster {
  push: (toast: ToastInput) => void;
}

const ICON: Record<NotificationLevel, string> = {
  info: "info",
  success: "check-circle",
  warning: "alert",
  danger: "alert",
};

/** Never more than four at once: the oldest goes first (as in the classic page). */
export const MAX_TOASTS = 4;
export const TOAST_MS = 7000;
export const STICKY_TOAST_MS = 15000;
const LEAVE_MS = 260;

// Outside a provider (a page drawn alone, in a test) a toast goes nowhere instead of throwing.
const ToastContext = createContext<Toaster>({ push: () => undefined });

export function useToasts(): Toaster {
  return useContext(ToastContext);
}

function ToastView({ item, onGone }: { item: ToastItem; onGone: (key: number) => void }) {
  const { t } = usePreferences();
  const [leaving, setLeaving] = useState(false);
  const level = item.level ?? "info";
  const href = item.url ? safeInternalPath(item.url) : null;

  useEffect(() => {
    let removal: number | undefined;
    const leave = window.setTimeout(
      () => {
        setLeaving(true);
        removal = window.setTimeout(() => onGone(item.key), LEAVE_MS);
      },
      item.sticky ? STICKY_TOAST_MS : TOAST_MS,
    );
    return () => {
      window.clearTimeout(leave);
      window.clearTimeout(removal);
    };
  }, [item.key, item.sticky, onGone]);

  const dismiss = () => {
    setLeaving(true);
    window.setTimeout(() => onGone(item.key), LEAVE_MS);
  };

  return (
    <div
      className={`toast toast--${level}${leaving ? " is-leaving" : ""}`}
      role={level === "danger" ? "alert" : "status"}
      style={href ? { cursor: "pointer" } : undefined}
      onClick={href ? () => navigation.assign(href) : undefined}
      data-toast={item.key}
    >
      <Icon name={ICON[level] ?? "info"} />
      <div>
        <div className="toast__title">{item.title}</div>
        {item.body && <div className="toast__body">{item.body}</div>}
      </div>
      <button
        type="button"
        className="toast__close"
        aria-label={t("اقفل", "Close")}
        onClick={(event) => {
          event.stopPropagation();
          dismiss();
        }}
      >
        <Icon name="x" />
      </button>
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counter = useRef(0);

  const push = useCallback((toast: ToastInput) => {
    counter.current += 1;
    const item = { ...toast, key: counter.current };
    setItems((current) => [...current, item].slice(-MAX_TOASTS));
  }, []);
  const gone = useCallback((key: number) => setItems((current) => current.filter((item) => item.key !== key)), []);
  const toaster = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={toaster}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map((item) => (
          <ToastView key={item.key} item={item} onGone={gone} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}
