import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { Link, useNavigate } from "react-router";
import { useNavTaskSearch } from "../api/queries";
import { usePreferences } from "../i18n/Preferences";
import { buildIndex, prepareIndex, searchPages, type SearchLine } from "../lib/navSearch";
import { Icon } from "./Icon";

/** One row of the answer: where it goes and how it reads. */
interface Hit {
  key: string;
  to: { pathname: string; hash: string };
  icon: string;
  /** The code of a task, drawn before its title. */
  code?: string;
  title: string;
  where: string;
}

const TASK_ICON: Record<string, string> = { whatsapp: "message", email: "mail" };

/**
 * Search the menu: the pages this person has a line for, the sections inside some of them, and their tasks.
 *
 * The pages answer at once, from the lines; the tasks join a moment later, under their own heading, because there are
 * thousands and the server decides which of them this person may open. Up and down move, Enter goes, Escape clears.
 * Ctrl+K from anywhere, or "/" when not already typing, comes here.
 */
export function NavSearch({ lines, onShortcut }: { lines: SearchLine[]; onShortcut?: () => void }) {
  const { t, lang } = usePreferences();
  const navigate = useNavigate();
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  // The tasks are asked for once the typing pauses, not on every letter.
  const [asked, setAsked] = useState("");
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);

  const index = useMemo(() => prepareIndex(buildIndex(lines)), [lines]);
  const text = query.trim();
  const found = useNavTaskSearch(asked);

  useEffect(() => {
    const timer = window.setTimeout(() => setAsked(text), 220);
    return () => window.clearTimeout(timer);
  }, [text]);

  const pages: Hit[] = useMemo(
    () =>
      searchPages(index, text).map((row) => ({
        key: `${row.path}#${row.hash}`,
        to: { pathname: row.path, hash: row.hash ? `#${row.hash}` : "" },
        icon: row.icon,
        title: lang === "ar" ? row.label[0] : row.label[1],
        where: lang === "ar" ? row.where[0] : row.where[1],
      })),
    [index, text, lang],
  );
  // An answer to an older typing is never shown under a newer one.
  const items = asked === text && found.data ? found.data.items : [];
  const tasks: Hit[] = items.map((task) => ({
    key: `task:${task.code}`,
    to: { pathname: `/tasks/${encodeURIComponent(task.code)}`, hash: "" },
    icon: TASK_ICON[task.origin] ?? "layers",
    code: task.code,
    title: task.title,
    where: [task.client, lang === "ar" ? task.status_ar : task.status_en].filter(Boolean).join(" · "),
  }));
  const shown = [...pages, ...tasks];
  const listed = shown.map((hit) => hit.key).join("|");
  const visible = open && text !== "";

  // The first answer is the one Enter takes, whenever the list changes under the cursor.
  useEffect(() => setCursor(0), [listed]);

  // Out of the way when you click anywhere else.
  useEffect(() => {
    const away = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("click", away);
    return () => document.removeEventListener("click", away);
  }, []);

  // Ctrl+K anywhere, or "/" when you are not already typing somewhere.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = Boolean(target && (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable));
      const ctrlK = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k";
      if (!ctrlK && !(event.key === "/" && !typing)) return;
      event.preventDefault();
      onShortcut?.();
      input.current?.focus();
      input.current?.select();
      setOpen(true);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onShortcut]);

  const finish = () => {
    setQuery("");
    setAsked("");
    setOpen(false);
    input.current?.blur();
  };

  const go = (hit: Hit | undefined) => {
    if (!hit) return;
    navigate(hit.to);
    finish();
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (shown.length) setCursor((now) => (now + (event.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      go(shown[cursor]);
    } else if (event.key === "Escape") {
      finish();
    }
  };

  // The row the cursor is on stays in view as it moves.
  useEffect(() => {
    const row = box.current?.querySelector(".nav-search__row.is-active");
    if (row && typeof row.scrollIntoView === "function") row.scrollIntoView({ block: "nearest" });
  }, [cursor, listed]);

  const row = (hit: Hit, at: number) => (
    <Link
      key={hit.key}
      id={`nav-hit-${at}`}
      className={`nav-search__row${at === cursor ? " is-active" : ""}`}
      role="option"
      aria-selected={at === cursor}
      to={hit.to}
      onClick={finish}
    >
      <Icon name={hit.icon} size="sm" />
      <span className="nav-search__body">
        <b>
          {hit.code && <span className="mono">{hit.code} </span>}
          {hit.title}
        </b>
        <span className="nav-search__where">{hit.where}</span>
      </span>
    </Link>
  );

  const placeholder = t("دوّر على صفحة أو تاسك…", "Search a page or a task…");
  return (
    <div className="nav-search" id="navSearch" ref={box}>
      <Icon name="search" size="sm" className="nav-search__ic" />
      <input
        ref={input}
        className="nav-search__input"
        id="navSearchInput"
        type="search"
        autoComplete="off"
        placeholder={placeholder}
        aria-label={placeholder}
        role="combobox"
        aria-expanded={visible}
        aria-controls="navSearchResults"
        aria-activedescendant={visible && shown.length ? `nav-hit-${cursor}` : undefined}
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      <kbd className="nav-search__kbd">Ctrl K</kbd>
      {visible && (
        <div className="nav-search__results" id="navSearchResults" role="listbox">
          {shown.length === 0 ? (
            <div className="nav-search__empty">{t("مفيش حاجة بالاسم ده.", "Nothing by that name.")}</div>
          ) : (
            <>
              {pages.map((hit, at) => row(hit, at))}
              {tasks.length > 0 && <div className="nav-search__head">{t("تاسكات", "Tasks")}</div>}
              {tasks.map((hit, at) => row(hit, pages.length + at))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
